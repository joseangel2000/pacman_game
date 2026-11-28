"""Diagnóstico del FINAL DE PARTIDA: ¿se nos escapan los puntos en los últimos turnos?

SOLO MIDE (igual que diag_ataque.py / diag_defensa.py): engancha CaptureRules.process para
registrar el estado real de cada jugada, sin cambiar nada ni usar random. El análisis se hace
al terminar la partida.

Motivo: en el torneo, 81 de nuestras 92 partidas llegaron al límite de movimientos y 11 se
decidieron por 3 puntos o menos. Lo que pasa en los últimos turnos vale mucho.

Por partida registra:
  - comida DESPERDICIADA: la que nuestros agentes llevaban encima al acabar (nunca depositada),
    y la misma cifra del rival, para comparar.
  - el marcador en varios cortes (a 60, 40, 20 y 10 turnos del final) y al acabar.
  - lo que deposita cada equipo en los últimos turnos (ventana = --ventana, por defecto 40,
    que es el valor de endgame_defend).
  - cómo acaba quien iba por delante / por detrás / empatado al entrar en la ventana.

Uso (desde la raíz del repo, venv activado):
    python tools/diag_final.py --rivales tian__greedy_v4 --mapas 40 --salida f.json \
        --verificar mediciones/v43_greedy.json
    python tools/diag_final.py --resumen f.json [--por-rival]
"""
import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST = os.path.join(REPO, 'pacman-contest', 'src', 'contest')
sys.path.insert(0, os.path.join(REPO, 'tools'))

CORTES = (60, 40, 20, 10)


def run_single(argv, our_file, ventana):
    sys.path.insert(0, os.getcwd())
    import contest.capture as capture
    our_file = os.path.abspath(our_file)
    S = {'agents': [], 'hist': {}}

    orig_load = capture.load_agents

    def load_agents(is_red, agent_file, cmd_line_args):
        agents = orig_load(is_red, agent_file, cmd_line_args)
        f = agent_file if agent_file.endswith('.py') else agent_file + '.py'
        if os.path.abspath(f) == our_file and agents and agents[0] is not None:
            S['agents'] = list(agents)
        return agents

    capture.load_agents = load_agents
    orig_process = capture.CaptureRules.process

    def process(state, game):
        S['hist'][state.data.timeleft] = [(a.is_pacman, a.num_carrying, a.num_returned)
                                          for a in state.data.agent_states]
        return orig_process(state, game)

    capture.CaptureRules.process = staticmethod(process)
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        games = capture.run_games(**capture.read_command(argv))
    g = games[0]
    out = {'score': g.state.data.score, 'timeleft_end': g.state.data.timeleft}
    out.update(analyze(S, g, ventana))
    print('RESULT ' + json.dumps(out))


