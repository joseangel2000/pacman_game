"""Juega my_team.py contra el baseline y contra todos los rivales de opponents/.

Uso (desde la raíz del repo, con el venv activado):
    python tools/liga.py          # 10 mapas RANDOM + 10 fijos, como rojo y azul
    python tools/liga.py 5        # menos mapas RANDOM, más rápido
"""
import os, sys, subprocess, glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n_rand = sys.argv[1] if len(sys.argv) > 1 else '10'
rivals = ['baseline_team'] + sorted(glob.glob(os.path.join(REPO, 'opponents', 'rival_*.py')))
# Equipos de la edición anterior descargados con tools/descargar_rivales.py
rivals += sorted(glob.glob(os.path.join(REPO, 'rivales_ext', '*', 'my_team.py')))

summary = []
for rival in rivals:
    name = os.path.basename(rival).replace('.py', '')
    if name == 'my_team':
        name = os.path.basename(os.path.dirname(rival))
    print(f'Jugando contra {name}...', flush=True)
    p = subprocess.run([sys.executable, os.path.join(REPO, 'tools', 'bench.py'),
                        os.path.join(REPO, 'my_team.py'), rival, n_rand],
                       capture_output=True, text=True)
    lines = [l for l in p.stdout.splitlines() if l.startswith(('Partidas', 'Score medio', 'Defensa', 'ERROR'))]
    summary.append((name, lines))

print('\n================ RESUMEN ================')
for name, lines in summary:
    print(f'\n{name}')
    for l in lines:
        print('   ' + l)
