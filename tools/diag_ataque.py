"""Diagnóstico del ATAQUE: ¿por qué depositamos poco y por qué nos comen?

SOLO MIDE (igual que diag_capsulas.py y diag_defensa.py): envuelve choose_action de SmartAgent para
registrar el rol de cada turno, sin cambiar su resultado ni usar random; el análisis se hace al final.
--verificar compara marcadores con un JSON de defensa_bench de las mismas partidas.

Por cada INCURSIÓN de un agente nuestro (pasa de fantasma a pacman y vuelve):
  quién (atacante o defensor), cómo acaba (deposita / muere / vuelve vacío / fin de partida), duración,
  carga máxima y, si muere: carga perdida, si estaba en un callejón, a qué distancia de casa, cuántos
  fantasmas rivales tenía a <= 3, y cuántos turnos antes era ya visible el fantasma que lo mata.
Por partida: reparto del tiempo del atacante (en campo rival, en casa lejos de la frontera, pegado a la
frontera sin cruzar), rachas de atasco en la frontera, comida depositada por cada agente, cápsulas rivales
comidas y comida depositada mientras sus fantasmas estaban asustados, y cómo acaba la partida.

Uso (desde la raíz del repo, venv activado):
    python tools/diag_ataque.py --rivales tian__greedy_v4 --mapas 40 --salida a.json --verificar m.json
    python tools/diag_ataque.py --resumen a.json [--por-rival]
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


def run_single(argv, our_file):
    sys.path.insert(0, os.getcwd())
    import contest.capture as capture
    our_file = os.path.abspath(our_file)
    S = {'agents': [], 'hist': {}, 'roles': {}}

    orig_load = capture.load_agents

    def load_agents(is_red, agent_file, cmd_line_args):
        agents = orig_load(is_red, agent_file, cmd_line_args)
        f = agent_file if agent_file.endswith('.py') else agent_file + '.py'
        if os.path.abspath(f) == our_file and agents and agents[0] is not None:
            S['agents'] = list(agents)
            cls = type(agents[0])
            if not getattr(cls, '_diagat_patched', False):
                cls._diagat_patched = True
                o_choose = cls.choose_action

                def choose_action(self, gs):
                    act = o_choose(self, gs)
                    S['roles'][(gs.data.timeleft, self.index)] = self.brain.roles.get(self.index)
                    return act
                cls.choose_action = choose_action
        return agents

    capture.load_agents = load_agents
    orig_process = capture.CaptureRules.process

    def process(state, game):
        S['hist'][state.data.timeleft] = [(a.get_position(), a.is_pacman, a.scared_timer, a.num_carrying,
                                           a.num_returned) for a in state.data.agent_states]
        return orig_process(state, game)

    capture.CaptureRules.process = staticmethod(process)
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        games = capture.run_games(**capture.read_command(argv))
    g = games[0]
    out = {'score': g.state.data.score, 'timeleft_end': g.state.data.timeleft}
    out.update(analyze(S))
    print('RESULT ' + json.dumps(out))


def analyze(S):
    if not S['agents']:
        return {'raids': [], 'game': {}}
    ag = S['agents'][0]
    D = ag.get_maze_distance
    ours = [a.index for a in S['agents']]
    pref = {a.index: a.preferred for a in S['agents']}
    H = S['hist']
    tls = sorted(H, reverse=True)
    n_ag = len(H[tls[0]])
    rivals = [i for i in range(n_ag) if i not in ours]
    home = ag.home_cells
    enemy_pockets = {c for c in ag.pockets if c in ag.enemy_side}
    man = lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1])

    raids = []
    for i in ours:
        k = 1
        while k < len(tls):
            if H[tls[k]][i][1] and not H[tls[k - 1]][i][1]:
                s_k = k
                while k < len(tls) and H[tls[k]][i][1]:
                    k += 1
                last = H[tls[k - 1]]
                r = {'who': pref[i], 'dur': (k - s_k + 3) // 4,
                     'maxc': max(H[tls[j]][i][3] for j in range(s_k, k)),
                     'roles': {}}
                for j in range(s_k, k):
                    ro = S['roles'].get((tls[j], i))
                    if ro:
                        r['roles'][ro] = r['roles'].get(ro, 0) + 1
                if k >= len(tls):
                    r['fin'] = 'fin_partida'
                else:
                    now = H[tls[k]]
                    dep = now[i][4] - last[i][4]
                    r['dep'] = dep
                    if dep > 0:
                        r['fin'] = 'deposita'
                    elif D(now[i][0], last[i][0]) > 1:
                        r['fin'] = 'muere'
                        p = last[i][0]
                        r['carry'] = last[i][3]
                        r['pocket'] = p in enemy_pockets
                        r['d_home'] = min(D(p, h) for h in home)
                        ghosts = [e for e in rivals if not last[e][1] and last[e][2] == 0]
                        r['ghosts3'] = sum(1 for e in ghosts if D(last[e][0], p) <= 3)
                        # ¿Cuántos movimientos antes de morir había un fantasma rival visible (<= 5)?
                        seen = 0
                        for j in range(k - 1, max(s_k - 1, k - 81), -1):
                            st = H[tls[j]]
                            if any(not st[e][1] and st[e][2] <= 2 and man(st[e][0], st[i][0]) <= 5 for e in rivals):
                                seen += 1
                            else:
                                break
                        r['seen_moves'] = seen
                    else:
                        r['fin'] = 'vuelve_vacio'
                raids.append(r)
            else:
                k += 1

    # Reparto del tiempo del atacante (preferred == 'attack') en sus propios turnos.
    att = [a.index for a in S['agents'] if a.preferred == 'attack'][0]
    t_enemy = t_border = t_home = 0
    streak, streaks = 0, []
    for tl in tls:
        if (tl, att) not in S['roles']:
            continue
        st = H.get(tl)
        if st is None:
            continue
        p, pac = st[att][0], st[att][1]
        if pac:
            t_enemy += 1
            if streak:
                streaks.append(streak)
            streak = 0
        elif S['roles'][(tl, att)] == 'attack' and min(D(p, h) for h in home) <= 2:
            t_border += 1
            streak += 1
        else:
            t_home += 1
            if streak:
                streaks.append(streak)
            streak = 0
    if streak:
        streaks.append(streak)
    last = H[tls[-1]]
    rival_scared_dep = 0
    for k in range(1, len(tls)):
        a, b = H[tls[k - 1]], H[tls[k]]
        if any(b[e][2] > 0 for e in rivals):
            rival_scared_dep += sum(b[i][4] - a[i][4] for i in ours)
    game = {'att_enemy': t_enemy, 'att_border': t_border, 'att_home': t_home,
            'att_max_border_streak': max(streaks) if streaks else 0,
            'dep_att': last[att][4], 'dep_def': sum(last[i][4] for i in ours if i != att),
            'dep_rival_scared': rival_scared_dep,
            'rival_scared_moves': sum(1 for tl in tls if any(H[tl][e][2] > 0 for e in rivals))}
    return {'raids': raids, 'game': game}


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
            n = len(games)
            print(f"\n=== {path} [{name}]  params={data['params']}  partidas={n}")
            w = sum(g['score'] > 0 for g in games)
            t = sum(g['score'] == 0 for g in games)
            losses = [g['score'] for g in games if g['score'] < 0]
            print(f"V-E-D {w}-{t}-{n - w - t}; derrotas por <=3: {sum(1 for s in losses if s >= -3)}, "
                  f"4-8: {sum(1 for s in losses if -8 <= s < -3)}, >8: {sum(1 for s in losses if s < -8)}; "
                  f"empates {t}; partidas acabadas antes de tiempo (comida): "
                  f"{sum(1 for g in games if g['timeleft_end'] > 0)}")
            G = [g['game'] for g in games if g['game']]
            if G:
                tt = sum(x['att_enemy'] + x['att_border'] + x['att_home'] for x in G) or 1
                print(f"Atacante, % de sus turnos: en campo rival {100.0 * sum(x['att_enemy'] for x in G) / tt:.0f} %, "
                      f"pegado a la frontera sin cruzar {100.0 * sum(x['att_border'] for x in G) / tt:.0f} %, "
                      f"resto en casa {100.0 * sum(x['att_home'] for x in G) / tt:.0f} %")
                ms = sorted(x['att_max_border_streak'] for x in G)
                print(f"  racha máxima pegado a la frontera por partida: mediana {ms[len(ms) // 2]}, "
                      f">=50 turnos en {sum(1 for m in ms if m >= 50)} partidas")
                print(f"Depositamos por partida: atacante {sum(x['dep_att'] for x in G) / len(G):.1f}, "
                      f"defensor {sum(x['dep_def'] for x in G) / len(G):.1f}; con sus fantasmas asustados "
                      f"{sum(x['dep_rival_scared'] for x in G) / len(G):.1f} "
                      f"(movs. con algún fantasma rival asustado: {sum(x['rival_scared_moves'] for x in G) / len(G):.0f})")
            R = [r for g in games for r in g['raids']]
            if not R:
                continue
            for who in ('attack', 'defend'):
                RR = [r for r in R if r['who'] == who]
                if not RR:
                    continue
                print(f"Incursiones del {'atacante' if who == 'attack' else 'defensor'}: {len(RR) / n:.1f}/partida")
                print('  final           %    dur.media  carga máx.  dep.medio')
                for fin in ('deposita', 'muere', 'vuelve_vacio', 'fin_partida'):
                    ee = [r for r in RR if r['fin'] == fin]
                    if ee:
                        print(f"  {fin:13s} {100.0 * len(ee) / len(RR):5.1f}  {sum(r['dur'] for r in ee) / len(ee):9.1f}"
                              f"  {sum(r['maxc'] for r in ee) / len(ee):10.1f}  "
                              f"{sum(r.get('dep', 0) for r in ee) / len(ee):9.1f}")
                dd = [r for r in RR if r['fin'] == 'muere']
                if dd:
                    print(f"  muertes: {len(dd) / n:.2f}/partida, carga perdida {sum(r['carry'] for r in dd) / n:.1f}/partida "
                          f"(media {sum(r['carry'] for r in dd) / len(dd):.1f}); en callejón "
                          f"{100.0 * sum(r['pocket'] for r in dd) / len(dd):.0f} %; con 2 fantasmas a <=3 "
                          f"{100.0 * sum(r['ghosts3'] >= 2 for r in dd) / len(dd):.0f} %; "
                          f"dist. media a casa {sum(r['d_home'] for r in dd) / len(dd):.1f}")
                    sm = sorted(r['seen_moves'] for r in dd)
                    print(f"  movs. seguidos con fantasma visible antes de morir: mediana {sm[len(sm) // 2]}, "
                          f"0 (sin verlo venir) en {100.0 * sum(1 for s in sm if s == 0) / len(sm):.0f} %, "
                          f">=12 (3 turnos propios o más) en {100.0 * sum(1 for s in sm if s >= 12) / len(sm):.0f} %")


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
