"""Prepara una versión de my_team.py para compartir con otra persona revelando
lo mínimo posible de cómo funciona por dentro.

Qué hace:
  1. Quita todos los comentarios y docstrings (explican la estrategia).
  2. Quita el bloque PACMAN_PARAMS (solo sirve para entrenar en local).
  3. Compila el resultado a bytecode (.pyc) con TU versión de Python.
  4. Crea un my_team.py "cargador" de pocas líneas que carga ese .pyc.

Resultado en compartir/:  my_team.py  +  team_core.pyc
Con --un-archivo:          compartir/my_team.py  (un solo archivo, con el
                           bytecode comprimido dentro; no se puede leer como texto)
Con --nativo:              compartir/my_team.py  +  team_core.<abi>.so
                           (extensión compilada con Cython: código máquina, no
                           bytecode; es el más difícil de leer de los tres)

IMPORTANTE:
  - El .pyc solo funciona con la MISMA versión de Python (p.ej. 3.12.x) que
    use quien lo recibe. Ejecuta este script con esa versión.
  - Un .pyc NO es un cifrado: con herramientas se puede desensamblar y, a
    veces, reconstruir código parecido. Solo lo hace más difícil de leer.
  - El .so tampoco es un cifrado, pero sí es código máquina: no hay
    decompilador que devuelva Python. Quedan a la vista los nombres de
    funciones, clases y los textos literales (`strings` los muestra).
  - El .so depende de la versión de Python (3.12), de la arquitectura
    (x86-64), del sistema (Linux) y de la versión de glibc con la que se
    compila: solo sirve en un entorno compatible.

Uso (desde la raíz del repo):
    python tools/empaquetar.py                         # compila con tu Python
    python tools/empaquetar.py --python /ruta/python3.8 # compila para otra versión
    python tools/empaquetar.py --un-archivo --python /ruta/python3.8
    python tools/empaquetar.py --nativo                 # .so para tu Python (requiere Cython y gcc)

Para conseguir Python 3.8 sin tocar el del sistema:
    pip install uv
    uv python install 3.8
    python tools/empaquetar.py --python "$(uv python find 3.8)"
"""
import argparse
import ast
import os
import py_compile
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, 'my_team.py')
OUT = os.path.join(REPO, 'compartir')

LOADER = '''import importlib.machinery, importlib.util, os
_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'team_core.pyc')
_l = importlib.machinery.SourcelessFileLoader('team_core', _p)
_m = importlib.util.module_from_spec(importlib.util.spec_from_loader('team_core', _l))
_l.exec_module(_m)
create_team = _m.create_team
'''

NATIVE_LOADER = '''import glob, importlib.machinery, importlib.util, os, sys
if sys.version_info[:2] != (%(mayor)d, %(menor)d):
    raise ImportError('my_team.py requiere Python %(mayor)d.%(menor)d (team_core es una extension compilada)')
_d = os.path.dirname(os.path.abspath(__file__))
_c = glob.glob(os.path.join(_d, 'team_core.*.so'))
if not _c:
    raise ImportError('falta team_core%(abi)s junto a my_team.py')
_l = importlib.machinery.ExtensionFileLoader('team_core', _c[0])
_m = importlib.util.module_from_spec(importlib.util.spec_from_loader('team_core', _l))
sys.modules['team_core'] = _m
_l.exec_module(_m)
create_team = _m.create_team
'''


class StripDocstrings(ast.NodeTransformer):
    def _strip(self, node):
        self.generic_visit(node)
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], 'value', None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
        return node

    visit_FunctionDef = visit_ClassDef = visit_Module = _strip


class StripParamsOverride(ast.NodeTransformer):
    """Elimina el try/except que lee la variable de entorno PACMAN_PARAMS."""
    def visit_Try(self, node):
        if 'PACMAN_PARAMS' in ast.unparse(node):
            return None
        return node


def consulta(python, expr):
    """Pregunta algo al intérprete DESTINO (no al nuestro)."""
    code = f'import sysconfig, sys; print({expr})'
    return subprocess.run([python, '-c', code], check=True, capture_output=True, text=True).stdout.strip()


