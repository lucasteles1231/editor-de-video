"""
Ler e gravar vídeo com o PyAV — o FFmpeg que vem dentro do pacote Python.

**Vídeo de celular gravado em pé** costuma vir deitado no arquivo, com um metadado
dizendo quanto girar na hora de mostrar. O PyAV entrega o quadro sem girar e o ângulo
em ``frame.rotation`` (graus no sentido anti-horário); aqui o quadro é endireitado
com ``np.rot90`` — o mesmo resultado que o ``ffmpeg`` mostra, conferido nos dois
sentidos (+90 e −90).

**Vídeo com transparência** (a pessoa já sem fundo): o MOV com ProRes 4444, PNG ou
Animation sai com alfa do decodificador de sempre. O WebM VP9 guarda o alfa à parte, e o
decodificador nativo do FFmpeg joga ele fora; só o ``libvpx-vp9``, escolhido à mão e
alimentado com os pacotes do contêiner, devolve ``yuva420p``. O arquivo avisa que tem
alfa pela tag ``alpha_mode``. Conferido com arquivos gerados pelo próprio PyAV.
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


def _alfa_no_vp9(stream) -> bool:
    return (stream.codec_context.name == "vp9"
            and str(stream.metadata.get("alpha_mode", "")).strip() == "1")


def tem_alfa(caminho: Path) -> bool:
    """Se o vídeo tem transparência (a pessoa já vem sem fundo)."""
    try:
        with av.open(str(caminho)) as c:
            if not c.streams.video:
                return False
            s = c.streams.video[0]
            if s.codec_context.name == "vp9":
                return _alfa_no_vp9(s)
            nome = s.codec_context.pix_fmt
            if not nome:
                for quadro in c.decode(s):
                    nome = quadro.format.name
                    break
            if not nome:
                return False
            return any(comp.is_alpha for comp in av.video.format.VideoFormat(nome).components)
    except (av.error.FFmpegError, ValueError, OSError):
        return False


def quadros(caminho: Path, rotacao: int = 0, *, alfa: bool = False
            ) -> Iterator[tuple[float, np.ndarray]]:
    """Cada quadro como (instante em segundos, matriz RGB ou RGBA), já endireitado."""
    k = _giro(rotacao)
    formato = "rgba" if alfa else "rgb24"
    with av.open(str(caminho)) as c:
        stream = c.streams.video[0]
        if alfa and _alfa_no_vp9(stream):
            yield from _quadros_do_vp9_com_alfa(c, stream, k)
            return
        stream.thread_type = "AUTO"
        for quadro in c.decode(stream):
            if quadro.time is None:
                continue
            matriz = quadro.to_ndarray(format=formato)
            if k:
                matriz = np.ascontiguousarray(np.rot90(matriz, k=k))
            yield float(quadro.time), matriz


def _quadros_do_vp9_com_alfa(c, stream, k: int) -> Iterator[tuple[float, np.ndarray]]:
    ctx = av.CodecContext.create("libvpx-vp9", "r")
    if stream.codec_context.extradata:
        ctx.extradata = stream.codec_context.extradata
    base = stream.time_base
    for pacote in c.demux(stream):
        for quadro in ctx.decode(pacote):
            if quadro.pts is None:
                continue
            matriz = quadro.to_ndarray(format="rgba")
            if k:
                matriz = np.ascontiguousarray(np.rot90(matriz, k=k))
            yield float(quadro.pts * base), matriz


class Cursor:
    """Os quadros de um vídeo pedidos em ordem de tempo.

    ``em(t)`` devolve o último quadro com tempo até ``t``, decodificando só para frente.
    Quando o vídeo acaba antes do pedido, ele volta ao começo: na montagem, um fundo ou
    uma pessoa mais curtos que a fala ficam em loop, e não congelados.
    """

    def __init__(self, caminho: Path, rotacao: int = 0, *, alfa: bool = False,
                 duracao: float | None = None):
        self.caminho, self.rotacao, self.alfa = Path(caminho), rotacao, alfa
        self.duracao = duracao if duracao is not None else sondar(self.caminho).duracao
        self._abrir()

    def _abrir(self) -> None:
        antigo = getattr(self, "_gerador", None)
        if antigo is not None:
            antigo.close()                     # fecha o arquivo da volta anterior
        self._gerador = quadros(self.caminho, self.rotacao, alfa=self.alfa)
        self._atual: tuple[float, np.ndarray] | None = None
        self._proximo = next(self._gerador, None)
        self._ultimo_pedido = -1.0

    def em(self, t: float) -> np.ndarray | None:
        if self.duracao > 0 and t >= self.duracao:
            t = t % self.duracao
        if t < self._ultimo_pedido:
            self._abrir()                      # deu a volta: começa de novo
        self._ultimo_pedido = t
        while self._proximo is not None and (self._atual is None or self._proximo[0] <= t):
            self._atual = self._proximo
            self._proximo = next(self._gerador, None)
            if self._atual[0] >= t:
                break
        return None if self._atual is None else self._atual[1]

    def fechar(self) -> None:
        self._gerador.close()


def duracao_do_audio(caminho: Path) -> float:
    """A duração de um arquivo com áudio (MP3, WAV, M4A ou um vídeo)."""
    with av.open(str(caminho)) as c:
        if not c.streams.audio:
            raise ValueError("o arquivo não tem áudio")
        s = c.streams.audio[0]
        if c.duration:
            return c.duration / av.time_base
        if s.duration and s.time_base:
            return float(s.duration * s.time_base)
        return 0.0


def quadro_em(caminho: Path, t: float, rotacao: int = 0, *, alfa: bool = False
              ) -> np.ndarray | None:
    """Um quadro perto do instante ``t`` (para escolher a thumbnail), em RGB ou RGBA."""
    k = _giro(rotacao)
    with av.open(str(caminho)) as c:
        stream = c.streams.video[0]
        alvo = int(max(0.0, t) / stream.time_base) if stream.time_base else 0
        with contextlib.suppress(av.error.FFmpegError):
            c.seek(alvo, stream=stream, backward=True, any_frame=False)
        if alfa and _alfa_no_vp9(stream):
            # O alfa do VP9 só sai pelo libvpx, alimentado com os pacotes a partir do
            # ponto da busca (um quadro-chave).
            ctx = av.CodecContext.create("libvpx-vp9", "r")
            if stream.codec_context.extradata:
                ctx.extradata = stream.codec_context.extradata
            quadros_ = (q for pacote in c.demux(stream) for q in ctx.decode(pacote))

            def tempo(q):
                return None if q.pts is None else float(q.pts * stream.time_base)
        else:
            quadros_ = c.decode(stream)

            def tempo(q):
                return q.time
        melhor = None
        for quadro in quadros_:
            if tempo(quadro) is None:
                continue
            melhor = quadro
            if tempo(quadro) >= t:
                break
        if melhor is None:
            return None
        matriz = melhor.to_ndarray(format="rgba" if alfa else "rgb24")
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


__all__ = ["TAXA", "Cursor", "Gravador", "Info", "duracao_do_audio", "ler_audio",
           "ler_audio_mono", "quadro_em", "quadros", "sondar", "tem_alfa"]