def analyze(S, g, ventana):
    if not S['agents'] or not S['hist']:
        return {}
    ours = sorted(a.index for a in S['agents'])
    rivals = [i for i in range(4) if i not in ours]
    H = S['hist']
    tls = sorted(H, reverse=True)          # timeleft va bajando

    def dep(tl, idx):
        return sum(H[tl][i][2] for i in idx)

    def marcador(tl):
        return dep(tl, ours) - dep(tl, rivals)

    fin = tls[-1]
    # Comida que se queda sin depositar al acabar: puntos tirados.
    desperdiciada = sum(H[fin][i][1] for i in ours)
    desperdiciada_rival = sum(H[fin][i][1] for i in rivals)

    # Marcador en los cortes (por turnos propios restantes).
    cortes = {}
    for c in CORTES:
        cand = [tl for tl in tls if tl // 4 >= c]
        cortes[str(c)] = marcador(cand[-1]) if cand else None

    # Ventana final: qué deposita cada uno.
    cand = [tl for tl in tls if tl // 4 >= ventana]
    tl_v = cand[-1] if cand else tls[0]
    dep_nos = dep(fin, ours) - dep(tl_v, ours)
    dep_ellos = dep(fin, rivals) - dep(tl_v, rivals)

    m_v, m_fin = marcador(tl_v), marcador(fin)
    if m_v > 0:
        entrada = 'ganando'
    elif m_v < 0:
        entrada = 'perdiendo'
    else:
        entrada = 'empate'
    if m_fin > 0:
        final = 'ganamos'
    elif m_fin < 0:
        final = 'perdemos'
    else:
        final = 'empate'

    return {'desperdiciada': desperdiciada, 'desperdiciada_rival': desperdiciada_rival,
            'cortes': cortes, 'dep_nos_final': dep_nos, 'dep_ellos_final': dep_ellos,
            'marcador_ventana': m_v, 'marcador_final': m_fin,
            'entrada': entrada, 'final': final,
            'turnos_jugados': tls[0] // 4 - fin // 4,
            'acabo_por_tiempo': fin // 4 <= 1}


def play(job):
    team, params, rival_name, rival, lay, we_red, ventana = job
    r, b = (team, rival) if we_red else (rival, team)
    seed = f'def-{rival_name}-{lay}-{we_red}'   # misma semilla que defensa_bench.py
    cmd = [sys.executable, os.path.abspath(__file__), '--una', '--nuestro', team,
           '--ventana', str(ventana), '--',
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
        partidas = [p for p in data['partidas'] if p.get('entrada')]
        if not partidas:
            print(path, '(sin datos)')
            continue
        grupos = {'[TOTAL]': partidas}
        if por_rival:
            for p in partidas:
                grupos.setdefault(p['rival'], []).append(p)
        for nombre, ps in grupos.items():
            n = len(ps)
            print(f"\n=== {path} {nombre}  params={data.get('params', {})}  partidas={n}")
            desp = sum(p['desperdiciada'] for p in ps) / n
            despr = sum(p['desperdiciada_rival'] for p in ps) / n
            tiempo = sum(1 for p in ps if p['acabo_por_tiempo'])
            print(f"  Acaban por límite de movimientos: {100 * tiempo / n:.0f} %")
            print(f"  Comida sin depositar al acabar: nosotros {desp:.2f}/partida, ellos {despr:.2f}")
            dn = sum(p['dep_nos_final'] for p in ps) / n
            de = sum(p['dep_ellos_final'] for p in ps) / n
            print(f"  En la ventana final depositamos {dn:.2f} y ellos {de:.2f}")
            tabla = defaultdict(lambda: defaultdict(int))
            for p in ps:
                tabla[p['entrada']][p['final']] += 1
            print('  Cómo acaba según el marcador al entrar en la ventana:')
            print('    %-10s %7s %7s %7s %7s' % ('entrada', 'n', 'ganamos', 'empate', 'perdemos'))
            for entrada in ('ganando', 'empate', 'perdiendo'):
                f = tabla.get(entrada)
                if not f:
                    continue
                tot = sum(f.values())
                print('    %-10s %7d %7d %7d %7d' % (
                    entrada, tot, f.get('ganamos', 0), f.get('empate', 0), f.get('perdemos', 0)))
            # Remontadas y pinchazos ajustados
            ajust = [p for p in ps if abs(p['marcador_ventana']) <= 3]
            if ajust:
                gan = sum(1 for p in ajust if p['final'] == 'ganamos')
                emp = sum(1 for p in ajust if p['final'] == 'empate')
                print(f"  Partidas ajustadas al entrar (|marcador| <= 3): {len(ajust)}"
                      f" -> ganamos {gan}, empate {emp}, perdemos {len(ajust) - gan - emp}")
            cortes = {}
            for c in CORTES:
                vals = [p['cortes'].get(str(c)) for p in ps]
                vals = [v for v in vals if v is not None]
                if vals:
                    cortes[c] = sum(vals) / len(vals)
            if cortes:
                print('  Marcador medio a falta de: ' + ', '.join(
                    f'{c} turnos {v:+.2f}' for c, v in sorted(cortes.items(), reverse=True))
                    + f", final {sum(p['marcador_final'] for p in ps) / n:+.2f}")


def main():
    if '--una' in sys.argv:
        ventana = int(sys.argv[sys.argv.index('--ventana') + 1])
        return run_single(sys.argv[sys.argv.index('--') + 1:],
                          sys.argv[sys.argv.index('--nuestro') + 1], ventana)
    import defensa_bench as db
    ap = argparse.ArgumentParser()
    ap.add_argument('--team', default=os.path.join(REPO, 'my_team.py'))
    ap.add_argument('--params', default='{}')
    ap.add_argument('--rivales', nargs='*', default=['tian__greedy_v4'])
    ap.add_argument('--mapas', type=int, default=40)
    ap.add_argument('--fijos', type=int, default=10)
    ap.add_argument('--desde', type=int, default=1)
    ap.add_argument('--ventana', type=int, default=40)
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
                jobs.append((team, params, name, path, lay, we_red, a.ventana))
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(play, jobs))
    games = [r for r in res if r is not None]
    data = {'params': params, 'layouts': layouts, 'ventana': a.ventana,
            'errores': len(res) - len(games), 'partidas': games}
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
