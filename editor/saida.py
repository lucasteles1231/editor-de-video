"""
As opções de saída: formato, codec, resolução, quadros por segundo, qualidade e áudio.

O vídeo é gravado pelo FFmpeg que vem dentro do PyAV — nada a instalar no sistema.
O que cada computador grava é conferido na hora (:func:`disponiveis`), e só isso é
oferecido; o GIF sai pelo Pillow, que faz uma paleta melhor que o codificador do FFmpeg.
"""
from __future__ import annotations

import functools
from dataclasses import asdict, dataclass, fields
from fractions import Fraction

#: Formato → (contêiner do FFmpeg, codecs de vídeo, codecs de áudio), em ordem de
#: preferência. O primeiro de cada lista é o padrão.
FORMATOS = {
    "mp4": ("mp4", ("h264", "h265", "av1"), ("aac", "mp3")),
    "mov": ("mov", ("h264", "h265", "prores"), ("aac",)),
    "webm": ("webm", ("vp9", "av1"), ("opus",)),
    "mkv": ("matroska", ("h264", "h265", "vp9", "av1"), ("aac", "opus", "mp3")),
    "gif": ("gif", ("gif",), ()),
}

#: Codec → (encoders do FFmpeg em ordem de preferência, formato de pixel, nome).
CODECS = {
    "h264": (("libx264", "h264_videotoolbox", "h264_mf", "libopenh264"), "yuv420p", "H.264"),
    "h265": (("libx265", "hevc_videotoolbox", "hevc_mf"), "yuv420p", "H.265 (HEVC)"),
    "vp9": (("libvpx-vp9",), "yuv420p", "VP9"),
    "av1": (("libsvtav1", "libaom-av1"), "yuv420p", "AV1"),
    "prores": (("prores_ks", "prores"), "yuv422p10le", "ProRes"),
    "gif": ((), "rgb24", "GIF"),
}

AUDIOS = {"aac": ("aac", 192_000), "opus": ("libopus", 160_000), "mp3": ("libmp3lame", 192_000)}

#: Pelo lado curto: "1080p" de um vídeo vertical é 1080 × 1920.
RESOLUCOES = {"original": None, "2160p": 2160, "1440p": 1440, "1080p": 1080, "720p": 720,
              "480p": 480}
FPS = ("original", "24", "30", "60")
QUALIDADES = ("alta", "equilibrada", "leve")

#: O CRF de cada encoder (menor é melhor e maior).
CRF = {
    "libx264": {"alta": 18, "equilibrada": 23, "leve": 28},
    "libx265": {"alta": 20, "equilibrada": 26, "leve": 31},
    "libvpx-vp9": {"alta": 24, "equilibrada": 32, "leve": 38},
    "libsvtav1": {"alta": 26, "equilibrada": 34, "leve": 42},
    "libaom-av1": {"alta": 26, "equilibrada": 34, "leve": 42},
}
#: Bits por pixel por quadro, para os encoders que não têm CRF (os de hardware).
BPP = {"alta": 0.20, "equilibrada": 0.11, "leve": 0.06}
#: O perfil do ProRes: HQ, padrão e LT.
PERFIL_PRORES = {"alta": "3", "equilibrada": "2", "leve": "1"}

#: O GIF fica pequeno de propósito: sem som, curto e leve.
GIF_MAX_S = 30.0
GIF_FPS = 15
GIF_LADO_CURTO = 480