def build_native(tmp, python, out):
    """Compila team_core.py a una extensión nativa (.so) con Cython + gcc."""
    c_file = os.path.join(out, 'team_core.c')
    # Cython traduce Python a C. Sin docstrings ni el código fuente como comentarios.
    cython = [sys.executable, '-m', 'cython', '-3', '--no-docstrings',
              '-X', 'emit_code_comments=False', '-o', c_file, tmp]
    r = subprocess.run(cython, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('Cython falló (¿pip install cython?):\n' + (r.stderr or r.stdout))

    inc = consulta(python, "sysconfig.get_paths()['include']")
    suffix = consulta(python, "sysconfig.get_config_var('EXT_SUFFIX')")
    version = consulta(python, "'%d.%d' % sys.version_info[:2]")
    so = os.path.join(out, 'team_core' + suffix)
    gcc = ['gcc', '-shared', '-fPIC', '-O2', '-fvisibility=hidden',
           '-I' + inc, '-o', so, c_file]
    r = subprocess.run(gcc, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('gcc falló:\n' + (r.stderr or r.stdout))
    subprocess.run(['strip', '-s', so], capture_output=True)  # quita símbolos de depuración

    mayor, menor = (int(x) for x in version.split('.'))
    loader = NATIVE_LOADER % {'mayor': mayor, 'menor': menor, 'abi': suffix}
    open(os.path.join(out, 'my_team.py'), 'w').write(loader)
    os.remove(c_file)
    return so, version, suffix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--python', help='intérprete con el que compilar (p.ej. Python 3.8)')
    ap.add_argument('--un-archivo', action='store_true', help='generar un único my_team.py')
    ap.add_argument('--nativo', action='store_true',
                    help='compilar a extensión nativa .so con Cython (necesita Cython y gcc)')
    args = ap.parse_args()
    tree = ast.parse(open(SRC).read())
    tree = StripParamsOverride().visit(StripDocstrings().visit(tree))
    ast.fix_missing_locations(tree)
    clean = ast.unparse(tree)  # ast.unparse no conserva comentarios

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    tmp = os.path.join(OUT, 'team_core.py')
    open(tmp, 'w').write(clean)
    python = args.python or sys.executable
    if args.nativo:
        so, version, suffix = build_native(tmp, python, OUT)
        os.remove(tmp)
        print(f'Listo: {OUT}/my_team.py + {os.path.basename(so)}')
        print(f'Compilado para Python {version} ({suffix}): hay que entregar LOS DOS archivos juntos.')
        return
    if args.un_archivo:
        # El intérprete destino compila el código y lo serializa (marshal),
        # comprimido y en base64, dentro de un my_team.py de pocas líneas.
        target = os.path.join(OUT, 'my_team.py')
        code = (
            "import base64, marshal, sys, zlib\n"
            f"src = open({tmp!r}).read()\n"
            "co = compile(src, 'team_core', 'exec', optimize=2)\n"
            "blob = base64.b64encode(zlib.compress(marshal.dumps(co), 9)).decode()\n"
            "v = sys.version_info[:2]\n"
            "lines = [blob[i:i + 100] for i in range(0, len(blob), 100)]\n"
            "body = 'import base64, marshal, sys, zlib\\n'\n"
            "body += 'if sys.version_info[:2] != %r:\\n' % (v,)\n"
            "body += '    raise ImportError(\"my_team.py requiere Python %d.%d\")\\n' % v\n"
            "body += '_B = (\\n' + ''.join('    %r\\n' % l for l in lines) + ')\\n'\n"
            "body += 'exec(marshal.loads(zlib.decompress(base64.b64decode(_B))))\\n'\n"
            f"open({target!r}, 'w').write(body)\n"
            "print('%d.%d' % v)\n"
        )
        version = subprocess.run([python, '-c', code], check=True, capture_output=True, text=True).stdout.strip()
        os.remove(tmp)
        print(f'Listo: {target} (un solo archivo)')
        print(f'Compilado para Python {version}: quien lo reciba debe usar Python {version}.x')
        return

    pyc = os.path.join(OUT, 'team_core.pyc')
    code = (f"import py_compile, sys; py_compile.compile({tmp!r}, cfile={pyc!r}, doraise=True, optimize=2); "
            f"print('%d.%d' % sys.version_info[:2])")
    version = subprocess.run([python, '-c', code], check=True, capture_output=True, text=True).stdout.strip()
    os.remove(tmp)
    open(os.path.join(OUT, 'my_team.py'), 'w').write(LOADER)

    print(f'Listo: {OUT}/my_team.py + team_core.pyc')
    print(f'Compilado para Python {version}: quien lo reciba debe usar Python {version}.x')


if __name__ == '__main__':
    main()
