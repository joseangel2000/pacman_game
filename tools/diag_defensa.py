"""Diagnóstico "esperar o cazar": ¿qué hace nuestro defensor mientras hay un invasor y cómo acaba cada invasión?

SOLO MIDE (igual que diag_capsulas.py): envuelve métodos de SmartAgent para registrar, sin cambiar su
resultado, sin usar random, y analiza al final de la partida. --verificar compara marcadores con un JSON
de defensa_bench de las mismas partidas.

Para cada turno de un agente nuestro en rol 'defend' con algún invasor REAL en nuestro campo:
  - rama: asustado / intercepta en su ruta / va a la puerta (intercept_fallback) / otra (persecución...)
  - acción: quieto (STOP), se acerca o no al invasor más cercano (estado real)
  - contexto: invasor en callejón, visible, carga
Para cada invasión (rival pasa de fantasma a pacman y vuelve): cómo acaba (comido / deposita / vuelve
vacío / fin de partida), duración, comida depositada y, si deposita, a qué distancia estaba nuestro
fantasma más cercano de la casilla por la que salió.

Uso (desde la raíz del repo, venv activado):
    python tools/diag_defensa.py --rivales tian__greedy_v4 --mapas 40 --salida d.json --verificar m.json
    python tools/diag_defensa.py --resumen d.json
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


# ----------------------------------------------------------------------------------------------
# Una partida instrumentada
# ----------------------------------------------------------------------------------------------

def run_single(argv, our_file):
    sys.path.insert(0, os.getcwd())
    import contest.capture as capture
    our_file = os.path.abspath(our_file)
    S = {'agents': [], 'hist': {}, 'decisions': []}

    orig_load = capture.load_agents

    def load_agents(is_red, agent_file, cmd_line_args):
        agents = orig_load(is_red, agent_file, cmd_line_args)
        f = agent_file if agent_file.endswith('.py') else agent_file + '.py'
        if os.path.abspath(f) == our_file and agents and agents[0] is not None:
            S['agents'] = list(agents)
            patch_class(type(agents[0]), S)
        return agents

    capture.load_agents = load_agents
    orig_process = capture.CaptureRules.process

    def process(state, game):
        S.setdefault('caps', {})[state.data.timeleft] = len(state.data.capsules)
        S['hist'][state.data.timeleft] = [(a.get_position(), a.is_pacman, a.scared_timer, a.num_carrying,
                                           a.num_returned) for a in state.data.agent_states]
        return orig_process(state, game)

    capture.CaptureRules.process = staticmethod(process)
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        games = capture.run_games(**capture.read_command(argv))
    g = games[0]
    out = {'score': g.state.data.score}
    out.update(analyze(S))
    print('RESULT ' + json.dumps(out))


def patch_class(cls, S):
    if getattr(cls, '_diagdef_patched', False):
        return
    cls._diagdef_patched = True
    o_choose, o_icpt, o_route = cls.choose_action, cls.intercept_action, cls.route_cell
    S['params'] = o_choose.__globals__['PARAMS']

    def choose_action(self, gs):
        self._dd = {'icpt': None, 'rc': 'no', 'in_icpt': False}
        act = o_choose(self, gs)
        S['decisions'].append((gs.data.timeleft, self.index, self.brain.roles.get(self.index), act,
                               self._dd['icpt'], self._dd['rc']))
        return act

    def intercept_action(self, gs, my_pos, ipos):
        d = getattr(self, '_dd', None)
        if d is not None:
            d['in_icpt'] = True
        r = o_icpt(self, gs, my_pos, ipos)
        if d is not None:
            d['in_icpt'] = False
            d['icpt'] = None if r is None else str(r)
        return r

    def route_cell(self, *a, **k):
        r = o_route(self, *a, **k)
        d = getattr(self, '_dd', None)
        if d is not None and d['in_icpt']:
            d['rc'] = 'none' if r is None else 'cell'
        return r

    cls.choose_action, cls.intercept_action, cls.route_cell = choose_action, intercept_action, route_cell


def analyze(S):
    if not S['agents']:
        return {'turns': [], 'episodes': []}
    ag = S['agents'][0]
    D = ag.get_maze_distance
    ours = [a.index for a in S['agents']]
    H = S['hist']
    tls = sorted(H, reverse=True)
    n_ag = len(H[tls[0]])
    rivals = [i for i in range(n_ag) if i not in ours]
    pockets = ag.pockets
    gates = ag.gates

    # --- Turnos de nuestros defensores con invasor real presente ---
    turns = []
    for tl, i, role, act, icpt, rc in S['decisions']:
        if role != 'defend' or tl not in H:
            continue
        st = H[tl]
        invs = [e for e in rivals if st[e][1]]
        if not invs:
            continue
        me = st[i][0]
        if st[i][1]:
            continue  # aún somos pacman volviendo a casa
        e = min(invs, key=lambda x: D(me, st[x][0]))
        ip = st[e][0]
        d0 = D(me, ip)
        vec = {'North': (0, 1), 'South': (0, -1), 'East': (1, 0), 'West': (-1, 0), 'Stop': (0, 0)}[act]
        nxt = (int(me[0] + vec[0]), int(me[1] + vec[1]))
        d1 = D(nxt, ip)
        if st[i][2] > 0:
            rama = 'asustado'
        elif icpt is not None and rc == 'cell':
            rama = 'intercepta_ruta'
        elif icpt is not None:
            rama = 'puerta_fallback'
        else:
            rama = 'persigue_u_otra'
        vis = any(abs(st[j][0][0] - ip[0]) + abs(st[j][0][1] - ip[1]) <= 5 for j in ours)
        turns.append({'rama': rama, 'stop': act == 'Stop', 'acerca': d1 < d0, 'd': d0,
                      'pocket': ip in pockets, 'vis': vis, 'carry': st[e][3],
                      'en_puerta': me in gates})

    # --- Invasiones ---
    eps = []
    for e in rivals:
        k = 1
        while k < len(tls):
            if H[tls[k]][e][1] and not H[tls[k - 1]][e][1]:
                s_k = k
                while k < len(tls) and H[tls[k]][e][1]:
                    k += 1
                last = H[tls[k - 1]]
                dur = (k - s_k + 3) // 4
                maxc = max(H[tls[j]][e][3] for j in range(s_k, k))
                vis_t = sum(1 for j in range(s_k, k)
                            if any(abs(H[tls[j]][o][0][0] - H[tls[j]][e][0][0]) +
                                   abs(H[tls[j]][o][0][1] - H[tls[j]][e][0][1]) <= 5 for o in ours))
                scared = any(H[tls[j]][o][2] > 0 and not H[tls[j]][o][1] for j in range(s_k, k) for o in ours)
                if k >= len(tls):
                    fin, dep, dexit = 'fin_partida', 0, None
                else:
                    now = H[tls[k]]
                    dep = now[e][4] - last[e][4]
                    if dep > 0:
                        fin = 'deposita'
                    elif D(now[e][0], last[e][0]) > 1:
                        fin = 'comido'          # salto de más de una casilla = respawn tras morir
                    else:
                        fin = 'vuelve_vacio'
                    exit_cell = last[e][0]
                    ghosts = [D(last[o][0], exit_cell) for o in ours if not last[o][1]]
                    dexit = min(ghosts) if ghosts else None
                    calm = [D(last[o][0], exit_cell) for o in ours if not last[o][1] and last[o][2] == 0]
                    dexit_calm = min(calm) if calm else None
                    near = [o for o in ours if not last[o][1] and D(last[o][0], exit_cell) == dexit]
                    scared_exit = bool(near) and last[near[0]][2] > 0
                    other_gate = bool(near) and last[near[0]][0] in gates and last[near[0]][0] != exit_cell
                caps = S['caps']
                cap_eaten = caps.get(tls[k - 1], 0) < caps.get(tls[s_k - 1], 0) if s_k > 0 else False
                ext = {} if k >= len(tls) else {'d_exit_calm': dexit_calm, 'scared_exit': scared_exit,
                                                 'other_gate': other_gate}
                eps.append(dict({'fin': fin, 'dur': dur, 'maxc': maxc, 'dep': dep, 'd_exit': dexit,
                                 'vis_frac': vis_t / max(1, k - s_k), 'scared': scared,
                                 'cap_eaten': cap_eaten}, **ext))
            else:
                k += 1
    # resumen compacto de turnos para no generar JSON enormes
    agg = {}
    for t in turns:
        key = (t['rama'], t['stop'], t['acerca'], t['pocket'], t['vis'], t['carry'] >= 3, t['en_puerta'])
        agg[key] = agg.get(key, 0) + 1
    return {'turns': [list(k) + [v] for k, v in agg.items()], 'episodes': eps}


# ----------------------------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------------------------

def play(job):
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
    res.update({'rival': rival_name, 'lay': lay, 'we_red': we_red,
                'score': res['score'] if we_red else -res['score']})
    return res


def resumen(paths, por_rival=False):
    for path in paths:
        data = json.load(open(path))
        groups = {'TOTAL': data['partidas']}
        if por_rival:
            for g in data['partidas']:
                groups.setdefault(g['rival'], []).append(g)
        for name, games in groups.items():
            print(f"\n=== {path} [{name}]  params={data['params']}  partidas={len(games)}")
            T = [t for g in games for t in g['turns']]   # [rama, stop, acerca, pocket, vis, carry>=3, en_puerta, n]
            n = sum(t[-1] for t in T) or 1
            f = lambda cond: sum(t[-1] for t in T if cond(t))
            print(f"Turnos de defensor con invasor presente: {n} ({n / len(games):.1f}/partida)")
            print(f"  quieto (STOP) {100.0 * f(lambda t: t[1]) / n:5.1f} %   se acerca {100.0 * f(lambda t: t[2]) / n:5.1f} %"
                  f"   invasor visible {100.0 * f(lambda t: t[4]) / n:5.1f} %")
            print('  rama                   % turnos   % quieto en la rama   % se acerca')
            for r in ('intercepta_ruta', 'puerta_fallback', 'persigue_u_otra', 'asustado'):
                nr = f(lambda t: t[0] == r)
                if nr:
                    print(f"  {r:22s} {100.0 * nr / n:7.1f}   {100.0 * f(lambda t: t[0] == r and t[1]) / nr:16.1f}"
                          f"   {100.0 * f(lambda t: t[0] == r and t[2]) / nr:10.1f}")
            npk = f(lambda t: t[3])
            if npk:
                print(f"  invasor en callejón: {100.0 * npk / n:.1f} % de los turnos; quietos en ellos "
                      f"{100.0 * f(lambda t: t[3] and t[1]) / npk:.1f} %")
            nq = f(lambda t: t[1]) or 1
            print(f"  de los turnos quietos: en una puerta {100.0 * f(lambda t: t[1] and t[6]) / nq:.1f} %, "
                  f"invasor con carga>=3 {100.0 * f(lambda t: t[1] and t[5]) / nq:.1f} %, "
                  f"invasor visible {100.0 * f(lambda t: t[1] and t[4]) / nq:.1f} %")
            E = [e for g in games for e in g['episodes']]
            if not E:
                continue
            print(f"Invasiones: {len(E)} ({len(E) / len(games):.1f}/partida)")
            print('  final            %    dur.media  carga máx.  dep.medio  dist.fantasma a su salida')
            for fin in ('deposita', 'comido', 'vuelve_vacio', 'fin_partida'):
                ee = [e for e in E if e['fin'] == fin]
                if not ee:
                    continue
                dd = [e['d_exit'] for e in ee if e['d_exit'] is not None]
                print(f"  {fin:14s} {100.0 * len(ee) / len(E):5.1f}  {sum(e['dur'] for e in ee) / len(ee):9.1f}"
                      f"  {sum(e['maxc'] for e in ee) / len(ee):10.1f}  {sum(e['dep'] for e in ee) / len(ee):9.1f}"
                      f"  {(sum(dd) / len(dd)) if dd else float('nan'):10.1f}")
            dep = [e for e in E if e['fin'] == 'deposita']
            if dep:
                tot = sum(e['dep'] for e in dep) or 1
                big = sum(e['dep'] for e in dep if e['dep'] >= 5)
                print(f"  comida depositada por partida {tot / len(games):.1f}; de ella en invasiones con >=5: "
                      f"{100.0 * big / tot:.0f} %; con algún fantasma nuestro asustado: "
                      f"{100.0 * sum(e['dep'] for e in dep if e['scared']) / tot:.0f} %")
                close = [e for e in dep if e['d_exit'] is not None and e['d_exit'] <= 2]
                if close and 'scared_exit' in close[0]:
                    print(f"  depósitos con fantasma nuestro a <=2 de su salida ({len(close)}): ese fantasma asustado "
                          f"{100.0 * sum(e['scared_exit'] for e in close) / len(close):.0f} %, quieto en OTRA puerta "
                          f"{100.0 * sum(e['other_gate'] for e in close) / len(close):.0f} %")
                    nc = [e for e in dep if e.get('d_exit_calm') is not None]
                    print(f"  fantasma NO asustado más cercano a su salida: <=1 en "
                          f"{100.0 * sum(e['d_exit_calm'] <= 1 for e in nc) / max(1, len(nc)):.0f} %, <=3 en "
                          f"{100.0 * sum(e['d_exit_calm'] <= 3 for e in nc) / max(1, len(nc)):.0f} %, ninguno no asustado en "
                          f"{100.0 * (len(dep) - len(nc)) / len(dep):.0f} % de los depósitos")
                    print(f"  depósitos en invasiones en las que se comió nuestra cápsula: "
                          f"{100.0 * sum(e['dep'] for e in dep if e.get('cap_eaten')) / tot:.0f} % de la comida")
                print(f"  al depositar, nuestro fantasma más cercano a su casilla de salida: <=2 en "
                      f"{100.0 * sum(1 for e in dep if e['d_exit'] is not None and e['d_exit'] <= 2) / len(dep):.0f} %, "
                      f">=6 en {100.0 * sum(1 for e in dep if e['d_exit'] is None or e['d_exit'] >= 6) / len(dep):.0f} %")


def main():
    if '--una' in sys.argv:
        return run_single(sys.argv[sys.argv.index('--') + 1:], sys.argv[sys.argv.index('--nuestro') + 1])
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
    ap.add_argument('--por-rival', action='store_true')
    ap.add_argument('--verificar')
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 2)
    a = ap.parse_args()
    if a.resumen:
        return resumen(a.resumen, a.por_rival)
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
        json.dump(data, open(a.salida, 'w'))
    if a.verificar:
        ref = json.load(open(a.verificar))
        refs = {(r['lay'], r['we_red'], k): r['score'] for k, v in ref['filas'].items() for r in v}
        same = sum(1 for g in games if refs.get((g['lay'], g['we_red'], g['rival'])) == g['score'])
        known = sum(1 for g in games if (g['lay'], g['we_red'], g['rival']) in refs)
        print(f"Verificación contra {a.verificar}: marcador idéntico en {same} de {known}")
    print(f"Partidas: {len(games)}  errores: {data['errores']}")
    if a.salida:
        resumen([a.salida], a.por_rival)


if __name__ == '__main__':
    main()
