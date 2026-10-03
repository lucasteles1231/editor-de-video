"""
O Whisper de verdade, de ponta a ponta. O workflow manual ``whisper.yml`` roda isto no
Windows e no Mac, com uma fala sintetizada pela voz do próprio sistema:

    uv run python tests/whisper_de_verdade.py fala.wav [--modelo tiny] [--idioma en]

Monta um vídeo com a fala duas vezes, entre pausas longas, edita com o modelo pedido e
confere que saíram palavras e que as pausas foram cortadas. O pytest não coleta este
arquivo: ele baixa o modelo e leva dezenas de segundos.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from editor import render, saida, video
from editor.opcoes import OpcoesDeEdicao
from tests.conftest import fazer_video

PAUSA_S = 1.5


def main() -> int:
    ap = argparse.ArgumentParser(description="O Whisper de verdade, de ponta a ponta.")
    ap.add_argument("fala", type=Path, help="um arquivo de áudio com fala")
    ap.add_argument("--modelo", default="tiny")
    ap.add_argument("--idioma", default="en")
    a = ap.parse_args()

    fala = video.ler_audio(a.fala)
    pausa = np.zeros((round(PAUSA_S * video.TAXA), 2), np.float32)
    som = np.concatenate([pausa, fala, pausa, fala, pausa])
    with tempfile.TemporaryDirectory() as tmp:
        entrada = fazer_video(Path(tmp) / "fala.mp4", segundos=len(som) / video.TAXA,
                              audio=som)
        r = render.editar(entrada, Path(tmp) / "editado.mp4",
                          OpcoesDeEdicao(modelo=a.modelo, idioma=a.idioma),
                          saida.OpcoesDeSaida(srt=True))
        plano = json.loads(Path(r.plano).read_text(encoding="utf-8"))

    palavras = [w["texto"] for b in plano["blocos"] for w in b["palavras"]]
    print(f"{r.duracao_original:.1f} s → {r.duracao_final:.1f} s em {r.segundos:.0f} s, "
          f"{len(palavras)} palavras:\n  {' '.join(palavras)}")
    falhas = []
    if len(palavras) < 8:
        falhas.append("quase nenhuma palavra transcrita")
    # Três pausas de 1,5 s; sobram uns 0,3 s delas.
    if r.duracao_final > r.duracao_original - 2 * PAUSA_S:
        falhas.append("as pausas não foram cortadas")
    for f in falhas:
        print(f"FALHOU: {f}", file=sys.stderr)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
