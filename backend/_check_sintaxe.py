"""Verificação de sintaxe de todos os módulos do backend.

Roda `ast.parse` sem importar nada: pega erro de sintaxe sem precisar de
dependência instalada nem de banco no ar.
"""

import ast
import glob
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

alvos = sorted(
    set(glob.glob("app/**/*.py", recursive=True) + ["criar_admin.py"] + glob.glob("alembic/versions/*.py"))
)

falhas = 0
for caminho in alvos:
    fonte = open(caminho, "rb").read().decode("utf-8")
    try:
        ast.parse(fonte, filename=caminho)
        print(f"  ok    {caminho}")
    except SyntaxError as erro:
        falhas += 1
        linha = erro.lineno or 0
        print(f"  FALHA {caminho} linha {linha}: {erro.msg}")
        print(f"        {fonte.splitlines()[linha - 1] if linha else ''}")

print(f"\n{len(alvos) - falhas}/{len(alvos)} arquivos sem erro de sintaxe")
sys.exit(1 if falhas else 0)