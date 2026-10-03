"""
Ler e gravar vídeo com o PyAV — o FFmpeg que vem dentro do pacote Python.

**Vídeo de celular gravado em pé** costuma vir deitado no arquivo, com um metadado
dizendo quanto girar na hora de mostrar. O PyAV entrega o quadro sem girar e o ângulo
em ``frame.rotation`` (graus no sentido anti-horário); aqui o quadro é endireitado
com ``np.rot90`` — o mesmo resultado que o ``ffmpeg`` mostra, conferido nos dois
sentidos (+90 e −90).
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image

from editor import saida as saida_mod

#: A taxa de amostragem do áudio em todo o editor.
TAXA = 48_000


@dataclass(frozen=True)
class Info:
    largura: int          # já endireitado
    altura: int
    fps: Fraction
    duracao: float
    tem_audio: bool
    rotacao: int          # graus, anti-horário, como o PyAV informa

    @property
    def vertical(self) -> bool:
        return self.altura > self.largura


def _giro(rotacao: int) -> int:
    return round((rotacao or 0) / 90) % 4


def sondar(caminho: Path) -> Info:
    """Tamanho, fps, duração, áudio e rotação do vídeo."""
    with av.open(str(caminho)) as c:
        if not c.streams.video:
            raise ValueError("o arquivo não tem vídeo")
        v = c.streams.video[0]
        fps = v.average_rate or v.guessed_rate or Fraction(30)
        rotacao = 0
        for quadro in c.decode(video=0):
            rotacao = int(getattr(quadro, "rotation", 0) or 0)
            break
        if c.duration:
            duracao = c.duration / av.time_base
        elif v.duration and v.time_base:
            duracao = float(v.duration * v.time_base)
        else:
            duracao = (v.frames or 0) / float(fps)
        largura, altura = v.width, v.height
        if _giro(rotacao) % 2 == 1:
            largura, altura = altura, largura
        return Info(largura, altura, Fraction(fps).limit_denominator(100_000), float(duracao),
                    bool(c.streams.audio), rotacao)


def quadros(caminho: Path, rotacao: int = 0) -> Iterator[tuple[float, np.ndarray]]:
    """Cada quadro como (instante em segundos, matriz RGB), já endireitado."""
    k = _giro(rotacao)
    with av.open(str(caminho)) as c:
        stream = c.streams.video[0]
        stream.thread_type = "AUTO"
        for quadro in c.decode(stream):
            if quadro.time is None:
                continue
            matriz = quadro.to_ndarray(format="rgb24")
            if k:
                matriz = np.ascontiguousarray(np.rot90(matriz, k=k))
            yield float(quadro.time), matriz


def quadro_em(caminho: Path, t: float, rotacao: int = 0) -> np.ndarray | None:
    """Um quadro perto do instante ``t`` (para escolher a thumbnail)."""
    k = _giro(rotacao)
    with av.open(str(caminho)) as c:
        stream = c.streams.video[0]
        alvo = int(max(0.0, t) / stream.time_base) if stream.time_base else 0
        with contextlib.suppress(av.error.FFmpegError):
            c.seek(alvo, stream=stream, backward=True, any_frame=False)
        melhor = None
        for quadro in c.decode(stream):
            if quadro.time is None:
                continue
            melhor = quadro
            if quadro.time >= t:
                break
        if melhor is None:
            return None
        matriz = melhor.to_ndarray(format="rgb24")
        return np.ascontiguousarray(np.rot90(matriz, k=k)) if k else matriz


def ler_audio(caminho: Path, duracao: float | None = None) -> np.ndarray:
    """O áudio inteiro em estéreo, ``TAXA`` Hz, ``float32`` (amostras × 2)."""
    pedacos = []
    with av.open(str(caminho)) as c:
        if not c.streams.audio:
            n = round((duracao or 0.0) * TAXA)
            return np.zeros((n, 2), dtype=np.float32)
        stream = c.streams.audio[0]
        reamostrador = av.AudioResampler(format="fltp", layout="stereo", rate=TAXA)
        for quadro in c.decode(stream):
            for r in reamostrador.resample(quadro):
                pedacos.append(r.to_ndarray())
        for r in reamostrador.resample(None):
            pedacos.append(r.to_ndarray())
    if not pedacos:
        return np.zeros((0, 2), dtype=np.float32)
    return np.ascontiguousarray(np.concatenate(pedacos, axis=1).T.astype(np.float32))


def ler_audio_mono(caminho: Path, taxa: int = 16_000) -> np.ndarray:
    """O áudio em mono, na taxa pedida (16 kHz para o Whisper), ``float32``."""
    pedacos = []
    with av.open(str(caminho)) as c:
        if not c.streams.audio:
            return np.zeros(0, dtype=np.float32)
        reamostrador = av.AudioResampler(format="flt", layout="mono", rate=taxa)
        for quadro in c.decode(c.streams.audio[0]):
            for r in reamostrador.resample(quadro):
                pedacos.append(r.to_ndarray().reshape(-1))
        for r in reamostrador.resample(None):
            pedacos.append(r.to_ndarray().reshape(-1))
    if not pedacos:
        return np.zeros(0, dtype=np.float32)
    return np.ascontiguousarray(np.concatenate(pedacos).astype(np.float32))


class Gravador:
    """Grava os quadros e o áudio no formato escolhido, intercalados no tempo."""

    def __init__(self, caminho: Path, opcoes: saida_mod.OpcoesDeSaida, largura: int,
                 altura: int, fps: Fraction, *, com_audio: bool):
        self.caminho = Path(caminho)
        self.opcoes = opcoes.resolvidas()
        self.largura, self.altura, self.fps = largura, altura, fps
        self.indice = 0
        self._gif: list[Image.Image] | None = None
        self._audio: np.ndarray | None = None
        self._enviado = 0
        if self.opcoes.formato == "gif":
            self._gif = []
            return
        conteiner = saida_mod.FORMATOS[self.opcoes.formato][0]
        extras = {"movflags": "+faststart"} if conteiner in ("mp4", "mov") else {}
        self.c = av.open(str(self.caminho), "w", format=conteiner, options=extras)
        nome = saida_mod.encoder(self.opcoes.codec)
        ajustes, taxa_de_bits = saida_mod.ajustes_do_encoder(nome, self.opcoes.qualidade,
                                                             largura, altura, fps)
        self.v = self.c.add_stream(nome, rate=fps, options=ajustes)
        self.v.width, self.v.height = largura, altura
        self.v.pix_fmt = saida_mod.CODECS[self.opcoes.codec][1]
        if taxa_de_bits:
            self.v.bit_rate = taxa_de_bits
        self.a = None
        if com_audio and self.opcoes.audio:
            nome_audio, bits = saida_mod.AUDIOS[self.opcoes.audio]
            self.a = self.c.add_stream(nome_audio, rate=TAXA)
            self.a.layout = "stereo"
            self.a.bit_rate = bits

    def preparar_audio(self, amostras: np.ndarray) -> None:
        """O áudio final inteiro; ele é gravado aos poucos, junto com os quadros."""
        self._audio = amostras

    def quadro(self, matriz: np.ndarray) -> None:
        if self._gif is not None:
            self._gif.append(Image.fromarray(matriz))
            self.indice += 1
            return
        f = av.VideoFrame.from_ndarray(matriz, format="rgb24")
        f.pts = self.indice
        for pacote in self.v.encode(f):
            self.c.mux(pacote)
        self.indice += 1
        self._enviar_audio(self.indice / float(self.fps))

    def _enviar_audio(self, ate_s: float | None) -> None:
        if self.a is None or self._audio is None:
            return
        fim = len(self._audio) if ate_s is None else min(len(self._audio),
                                                         int(ate_s * TAXA) + TAXA // 10)
        while self._enviado < fim:
            n = min(fim - self._enviado, 4096)
            pedaco = np.ascontiguousarray(self._audio[self._enviado:self._enviado + n].T)
            af = av.AudioFrame.from_ndarray(pedaco, format="fltp", layout="stereo")
            af.sample_rate = TAXA
            af.pts = self._enviado
            for pacote in self.a.encode(af):
                self.c.mux(pacote)
            self._enviado += n

    def fechar(self) -> None:
        if self._gif is not None:
            if self._gif:
                passo = max(1, round(1000 / float(self.fps)))
                self._gif[0].save(self.caminho, save_all=True, append_images=self._gif[1:],
                                  duration=passo, loop=0, optimize=True)
            return
        for pacote in self.v.encode():
            self.c.mux(pacote)
        self._enviar_audio(None)
        if self.a is not None:
            for pacote in self.a.encode():
                self.c.mux(pacote)
        self.c.close()

    def __enter__(self) -> Gravador:
        return self

    def __exit__(self, tipo, *_resto) -> None:
        if tipo is None:
            self.fechar()
        elif self._gif is None:
            try:
                self.c.close()
            finally:
                self.caminho.unlink(missing_ok=True)


__all__ = ["TAXA", "Gravador", "Info", "ler_audio", "ler_audio_mono", "quadro_em", "quadros",
           "sondar"]
