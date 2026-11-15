"""Aprendizaje offline de los PARAMS de my_team.py jugando contra los rivales.

Idea: búsqueda por coordenadas ("coordinate descent"). Para cada parámetro
probamos varios valores dejando los demás fijos, jugamos una liga completa
con cada valor y nos quedamos con el que más puntos de torneo consigue
(victoria = 3, empate = 1, derrota = 0, como en el torneo de la UPF).
Repetimos varias pasadas hasta que nada mejora.

Para que la comparación sea justa, cada candidato juega EXACTAMENTE las
mismas partidas (mismos mapas, colores y semilla aleatoria). Al final se
valida el ganador en mapas NUEVOS que no se han usado para aprender, y solo
se escribe en my_team.py si también gana ahí.

Uso (desde la raíz del repo, con el venv activado):
    python tools/aprender.py                 # aprendizaje completo
    python tools/aprender.py --rapido        # menos partidas, para probar
    python tools/aprender.py --no-escribir   # no modifica my_team.py
    python tools/aprender.py --externos lorecleme__pacman-agent Aiko-vdm__DotGobblers
                                             # añade equipos de rivales_ext/ a la liga
"""
import argparse
import ast
import glob
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST = os.path.join(REPO, 'pacman-contest', 'src', 'contest')
RUNNER = os.path.join(REPO, 'tools', 'run_one.py')
TEAM = os.path.join(REPO, 'my_team.py')
LOG = os.path.join(REPO, 'tools', 'aprendizaje_log.json')

# Valores que se prueban para cada parámetro.
SPACE = {
    'return_threshold': [3, 4, 6, 8, 10],
    'raid_threshold': [1, 2, 3, 5],
    'passive_turns': [10, 20, 30, 60, 999],
    'scared_switch': [3, 6, 10, 20, 999],
    'danger_radius': [1, 2],
    'ghost_alert': [3, 4, 5, 7],
    'avoid_pockets': [0, 1],
    'double_defense': [0, 1],
    'double_defense_carry': [0, 3, 6, 10],
    'double_defense_dist': [4, 8, 99],
    'help_carry': [5, 8, 12, 20, 99],
    'scared_raid_max_carry': [3, 6, 10, 99],
    'stuck_turns': [15, 25, 40, 999],
    'stuck_defend': [0, 30, 60],
    'raid_max_aggr': [0.1, 0.2, 0.35, 1.0],
    'pocket_min_carry': [0, 1, 3],
    'cut_exit': [0, 1],
    'endgame_defend': [0, 20, 40, 80],
    # Defensa v4
    'intercept': [0, 1],
    'intercept_min_carry': [1, 3, 5],
    'pocket_trap': [0, 1],
    'leash_mode': [0, 1, 2],
    'leash_margin': [2, 4, 6],
    'leash_aggr': [0.0, 0.1, 0.3],
}

# Parámetros que solo importan si otro está activado (si no, no se prueban).
DEPENDS = {'double_defense_carry': ('double_defense', 1), 'double_defense_dist': ('double_defense', 1),
           'intercept_min_carry': ('intercept', 1), 'pocket_trap': ('intercept', 1),
           'leash_margin': ('leash_mode', 1)}
# Parámetros que solo importan si otro NO está en un valor concreto.
DEPENDS_NOT = {'stuck_defend': ('stuck_turns', 999), 'leash_aggr': ('leash_mode', 0)}

FIXED = ['defaultCapture', 'alleyCapture', 'bloxCapture', 'crowdedCapture', 'distantCapture',
         'fastCapture', 'jumboCapture', 'mediumCapture', 'officeCapture', 'strategicCapture']


def read_params():
    src = open(TEAM).read()
    m = re.search(r'# --- PARAMS START ---\nPARAMS = (\{.*?\})\n# --- PARAMS END ---', src, re.S)
    if not m:
        sys.exit('No encuentro el bloque PARAMS en my_team.py')
    return ast.literal_eval(m.group(1))


def write_params(params):
    src = open(TEAM).read()
    old = re.search(r'# --- PARAMS START ---\nPARAMS = \{.*?\}\n# --- PARAMS END ---', src, re.S).group(0)
    # Conservamos los comentarios de cada línea.
    new_lines = []
    for line in old.splitlines():
        m = re.match(r"(\s*)'(\w+)': ([^,]+),(.*)", line)
        if m and m.group(2) in params:
            val = repr(params[m.group(2)])
            line = f"{m.group(1)}'{m.group(2)}': {val},{m.group(4)}"
        new_lines.append(line)
    open(TEAM, 'w').write(src.replace(old, '\n'.join(new_lines)))


def make_games(rivals, layouts, tag):
    games = []
    for rival in rivals:
        for lay in layouts:
            for we_red in (True, False):
                games.append((rival, lay, we_red, f'{tag}-{os.path.basename(rival)}-{lay}-{we_red}'))
    return games


