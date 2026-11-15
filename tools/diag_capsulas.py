"""Diagnóstico de cápsulas perdidas: ¿por qué capsule_guard no evita que nos las coman?

SOLO MIDE. No cambia el comportamiento del agente:
  - envuelve (monkeypatch) métodos de SmartAgent solo para REGISTRAR qué ha decidido;
  - no consume números aleatorios (no se importa random);
  - lo caro (recalcular capsule_guard_action como contrafactual) se hace al FINAL de la
    partida, fuera del tiempo de los agentes.
Comprobación de que no altera las partidas: con --verificar A.json (salida de defensa_bench con
las mismas semillas) compara el marcador partida a partida.

Uso (desde la raíz del repo, venv activado):
    python tools/diag_capsulas.py --rivales tian__greedy_v4 --mapas 40 --salida diag_g0.json
    python tools/diag_capsulas.py --params '{"capsule_guard": 1}' --rivales tian__greedy_v4 --mapas 40
    python tools/diag_capsulas.py --resumen diag_g0.json diag_g1.json
Modo interno (una partida): python tools/diag_capsulas.py --una -r ... -b ... (lo usa el driver).
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST = os.path.join(REPO, 'pacman-contest', 'src', 'contest')
sys.path.insert(0, os.path.join(REPO, 'tools'))

WINDOW_BACK = 60      # movimientos (de los 4 agentes) hacia atrás que guardamos por evento como máximo
AFTER = 160           # movimientos tras la cápsula para medir lo que deposita el rival (40 por agente)


# ----------------------------------------------------------------------------------------------
# Una partida instrumentada
# ----------------------------------------------------------------------------------------------

def run_single(argv, our_file):
    sys.path.insert(0, os.getcwd())
    import contest.capture as capture

    our_file = os.path.abspath(our_file)
    S = {'agents': [], 'red': None, 'hist': {}, 'caps_prev': None, 'events': [], 'decisions': []}

    # --- 1) Enganche en la carga del equipo: envolvemos la clase de NUESTROS agentes ---
    orig_load = capture.load_agents

    def load_agents(is_red, agent_file, cmd_line_args):
        agents = orig_load(is_red, agent_file, cmd_line_args)
        f = agent_file if agent_file.endswith('.py') else agent_file + '.py'
        if os.path.abspath(f) == our_file and agents and agents[0] is not None:
            S['agents'] = list(agents)
            S['red'] = is_red
            patch_class(type(agents[0]), S)
        return agents

    capture.load_agents = load_agents

    # --- 2) Enganche en cada jugada REAL (estado verdadero, no observación) ---
    orig_process = capture.CaptureRules.process

    def process(state, game):
        tl = state.data.timeleft
        ads = state.data.agent_states
        S['hist'][tl] = [(a.get_position(), a.is_pacman, a.scared_timer, a.num_carrying, a.num_returned)
                         for a in ads]
        caps = list(state.data.capsules)
        if S['caps_prev'] is not None and S['red'] is not None:
            half = state.data.layout.width // 2
            for c in S['caps_prev']:
                if c not in caps and ((c[0] < half) == S['red']):
                    S['events'].append({'tl': tl, 'cap': c, 'eater': getattr(state.data, '_agent_moved', None)})
        S['caps_prev'] = caps
        return orig_process(state, game)

    capture.CaptureRules.process = staticmethod(process)

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        opts = capture.read_command(argv)
        games = capture.run_games(**opts)
    g = games[0]
    out = {'score': g.state.data.score, 'events': analyze(S)}
    print('RESULT ' + json.dumps(out))


def patch_class(cls, S):
    """Registra decisiones. Lo único que hacen los wrappers es guardar referencias y copiar
    resultados; el cálculo del agente es exactamente el original."""
    if getattr(cls, '_diag_patched', False):
        return
    cls._diag_patched = True
    o_choose, o_defend = cls.choose_action, cls.defend
    o_guard, o_icpt = cls.capsule_guard_action, cls.intercept_action
    cls._diag_orig_guard = o_guard   # para el contrafactual al final de la partida
    S['params'] = o_choose.__globals__['PARAMS']   # el módulo no queda en sys.modules

    def choose_action(self, gs):
        self._d = {'defend': False, 'inv': None, 'guard': 'no_llamado', 'icpt': 'no_llamado'}
        act = o_choose(self, gs)
        d = self._d
        S['decisions'].append({'tl': gs.data.timeleft, 'i': self.index, 'role': self.brain.roles.get(self.index),
                               'act': act, 'gs': gs, 'agent': self, **d})
        return act

    def defend(self, gs):
        # Lista de invasores tal y como la ve defend() (misma construcción; most_likely es de solo lectura).
        if getattr(self, '_d', None) is not None and not self._d['defend']:
            self._d['defend'] = True
            inv = []
            for i in self.get_opponents(gs):
                st = gs.get_agent_state(i)
                if not st.is_pacman:
                    continue
                pos = st.get_position()
                if pos is not None:
                    inv.append((i, pos, st.num_carrying, True))
                else:
                    est = self.tracker.most_likely(i)
                    if est is not None:
                        inv.append((i, est, st.num_carrying, False))
            self._d['inv'] = inv
        return o_defend(self, gs)

    def capsule_guard_action(self, gs, my_pos, invaders):
        r = o_guard(self, gs, my_pos, invaders)
        if getattr(self, '_d', None) is not None:
            self._d['guard'] = 'none' if r is None else str(r)
        return r

    def intercept_action(self, gs, my_pos, ipos):
        r = o_icpt(self, gs, my_pos, ipos)
        if getattr(self, '_d', None) is not None:
            self._d['icpt'] = 'none' if r is None else str(r)
        return r

    cls.choose_action, cls.defend = choose_action, defend
    cls.capsule_guard_action, cls.intercept_action = capsule_guard_action, intercept_action


# ----------------------------------------------------------------------------------------------
# Análisis (al final de la partida: fuera del tiempo de los agentes)
# ----------------------------------------------------------------------------------------------

def analyze(S):
    if not S['agents']:
        return []
    ag = S['agents'][0]
    params = S['params']
    radius = params['capsule_radius']
    D = ag.get_maze_distance
    ours = [a.index for a in S['agents']]
    H = S['hist']
    tls = sorted(H, reverse=True)          # orden temporal (timeleft decrece)
    pos_of = {tl: k for k, tl in enumerate(tls)}
    out = []
    for ev in S['events']:
        tl, cap, e = ev['tl'], tuple(ev['cap']), ev['eater']
        k = pos_of[tl]
        prev = H[tls[k - 1]] if k > 0 else H[tl]
        epos_prev = prev[e][0]
        # Inicio de la incursión del comedor y primera entrada en el radio de la cápsula.
        start_k = k
        while start_k - 1 >= 0 and H[tls[start_k - 1]][e][1] and k - (start_k - 1) <= 400:
            start_k -= 1
        entry_k = None
        for j in range(start_k, k + 1):
            p = H[tls[j]][e][0]
            if p is not None and D(p, cap) <= radius:
                entry_k = j
                break
        if entry_k is None:
            entry_k = k
        entry = H[tls[entry_k]]
        e_entry_d = D(entry[e][0], cap)
        our_entry = []
        for i in ours:
            p, pac, sc = entry[i][0], entry[i][1], entry[i][2]
            our_entry.append({'i': i, 'd_cap': D(p, cap), 'pacman': pac, 'scared': sc})
        # Fantasma nuestro (no pacman, no asustado) más cercano al comedor justo antes de comer.
        ghost_d = [D(prev[i][0], epos_prev) for i in ours if not prev[i][1] and prev[i][2] == 0]
        min_ghost = min(ghost_d) if ghost_d else None
        visible_prev = any(abs(prev[i][0][0] - epos_prev[0]) + abs(prev[i][0][1] - epos_prev[1]) <= 5
                           for i in ours)
        # Decisiones nuestras en la ventana [entrada en el radio, comer]
        tl_hi, tl_lo = tls[entry_k] + 1, tl + 1   # decisión en timeleft T -> jugada en T-1
        win = [d for d in S['decisions'] if tl_lo <= d['tl'] <= tl_hi]
        n_def = sum(1 for d in win if d['role'] == 'defend')
        n_def_scared0 = 0
        guard_called = guard_act = guard_cf = icpt_act = stops = 0
        cf_route_none = cf_no_inv = 0
        track_err, track_n, eater_seen = 0, 0, 0
        roles = {}
        for d in win:
            roles[d['role']] = roles.get(d['role'], 0) + 1
            if d['role'] != 'defend' or not d['defend']:
                continue
            a, gs = d['agent'], d['gs']
            if gs.get_agent_state(a.index).scared_timer == 0:
                n_def_scared0 += 1
            if d['guard'] != 'no_llamado':
                guard_called += 1
            if d['guard'] not in ('no_llamado', 'none'):
                guard_act += 1
            if d['icpt'] not in ('no_llamado', 'none'):
                icpt_act += 1
            if d['act'] == 'Stop':
                stops += 1
            inv = d['inv'] or []
            # Contrafactual: ¿qué habría devuelto capsule_guard_action con lo que veía el agente?
            my_pos = gs.get_agent_position(a.index)
            cf = type(a)._diag_orig_guard(a, gs, my_pos, [(x[1], x[2], x[3]) for x in inv])
            if cf is not None:
                guard_cf += 1
            else:
                caps_now = a.get_capsules_you_are_defending(gs)
                if any(D(x[1], c) <= radius for x in inv for c in caps_now):
                    cf_route_none += 1      # hay invasor (visto o estimado) en el radio: no llego antes que él
                else:
                    cf_no_inv += 1          # el defensor no cree que haya invasor en el radio
            for x in inv:
                if x[0] == e:
                    # La observación con timeleft T es el estado tras la jugada que dejó timeleft T.
                    true_p = H[d['tl']][e][0] if d['tl'] in H else None
                    if x[3]:
                        eater_seen += 1
                    elif true_p is not None:
                        track_err += D(x[1], true_p)
                        track_n += 1
        # Lo que deposita el rival en los AFTER movimientos siguientes y si el comedor muere antes de depositar.
        rivals = [i for i in range(len(H[tl])) if i not in ours]
        ret0 = sum(H[tl][i][4] for i in rivals)
        k2 = min(len(tls) - 1, k + AFTER)
        ret1 = sum(H[tls[k2]][i][4] for i in rivals)
        eater_died = False
        for j in range(k + 1, k2 + 1):
            st = H[tls[j]][e]
            if not st[1]:
                prevst = H[tls[j - 1]][e]
                eater_died = st[4] == prevst[4] and prevst[3] > 0
                break
        out.append({
            'tl': tl, 'cap': cap, 'eater_carry': prev[e][3], 'eater_turns': (k - start_k) // 4,
            'our_scared_before': any(prev[i][2] > 0 and not prev[i][1] for i in ours),
            'e_entry_d': e_entry_d, 'our_entry': our_entry, 'entry_moves_before': k - entry_k,
            'min_ghost_d': min_ghost, 'visible_prev': visible_prev,
            'roles': roles, 'n_def': n_def, 'n_def_scared0': n_def_scared0,
            'guard_called': guard_called, 'guard_act': guard_act, 'guard_cf': guard_cf, 'icpt_act': icpt_act,
            'cf_route_none': cf_route_none, 'cf_no_inv': cf_no_inv,
            'stops': stops, 'eater_seen': eater_seen, 'track_err': (track_err / track_n) if track_n else None,
            'their_dep_after': ret1 - ret0, 'eater_died': eater_died,
        })
    return out


# ----------------------------------------------------------------------------------------------
# Driver: mismas partidas y semillas que defensa_bench.py
# ----------------------------------------------------------------------------------------------

def play(job):
    import defensa_bench as db
    team, params, rival_name, rival, lay, we_red = job
    r, b = (team, rival) if we_red else (rival, team)
    seed = f'def-{rival_name}-{lay}-{we_red}'   # misma semilla que defensa_bench.py
    cmd = [sys.executable, os.path.abspath(__file__), '--una', '--nuestro', team, '--',
           '-r', r, '-b', b, '-l', lay, '-Q', '--delay-step', '0', '-c', '--setRandomSeed', seed]
    env = dict(os.environ, PACMAN_PARAMS=json.dumps(params))
    try:
        p = subprocess.run(cmd, cwd=CONTEST, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return None
    line = [l for l in p.stdout.splitlines() if l.startswith('RESULT ')]
    if not line:
        sys.stderr.write(p.stderr[-2000:])
        return None
    res = json.loads(line[0][7:])
    return {'rival': rival_name, 'lay': lay, 'we_red': we_red,
            'score': res['score'] if we_red else -res['score'], 'events': res['events']}


def resumen(paths):
    for path in paths:
        data = json.load(open(path))
        games = data['partidas']
        ev = [x for g in games for x in g['events']]
        n = len(games)
        print(f"\n=== {path}  params={data['params']}  partidas={n}  cápsulas perdidas={len(ev)} "
              f"({len(ev) / max(n, 1):.2f}/partida)")
        if not ev:
            continue
        def pct(f):
            return 100.0 * sum(1 for x in ev if f(x)) / len(ev)
        cats = {}
        for x in ev:
            c = categoria(x)
            cats[c] = cats.get(c, 0) + 1
        print('Categoría (primera que aplica)              %     n')
        for c in CATS:
            print(f"  {c:40s} {100.0 * cats.get(c, 0) / len(ev):5.1f} {cats.get(c, 0):5d}")
        print('Indicadores (no excluyentes)')
        print(f"  ya estábamos asustados al comérsela        {pct(lambda x: x['our_scared_before']):5.1f} %")
        print(f"  ningún agente en 'defend' en la ventana    {pct(lambda x: x['n_def'] == 0):5.1f} %")
        print(f"  capsule_guard llamado alguna vez           {pct(lambda x: x['guard_called'] > 0):5.1f} %")
        print(f"  capsule_guard devolvió acción (real)       {pct(lambda x: x['guard_act'] > 0):5.1f} %")
        print(f"  capsule_guard devolvería acción (contraf.) {pct(lambda x: x['guard_cf'] > 0):5.1f} %")
        print(f"  guard None porque no ve invasor en el radio (alguna vez) "
              f"{pct(lambda x: x['cf_no_inv'] > 0):5.1f} %")
        print(f"  guard None porque llega tarde (alguna vez)  {pct(lambda x: x['cf_route_none'] > 0):5.1f} %")
        print(f"  algún defensor más cerca de la cápsula que él al entrar en el radio "
              f"{pct(lambda x: any(o['d_cap'] < x['e_entry_d'] and not o['pacman'] for o in x['our_entry'])):5.1f} %")
        print(f"  fantasma nuestro no asustado a <=3 justo antes (¿huida?) "
              f"{pct(lambda x: x['min_ghost_d'] is not None and x['min_ghost_d'] <= 3):5.1f} %")
        print(f"  comedor visible justo antes                {pct(lambda x: x['visible_prev']):5.1f} %")
        errs = [x['track_err'] for x in ev if x['track_err'] is not None]
        if errs:
            print(f"  error medio del tracker (invasor oculto)   {sum(errs) / len(errs):5.1f} casillas (n={len(errs)})")
        m = lambda k: sum(x[k] for x in ev) / len(ev)
        print(f"  comida que lleva al comerla {m('eater_carry'):.1f}; turnos en nuestro campo {m('eater_turns'):.1f}; "
              f"movs. desde que entra en el radio {m('entry_moves_before'):.1f}")
        print(f"  rival deposita en los 40 turnos siguientes {m('their_dep_after'):.1f}; "
              f"comedor muere antes de volver {pct(lambda x: x['eater_died']):.1f} %")
        rol = {}
        for x in ev:
            for r_, c_ in x['roles'].items():
                rol[r_] = rol.get(r_, 0) + c_
        tot = sum(rol.values()) or 1
        print('  roles de nuestros agentes en la ventana: ' +
              ', '.join(f"{r_} {100.0 * c_ / tot:.0f} %" for r_, c_ in sorted(rol.items(), key=lambda kv: -kv[1])))


CATS = ['ya_asustados', 'sin_defensor_en_ventana', 'guard_no_actua_llega_tarde',
        'guard_actua_y_se_pierde', 'guard_apagado_habria_actuado', 'otro']


def categoria(x):
    if x['our_scared_before']:
        return 'ya_asustados'
    if x['n_def'] == 0:
        return 'sin_defensor_en_ventana'
    if x['guard_act'] > 0:
        return 'guard_actua_y_se_pierde'
    if x['guard_cf'] > 0:
        return 'guard_apagado_habria_actuado'
    if x['guard_cf'] == 0:
        return 'guard_no_actua_llega_tarde'
    return 'otro'


def main():
    if '--una' in sys.argv:
        i = sys.argv.index('--nuestro')
        sep = sys.argv.index('--')
        return run_single(sys.argv[sep + 1:], sys.argv[i + 1])
    import defensa_bench as db
    ap = argparse.ArgumentParser()
    ap.add_argument('--team', default=os.path.join(REPO, 'my_team.py'))
    ap.add_argument('--params', default='{}')
    ap.add_argument('--rivales', nargs='*', default=['tian__greedy_v4'])
    ap.add_argument('--mapas', type=int, default=40)
    ap.add_argument('--fijos', type=int, default=10)
    ap.add_argument('--desde', type=int, default=1)
    ap.add_argument('--salida')
    ap.add_argument('--resumen', nargs='+')
    ap.add_argument('--verificar', help='JSON de defensa_bench con las mismas partidas: compara marcadores')
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 2)
    a = ap.parse_args()
    if a.resumen:
        return resumen(a.resumen)
    team = os.path.abspath(a.team)
    params = json.loads(a.params)
    layouts = db.FIXED[:a.fijos] + [f'RANDOM{s}' for s in range(a.desde, a.desde + a.mapas)]
    jobs = []
    for name in a.rivales:
        path = db.resolve(name)
        if path is None:
            print('Rival no encontrado:', name)
            continue
        for lay in layouts:
            for we_red in (True, False):
                jobs.append((team, params, name, path, lay, we_red))
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(play, jobs))
    games = [r for r in res if r is not None]
    data = {'params': params, 'layouts': layouts, 'errores': len(res) - len(games), 'partidas': games}
    if a.salida:
        json.dump(data, open(a.salida, 'w'), indent=1)
    if a.verificar:
        ref = json.load(open(a.verificar))
        refs = {(r['lay'], r['we_red'], k): r['score'] for k, v in ref['filas'].items() for r in v}
        same = diff = 0
        for g in games:
            key = (g['lay'], g['we_red'], g['rival'])
            if key in refs:
                same += refs[key] == g['score']
                diff += refs[key] != g['score']
        print(f"Verificación contra {a.verificar}: marcador idéntico en {same}, distinto en {diff}")
    print(f"Partidas: {len(games)}  errores: {data['errores']}")
    if a.salida:
        resumen([a.salida])


if __name__ == '__main__':
    main()
