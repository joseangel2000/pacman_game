"""Descarga los equipos de la edición anterior (lista compartida por el profesor)
en rivales_ext/<usuario>__<repo>/ para poder jugar contra ellos.

Uso (desde la raíz del repo):
    python tools/descargar_rivales.py

La carpeta rivales_ext/ está en .gitignore: es código de otros equipos y NO
debe subirse a vuestro repositorio.
"""
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(REPO, 'rivales_ext')

REPOS = [
    'foxtrotdelta-hub/flagrats', 'vsi7-m/despookjes', 'Aiko-vdm/DotGobblers', 'Wakie26/In-The-Fridge',
    'SebastianTabacariu/TooPac', 'robpriem/PacBoys', 'Scooooooott/Pacman_IDontThinkWeCanFinishThisToday',
    'Supergodgg/LL_Autonomous_Pacman', 'lorecleme/pacman-agent', 'marinadalmau/pacman-agent',
    'dea2001/pacManContest', 'amolaaudi/tortosa_pacman', 'rcrtss/pacman-agent',
    'Cambie26/pacman-agent-BonaTarda', 'cherryneosea/TheDotDominators', 'maferfarfan2122/pacman_AS',
    'amadeohm/AutSys-pacman', 'sta05/Clingho_pacman', 'eliasdevvub/pacboywhite',
]

os.makedirs(DEST, exist_ok=True)
env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
for r in REPOS:
    folder = os.path.join(DEST, r.replace('/', '__'))
    if os.path.isdir(folder):
        print(f'ya existe   {r}')
        continue
    p = subprocess.run(['git', 'clone', '-q', '--depth', '1', f'https://github.com/{r}.git', folder],
                       capture_output=True, text=True, env=env)
    ok = p.returncode == 0 and os.path.isfile(os.path.join(folder, 'my_team.py'))
    print(f"{'OK         ' if ok else 'NO DISPONIBLE'} {r}")
