"""Auditoria de encoding dos documentos e do código.

Dois defeitos que já ocorreram e valem detectar:

1. Texto com dupla codificação (mojibake): "mÃ­nimo" no lugar de "mínimo".
   Aparece quando um arquivo é gravado em UTF-8 e depois lido como latin-1.
2. Byte inválido no meio do arquivo, que o Python substitui por U+FFFD.

    python _check_encoding.py
"""

import glob
import os
import sys
import unicodedata

os.chdir(os.path.dirname(os.path.abspath(__file__)))

alvos = sorted(glob.glob("docs/*.md") + ["../README.md"] + glob.glob("app/**/*.py", recursive=True))

# Sinais de mojibake: sequências que nunca aparecem em português correto.
SINAIS = [
    "Ã©", "Ã£", "Ã­", "Ãº", "Ã§", "Ã£o", "â€", "Â ", "Â·", "ï¿½",
    "ð\x9f", "Ã\x83", "Ã\x82", "â€”", "â€œ",
]

problemas = 0

for caminho in alvos:
    bruto = open(caminho, "rb").read()

    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError as erro:
        problemas += 1
        linha = bruto[: erro.start].count(b"\n") + 1
        print(f"  BYTE INVALIDO  {caminho} linha {linha}: {erro.reason}")
        continue

    achados = [s for s in SINAIS if s in texto]
    if achados:
        problemas += 1
        print(f"  MOJIBAKE       {caminho} -> {achados}")
        for sinal in achados[:3]:
            i = texto.index(sinal)
            linha = texto[:i].count("\n") + 1
            trecho = texto[max(0, i - 40) : i + 30].replace("\n", " / ")
            print(f"      linha {linha}: {trecho}")

print(f"\n{len(alvos) - problemas}/{len(alvos)} arquivos limpos")
sys.exit(1 if problemas else 0)