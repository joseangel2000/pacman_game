"""Juega nuestro equipo contra un rival en varios mapas, como rojo y como azul.

Uso (desde la raíz del repo, con el venv activado):
    python tools/bench.py                       # my_team.py vs baseline_team, 10 mapas RANDOM
    python tools/bench.py my_team.py baseline_team 20
"""
import sys, json, subprocess, os
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST = os.path.join(REPO, 'pacman-contest', 'src', 'contest')
RUNNER = os.path.join(REPO, 'tools', 'run_one.py')
PY = sys.executable

ours = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(REPO, 'my_team.py')
opp = sys.argv[2] if len(sys.argv) > 2 else 'baseline_team'
if opp.endswith('.py'):
    opp = os.path.abspath(opp)
n_rand = int(sys.argv[3]) if len(sys.argv) > 3 else 10
fixed = ['defaultCapture', 'alleyCapture', 'bloxCapture', 'crowdedCapture', 'distantCapture',
         'fastCapture', 'jumboCapture', 'mediumCapture', 'officeCapture', 'strategicCapture']
layouts = fixed + [f'RANDOM{s}' for s in range(1, n_rand + 1)]


def play(job):
    lay, we_red = job
    r, b = (ours, opp) if we_red else (opp, ours)
    cmd = [PY, RUNNER, '-r', r, '-b', b, '-l', lay, '-Q', '--delay-step', '0', '-c']
    p = subprocess.run(cmd, cwd=CONTEST, capture_output=True, text=True, timeout=900)
    line = [l for l in p.stdout.splitlines() if l.startswith('RESULT ')]
    if not line:
        return lay, we_red, None, p.stderr[-800:]
    res = json.loads(line[0][7:])
    s = res['score'] if we_red else -res['score']
    res['our_returned'] = res['red_returned'] if we_red else res['blue_returned']
    res['their_returned'] = res['blue_returned'] if we_red else res['red_returned']
    us, them = ('red', 'blue') if we_red else ('blue', 'red')
    m = res.get('metrics', {})
    res['kills'] = m.get('pac_deaths', {}).get(them, 0)        # invasores comidos por nosotros
    res['our_deaths'] = m.get('pac_deaths', {}).get(us, 0)     # nuestros pacmans comidos
    res['inv_turns'] = m.get('pac_turns', {}).get(them, 0)
    res['inv_eps'] = m.get('pac_episodes', {}).get(them, 0)
    return lay, we_red, s, res


jobs = [(l, c) for l in layouts for c in (True, False)]
with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
    results = list(ex.map(play, jobs))

w = t = l = err = 0
tot = ourret = theirret = 0
kills = deaths = inv_turns = inv_eps = 0
for lay, we_red, s, res in results:
    if s is None:
        err += 1
        print('ERROR', lay, 'rojo' if we_red else 'azul', res)
        continue
    w += s > 0; t += s == 0; l += s < 0; tot += s
    ourret += res['our_returned']; theirret += res['their_returned']
    kills += res['kills']; deaths += res['our_deaths']; inv_turns += res['inv_turns']; inv_eps += res['inv_eps']
    print(f"{lay:18s} {'rojo' if we_red else 'azul'}  score={s:+4d}  nosotros={res['our_returned']:3d}  ellos={res['their_returned']:3d}")
n = w + t + l
print(f"\nPartidas: {n}  Victorias: {w}  Empates: {t}  Derrotas: {l}  Errores: {err}")
if n:
    print(f"Score medio: {tot / n:+.2f}  Comida depositada media: nosotros {ourret / n:.1f} / ellos {theirret / n:.1f}")
    print(f"Defensa: invasores comidos {kills / n:.2f}/partida, nuestros pacmans comidos {deaths / n:.2f}/partida, "
          f"turnos medios de un invasor en nuestro campo {inv_turns / inv_eps if inv_eps else 0:.1f}")