@dataclass
class OpcoesDeSaida:
    formato: str = "mp4"
    codec: str = ""
    resolucao: str = "original"
    fps: str = "original"
    qualidade: str = "alta"
    audio: str = ""
    srt: bool = False
    vtt: bool = False

    def resolvidas(self) -> OpcoesDeSaida:
        """As mesmas, com codec e áudio preenchidos pelo padrão do formato."""
        conteiner, codecs, audios = FORMATOS.get(self.formato, FORMATOS["mp4"])
        del conteiner
        codec = self.codec or next((c for c in codecs if encoder(c)), codecs[0])
        audio = self.audio or (audios[0] if audios else "")
        return OpcoesDeSaida(self.formato, codec, self.resolucao, self.fps, self.qualidade,
                             audio, self.srt, self.vtt)

    def problemas(self) -> list[str]:
        erros = []
        if self.formato not in FORMATOS:
            return [f"formato desconhecido: {self.formato} (use {', '.join(FORMATOS)})"]
        _conteiner, codecs, audios = FORMATOS[self.formato]
        r = self.resolvidas()
        if r.codec not in codecs:
            erros.append(f"{self.formato.upper()} não aceita o codec {r.codec} "
                         f"(aceita {', '.join(codecs)})")
        elif r.codec != "gif" and not encoder(r.codec):
            erros.append(f"este computador não grava {CODECS[r.codec][2]}")
        if r.audio and r.audio not in audios:
            erros.append(f"{self.formato.upper()} não aceita áudio {r.audio}")
        if self.resolucao not in RESOLUCOES:
            erros.append(f"resolução desconhecida: {self.resolucao}")
        if self.fps not in FPS:
            erros.append(f"quadros por segundo: use {', '.join(FPS)}")
        if self.qualidade not in QUALIDADES:
            erros.append(f"qualidade: use {', '.join(QUALIDADES)}")
        return erros

    @classmethod
    def de_dict(cls, dados: dict) -> OpcoesDeSaida:
        conhecidos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (dados or {}).items() if k in conhecidos})

    def para_dict(self) -> dict:
        return asdict(self)


@functools.lru_cache(maxsize=32)
def encoder(codec: str) -> str:
    """O primeiro encoder deste codec que o FFmpeg embutido tem, ou ""."""
    import av

    for nome in CODECS.get(codec, ((),))[0]:
        try:
            av.codec.Codec(nome, "w")
            return nome
        except Exception:
            continue
    return ""


@functools.lru_cache(maxsize=1)
def disponiveis() -> dict:
    """O que este computador grava: {formato: {"codecs": [...], "audios": [...]}}."""
    import av

    saida = {}
    for formato, (conteiner, codecs, audios) in FORMATOS.items():
        if formato != "gif" and conteiner not in av.formats_available:
            continue
        cs = [c for c in codecs if c == "gif" or encoder(c)]
        aus = [a for a in audios if _tem_encoder(AUDIOS[a][0])]
        if cs:
            saida[formato] = {"codecs": cs, "audios": aus}
    return saida


def _tem_encoder(nome: str) -> bool:
    import av

    try:
        av.codec.Codec(nome, "w")
        return True
    except Exception:
        return False


def _par(x: float) -> int:
    return max(2, round(x / 2) * 2)


def tamanho(largura: int, altura: int, resolucao: str, formato: str = "mp4") -> tuple[int, int]:
    """O tamanho de saída: pelo lado curto, sem aumentar além do original, sempre par."""
    alvo = RESOLUCOES.get(resolucao)
    curto = min(largura, altura)
    if formato == "gif":
        alvo = min(alvo or curto, GIF_LADO_CURTO)
    if not alvo or alvo >= curto:
        return _par(largura), _par(altura)
    k = alvo / curto
    return _par(largura * k), _par(altura * k)


def fps_de_saida(fps_entrada: Fraction, escolha: str, formato: str = "mp4") -> Fraction:
    if formato == "gif":
        return Fraction(min(GIF_FPS, float(fps_entrada) or GIF_FPS)).limit_denominator(1000)
    if escolha in ("", "original"):
        return fps_entrada if fps_entrada > 0 else Fraction(30)
    return Fraction(int(escolha))


def ajustes_do_encoder(nome: str, qualidade: str, largura: int, altura: int,
                       fps: Fraction) -> tuple[dict, int | None]:
    """(opções do encoder, taxa de bits) para a qualidade pedida."""
    if nome in CRF:
        opcoes = {"crf": str(CRF[nome][qualidade])}
        if nome in ("libx264", "libx265"):
            opcoes["preset"] = "medium"
        if nome == "libvpx-vp9":
            opcoes.update({"b": "0", "row-mt": "1", "deadline": "good", "cpu-used": "4"})
        if nome == "libsvtav1":
            opcoes["preset"] = "8"
        return opcoes, None
    if nome.startswith("prores"):
        return {"profile": PERFIL_PRORES[qualidade]}, None
    return {}, int(BPP[qualidade] * largura * altura * float(fps))


__all__ = ["AUDIOS", "CODECS", "FORMATOS", "FPS", "QUALIDADES", "RESOLUCOES", "OpcoesDeSaida",
           "ajustes_do_encoder", "disponiveis", "encoder", "fps_de_saida", "tamanho"]