def play(game, params):
    rival, lay, we_red, seed = game
    r, b = (TEAM, rival) if we_red else (rival, TEAM)
    cmd = [sys.executable, RUNNER, '-r', r, '-b', b, '-l', lay, '-Q', '--delay-step', '0', '-c',
           '--setRandomSeed', seed]
    env = dict(os.environ, PACMAN_PARAMS=json.dumps(params))
    try:
        p = subprocess.run(cmd, cwd=CONTEST, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return None
    line = [l for l in p.stdout.splitlines() if l.startswith('RESULT ')]
    if not line:
        return None
    s = json.loads(line[0][7:])['score']
    return s if we_red else -s


def evaluate(params, games, workers):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        scores = list(ex.map(lambda g: play(g, params), games))
    errors = sum(s is None for s in scores)
    scores = [s if s is not None else -999 for s in scores]  # un error cuenta como derrota grave
    points = sum(3 if s > 0 else 1 if s == 0 else 0 for s in scores) / len(scores)
    mean_score = sum(max(s, -30) for s in scores) / len(scores)
    return {'points': points, 'score': mean_score, 'errors': errors}


def better(a, b, margin):
    """¿a es claramente mejor que b? Puntos primero, score como desempate."""
    if a['errors'] > b['errors']:
        return False
    if a['points'] > b['points'] + margin:
        return True
    return abs(a['points'] - b['points']) <= margin and a['score'] > b['score'] + 1.0 and a['points'] >= b['points']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rapido', action='store_true', help='menos mapas (para probar el script)')
    ap.add_argument('--pasadas', type=int, default=2)
    ap.add_argument('--no-escribir', action='store_true')
    ap.add_argument('--externos', nargs='*', default=None,
                    help='añade equipos de rivales_ext/ (nombres de carpeta, o nada para todos)')
    ap.add_argument('--solo', nargs='*', help='aprender solo estos parámetros')
    ap.add_argument('--random', type=int, default=10, help='nº de mapas RANDOM de entrenamiento')
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()

    rivals = ['baseline_team'] + sorted(glob.glob(os.path.join(REPO, 'opponents', 'rival_*.py')))
    if args.externos is not None:
        ext = sorted(glob.glob(os.path.join(REPO, 'rivales_ext', '*', 'my_team.py')))
        if args.externos:
            ext = [e for e in ext if os.path.basename(os.path.dirname(e)) in args.externos]
        rivals += ext
    if args.rapido:
        train_layouts = FIXED[:3] + ['RANDOM1', 'RANDOM2']
        valid_layouts = ['RANDOM101', 'RANDOM102', 'RANDOM103']
    else:
        train_layouts = FIXED + [f'RANDOM{i}' for i in range(1, args.random + 1)]
        valid_layouts = [f'RANDOM{i}' for i in range(101, 116)]
    train = make_games(rivals, train_layouts, 'train')
    valid = make_games(rivals, valid_layouts, 'valid')
    # Margen de mejora mínimo: evita quedarse con cambios que son puro ruido.
    margin = 0.05

    print(f'Rivales: {[os.path.basename(os.path.dirname(r)) if r.endswith("my_team.py") else os.path.basename(r) for r in rivals]}')
    print(f'Partidas por evaluación: {len(train)}  (validación: {len(valid)})\n', flush=True)

    start_params = read_params()
    best = dict(start_params)
    t0 = time.time()
    best_eval = evaluate(best, train, args.workers)
    print(f'Inicial: puntos/partida={best_eval["points"]:.3f}  score={best_eval["score"]:+.2f}  '
          f'({time.time() - t0:.0f}s por evaluación)', flush=True)
    history = [{'params': dict(best), 'train': best_eval}]

    for pasada in range(1, args.pasadas + 1):
        changed = False
        print(f'\n=== Pasada {pasada} ===', flush=True)
        for name, values in SPACE.items():
            if name not in best or (args.solo and name not in args.solo):
                continue
            if name in DEPENDS and best.get(DEPENDS[name][0]) != DEPENDS[name][1]:
                continue
            if name in DEPENDS_NOT and best.get(DEPENDS_NOT[name][0]) == DEPENDS_NOT[name][1]:
                continue
            current = best[name]
            for v in values:
                if v == current or v == best[name]:
                    continue
                cand = dict(best, **{name: v})
                ev = evaluate(cand, train, args.workers)
                mark = ''
                if better(ev, best_eval, margin):
                    best, best_eval, changed, mark = cand, ev, True, '  <-- MEJORA'
                print(f'  {name:22s} = {str(v):5s}  puntos={ev["points"]:.3f}  score={ev["score"]:+.2f}{mark}',
                      flush=True)
                history.append({'params': cand, 'train': ev})
        if not changed:
            break

    print('\n=== Validación en mapas nuevos ===', flush=True)
    v_start = evaluate(start_params, valid, args.workers)
    v_best = evaluate(best, valid, args.workers)
    print(f'  Parámetros iniciales:  puntos={v_start["points"]:.3f}  score={v_start["score"]:+.2f}')
    print(f'  Parámetros aprendidos: puntos={v_best["points"]:.3f}  score={v_best["score"]:+.2f}')

    json.dump({'inicial': start_params, 'aprendido': best, 'train_inicial': history[0]['train'],
               'train_aprendido': best_eval, 'valid_inicial': v_start, 'valid_aprendido': v_best,
               'historial': history}, open(LOG, 'w'), indent=2)

    changes = {k: (start_params[k], best[k]) for k in best if best[k] != start_params.get(k)}
    print('\nCambios:', changes or 'ninguno')
    if changes and v_best['points'] >= v_start['points'] and not args.no_escribir:
        write_params(best)
        print('Parámetros aprendidos escritos en my_team.py')
    elif changes:
        print('NO se escriben: no mejoran en validación (o --no-escribir).')


if __name__ == '__main__':
    main()
