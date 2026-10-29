import ast, pathlib, sys

root = pathlib.Path('app')
errors = []
files = sorted(root.rglob('*.py'))
for f in files:
    try:
        source = f.read_text(encoding='utf-8')
        ast.parse(source, filename=str(f))
    except SyntaxError as e:
        errors.append(f'{f}: {e}')

if errors:
    print('ERRORES DE SINTAXIS:')
    for e in errors:
        print(' -', e)
    sys.exit(1)
else:
    print(f'OK: {len(files)} archivos sin errores de sintaxis.')
