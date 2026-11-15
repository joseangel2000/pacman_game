"""Mide la DEFENSA de un equipo (my_team.py) contra una liga fija, con las mismas partidas y semillas.

Además de victorias/empates/derrotas imprime las tres métricas defensivas del playbook,
calculadas sobre el estado REAL de cada jugada (ver tools/run_one.py), no estimadas:
  - comida rival depositada por partida
  - invasores comidos por partida (pacmans rivales comidos por nuestros fantasmas)
  - turnos medios que un invasor rival pasa en nuestro campo por incursión
y también: nuestros pacmans comidos, comida que perdemos al morir, carga media del invasor al ser
comido (carga/com) y tiempo máximo por partida.

Uso (desde la raíz del repo, con el venv activado):
    python tools/defensa_bench.py                         # liga por defecto, my_team.py actual
    python tools/defensa_bench.py --params '{"intercept": 1}'   # PARAMS por encima de los del archivo
    python tools/defensa_bench.py --team ruta/otro_equipo.py --mapas 6 --salida a.json
    python tools/defensa_bench.py --rivales rival_capsula lorecleme__pacman-agent
    python tools/defensa_bench.py --comparar a.json b.json     # compara dos ejecuciones
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEST = os.path.join(REPO, 'pacman-contest', 'src', 'contest')
RUNNER = os.path.join(REPO, 'tools', 'run_one.py')
FIXED = ['defaultCapture', 'alleyCapture', 'bloxCapture', 'crowdedCapture', 'distantCapture',
         'fastCapture', 'jumboCapture', 'mediumCapture', 'officeCapture', 'strategicCapture']
DEFAULT_RIVALS = ['baseline_team', 'rival_espejo', 'rival_muro', 'rival_asalto', 'rival_capsula',
                  'rival_codicioso', 'lorecleme__pacman-agent', 'Supergodgg__LL_Autonomous_Pacman',
                  'sta05__Clingho_pacman', 'foxtrotdelta-hub__flagrats', 'Aiko-vdm__DotGobblers']


def resolve(name):
    if name == 'baseline_team':
        return name
    p = os.path.join(REPO, 'opponents', name + '.py')
    if os.path.exists(p):
        return p
    p = os.path.join(REPO, 'rivales_ext', name, 'my_team.py')
    if os.path.exists(p):
        return p
    return None


def play(job):
    team, params, rival_name, rival, lay, we_red = job
    r, b = (team, rival) if we_red else (rival, team)
    seed = f'def-{rival_name}-{lay}-{we_red}'
    cmd = [sys.executable, RUNNER, '-r', r, '-b', b, '-l', lay, '-Q', '--delay-step', '0', '-c',
           '--setRandomSeed', seed]
    env = dict(os.environ, PACMAN_PARAMS=json.dumps(params))
    try:
        p = subprocess.run(cmd, cwd=CONTEST, capture_output=True, text=True, timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return rival_name, None
    line = [l for l in p.stdout.splitlines() if l.startswith('RESULT ')]
    if not line:
        return rival_name, None
    res = json.loads(line[0][7:])
    us, them = ('red', 'blue') if we_red else ('blue', 'red')
    m = res.get('metrics', {})
    g = lambda k, t: m.get(k, {}).get(t, 0)
    return rival_name, {
        'score': res['score'] if we_red else -res['score'],
        'our_returned': res[us + '_returned'],
        'their_returned': res[them + '_returned'],
        'crashed': res.get('agent_crashed', False),
        'secs': res.get('secs', 0),
        'invaders_eaten': g('pac_deaths', them),     # pacmans rivales comidos por nosotros
        'our_deaths': g('pac_deaths', us),           # nuestros pacmans comidos
        'ghost_eaten': g('ghost_eaten', us),         # nuestros fantasmas comidos (asustados)
        'lost_carry': g('lost_carry', us),
        'their_lost_carry': g('lost_carry', them),   # comida que llevaban los invasores que nos comemos
        'inv_turns': g('pac_turns', them),
        'inv_episodes': g('pac_episodes', them),
        'caps_lost': g('capsules_lost', us),         # cápsulas nuestras que nos comen
        'caps_taken': g('capsules_lost', them),      # cápsulas rivales que comemos
        'our_scared': g('scared_turns', us),         # turnos de nuestros fantasmas asustados
        'lay': lay, 'we_red': we_red,
    }


def summarize(rows):
    """rows: lista de dicts de partidas -> dict de agregados."""
    n = len(rows)
    if not n:
        return {'n': 0}
    w = sum(r['score'] > 0 for r in rows)
    t = sum(r['score'] == 0 for r in rows)
    eps = sum(r['inv_episodes'] for r in rows)
    return {
        'n': n, 'w': w, 't': t, 'l': n - w - t,
        'pts': (3 * w + t) / n,
        'margin': sum(r['score'] for r in rows) / n,
        'their_returned': sum(r['their_returned'] for r in rows) / n,
        'our_returned': sum(r['our_returned'] for r in rows) / n,
        'invaders_eaten': sum(r['invaders_eaten'] for r in rows) / n,
        'our_deaths': sum(r['our_deaths'] for r in rows) / n,
        'lost_carry': sum(r['lost_carry'] for r in rows) / n,
        'inv_len': (sum(r['inv_turns'] for r in rows) / eps) if eps else 0.0,
        # Carga media del invasor al ser comido (None en JSON antiguos sin el campo).
        'carry_eaten': (sum(r['their_lost_carry'] for r in rows) / max(1, sum(r['invaders_eaten'] for r in rows)))
        if all('their_lost_carry' in r for r in rows) else None,
        'inv_eps': eps / n,
        'caps_lost': sum(r['caps_lost'] for r in rows) / n,
        'caps_taken': sum(r['caps_taken'] for r in rows) / n,
        'our_scared': sum(r['our_scared'] for r in rows) / n,
        'crashed': sum(bool(r['crashed']) for r in rows),
    }


HDR = (f"{'':34s} {'N':>4s} {'V-E-D':>9s} {'pts':>5s} {'marg':>6s} {'ellos dep.':>10s} {'inv.comidos':>11s} "
       f"{'muertes':>7s} {'turnos/inv':>10s} {'cáps.perd':>9s} {'asust.':>6s} {'carga/com':>9s}")


def fmt(name, s):
    if not s.get('n'):
        return f'{name:34s} (sin partidas)'
    return (f"{name:34s} {s['n']:4d} {s['w']:3d}-{s['t']:2d}-{s['l']:2d} {s['pts']:5.2f} {s['margin']:+6.1f} "
            f"{s['their_returned']:10.1f} {s['invaders_eaten']:11.2f} {s['our_deaths']:7.2f} {s['inv_len']:10.1f} "
            f"{s['caps_lost']:9.2f} {s['our_scared']:6.1f} "
            f"{'n/d' if s.get('carry_eaten') is None else format(s['carry_eaten'], '.1f'):>9s}")


def compare(a_path, b_path):
    a, b = json.load(open(a_path)), json.load(open(b_path))
    print(f"A = {a_path}   B = {b_path}\n")
    print(f"{'':34s} {'pts A':>6s} {'pts B':>6s} {'marg A':>7s} {'marg B':>7s} {'ellos A':>8s} {'ellos B':>8s} "
          f"{'inv A':>6s} {'inv B':>6s} {'T/inv A':>8s} {'T/inv B':>8s}")
    for k in list(a['por_rival']) + ['TOTAL']:
        sa = a['total'] if k == 'TOTAL' else a['por_rival'][k]
        sb = b['total'] if k == 'TOTAL' else b['por_rival'].get(k)
        if not sb or not sa.get('n') or not sb.get('n'):
            continue
        print(f"{k:34s} {sa['pts']:6.2f} {sb['pts']:6.2f} {sa['margin']:+7.1f} {sb['margin']:+7.1f} "
              f"{sa['their_returned']:8.1f} {sb['their_returned']:8.1f} {sa['invaders_eaten']:6.2f} "
              f"{sb['invaders_eaten']:6.2f} {sa['inv_len']:8.1f} {sb['inv_len']:8.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--team', default=os.path.join(REPO, 'my_team.py'))
    ap.add_argument('--params', default='{}', help='JSON con PARAMS que sobreescriben los del archivo')
    ap.add_argument('--rivales', nargs='*', default=DEFAULT_RIVALS)
    ap.add_argument('--mapas', type=int, default=4, help='cuántos mapas RANDOM (además de los 10 fijos)')
    ap.add_argument('--fijos', type=int, default=10, help='cuántos de los 10 mapas fijos usar')
    ap.add_argument('--desde', type=int, default=1, help='primer RANDOM a usar (p.ej. 101 para mapas de validación)')
    ap.add_argument('--salida', help='guarda el resultado en este JSON')
    ap.add_argument('--comparar', nargs=2, metavar=('A', 'B'))
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()
    if args.comparar:
        return compare(*args.comparar)

    team = os.path.abspath(args.team)
    params = json.loads(args.params)
    layouts = FIXED[:args.fijos] + [f'RANDOM{s}' for s in range(args.desde, args.desde + args.mapas)]
    jobs, skipped = [], []
    for name in args.rivales:
        path = resolve(name)
        if path is None:
            skipped.append(name)
            continue
        for lay in layouts:
            for we_red in (True, False):
                jobs.append((team, params, name, path, lay, we_red))
    if skipped:
        print('Rivales no encontrados (se omiten):', ', '.join(skipped))
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(play, jobs))

    by = {}
    errs = 0
    for name, row in results:
        if row is None:
            errs += 1
            continue
        by.setdefault(name, []).append(row)
    out = {'team': team, 'params': params, 'layouts': layouts, 'errores': errs,
           'por_rival': {k: summarize(v) for k, v in by.items()},
           'filas': by,
           'total': summarize([r for v in by.values() for r in v]),
           'max_secs_partida': max((r['secs'] for v in by.values() for r in v), default=0)}
    print(HDR)
    for k, s in out['por_rival'].items():
        print(fmt(k, s))
    print('-' * len(HDR))
    print(fmt('TOTAL', out['total']))
    print(f"\nErrores/timeouts: {errs}   Crashes: {out['total'].get('crashed', 0)}   "
          f"Partida más larga: {out['max_secs_partida']} s")
    if args.salida:
        json.dump(out, open(args.salida, 'w'), indent=1)


if __name__ == '__main__':
    main()
