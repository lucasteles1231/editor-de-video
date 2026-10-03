"""
O que os testes compartilham.

- **Nenhum teste roda o Whisper de verdade:** o transcritor falso fica ligado para
  todos. Esquecer isso num teste da interface rodaria o modelo sem ninguém perceber.
- **Nenhum teste escreve nas pastas do usuário:** o cache de transcrições e os envios
  vão para a pasta temporária do teste.
- **Os vídeos de teste são feitos pelo próprio PyAV**, sem ffmpeg na linha de comando,
  para rodar igual no Windows, no macOS e no Linux.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest

from editor import render, servidor, transcricao


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv(transcricao.VARIAVEL_FALSA, "falso")
    cache = tmp_path / "_cache"
    envios = tmp_path / "_envios"
    cache.mkdir()
    envios.mkdir()
    monkeypatch.setattr(render, "pasta_de_cache", lambda: cache)
    monkeypatch.setattr(servidor, "pasta_de_envios", lambda: envios)


def fazer_video(caminho: Path, *, largura: int = 320, altura: int = 568, segundos: float = 3.0,
                fps: int = 30, falas: list[tuple[float, float]] | None = None,
                com_audio: bool = True, audio: np.ndarray | None = None) -> Path:
    """Um vídeo de teste: imagem que muda a cada quadro e, no áudio, um tom nas
    ``falas`` (início, fim) e silêncio no resto — ou o ``audio`` dado (amostras × 2,
    48 kHz)."""
    caminho = Path(caminho)
    with av.open(str(caminho), "w") as c:
        v = c.add_stream("libx264", rate=fps, options={"crf": "30", "preset": "ultrafast"})
        v.width, v.height, v.pix_fmt = largura, altura, "yuv420p"
        a = None
        if com_audio:
            a = c.add_stream("aac", rate=48_000)
            a.layout = "stereo"
        n = round(segundos * fps)
        y = np.linspace(0, 255, altura, dtype=np.float32)[:, None]
        for i in range(n):
            matriz = np.empty((altura, largura, 3), np.uint8)
            matriz[..., 0] = (y + i * 4) % 256
            matriz[..., 1] = np.linspace(0, 255, largura, dtype=np.uint8)[None, :]
            matriz[..., 2] = (i * 9) % 256
            f = av.VideoFrame.from_ndarray(matriz, format="rgb24")
            f.pts = i
            for p in v.encode(f):
                c.mux(p)
        for p in v.encode():
            c.mux(p)
        if a is not None:
            taxa = 48_000
            if audio is not None:
                dados = np.ascontiguousarray(np.asarray(audio, dtype=np.float32).T)
            else:
                t = np.arange(round(segundos * taxa)) / taxa
                som = np.zeros_like(t, dtype=np.float32)
                for ini, fim in falas if falas is not None else [(0.2, segundos - 0.2)]:
                    trecho = (t >= ini) & (t < fim)
                    som[trecho] = 0.3 * np.sin(2 * np.pi * 220 * t[trecho])
                dados = np.ascontiguousarray(np.stack([som, som]).astype(np.float32))
            for k in range(0, dados.shape[1], 4096):
                af = av.AudioFrame.from_ndarray(np.ascontiguousarray(dados[:, k:k + 4096]),
                                                format="fltp", layout="stereo")
                af.sample_rate = taxa
                af.pts = k
                for p in a.encode(af):
                    c.mux(p)
            for p in a.encode():
                c.mux(p)
    return caminho


@pytest.fixture
def video(tmp_path) -> Path:
    return fazer_video(tmp_path / "entrada.mp4")


def ler_info(caminho: Path) -> dict:
    with av.open(str(caminho)) as c:
        v = c.streams.video[0]
        return {"largura": v.width, "altura": v.height,
                "fps": Fraction(v.average_rate or v.guessed_rate or 0),
                "duracao": (c.duration or 0) / av.time_base,
                "audio": [s.codec_context.name for s in c.streams.audio],
                "video": v.codec_context.name}


FIXTURES = Path(__file__).parent / "fixtures"
