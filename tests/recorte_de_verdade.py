"""
O recorte de verdade: baixa o MODNet e roda num quadro. O workflow manual
``modelos.yml`` roda isto no Windows e no Mac — é o que os testes comuns não cobrem
(eles usam uma silhueta falsa): o onnxruntime carregando o modelo em cada sistema.

    uv run python tests/recorte_de_verdade.py

O pytest não coleta este arquivo: ele baixa 26 MB.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from editor import recorte


def main() -> int:
    os.environ.pop(recorte.VARIAVEL_FALSA, None)
    # Um quadro qualquer, com uma forma clara no meio: o modelo tem de carregar, rodar e
    # devolver um alfa do tamanho do quadro, de 0 a 1.
    quadro = np.full((720, 405, 3), 40, np.uint8)
    yy, xx = np.mgrid[0:720, 0:405]
    quadro[((xx - 202) / 70) ** 2 + ((yy - 230) / 90) ** 2 <= 1] = (225, 190, 160)
    quadro[(yy > 330) & (np.abs(xx - 202) < 60 + (yy - 330) * 0.6)] = (60, 90, 160)
    comeco = time.monotonic()
    alfa = recorte.mascara(quadro)
    segundos = time.monotonic() - comeco
    print(f"MODNet rodou em {segundos:.1f} s (com o download na primeira vez); "
          f"alfa {alfa.shape}, de {alfa.min():.2f} a {alfa.max():.2f}, média {alfa.mean():.2f}")
    falhas = []
    if alfa.shape != quadro.shape[:2]:
        falhas.append("o alfa não tem o tamanho do quadro")
    if not (float(alfa.min()) >= 0.0 and float(alfa.max()) <= 1.0):
        falhas.append("o alfa saiu de 0 a 1")
    if not recorte.modelo_baixado():
        falhas.append("o modelo não ficou no cache")
    for f in falhas:
        print(f"FALHOU: {f}", file=sys.stderr)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
