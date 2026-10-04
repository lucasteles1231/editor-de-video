"""
O recorte da pessoa: tira o fundo de um quadro, para a thumbnail pôr quem fala na
frente de um fundo novo, com contorno branco.

Usa o MODNet, um modelo de recorte de retrato de 26 MB (código e pesos Apache-2.0), que
roda no próprio computador pelo ``onnxruntime`` — o mesmo que o faster-whisper já usa.
Ele é baixado do Hugging Face no primeiro uso, como o modelo da transcrição, e daí em
diante é lido do cache, sem rede.

Para testes há um recorte falso, ligado por ``EDITOR_RECORTE=falso``: uma silhueta de
busto no meio do quadro, sem baixar modelo nenhum.
"""
from __future__ import annotations

import io
import logging
import os
import threading
from dataclasses import dataclass

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

#: O modelo, numa revisão fixa: o mesmo arquivo para todo mundo, e ele só muda com uma
#: versão nova do editor.
REPOSITORIO = "Xenova/modnet"
ARQUIVO = "onnx/model.onnx"
REVISAO = "fa2fa546052fba4c08921230a26cc69a333fca12"
TAMANHO = "26 MB"

#: O lado curto da imagem que o modelo recebe, e o múltiplo que os dois lados precisam ter.
LADO_DO_MODELO = 512
MULTIPLO = 32
#: A partir de quanto o alfa conta como pessoa, para medir as caixas.
LIMIAR = 0.5
#: Menos que isto do quadro não é uma pessoa: é o modelo achando gente numa parede.
AREA_MINIMA = 0.02
#: Abaixo disto o alfa é ruído e vira zero.
ALFA_MINIMO = 0.12
#: O rosto, quando ninguém disse onde ele está: a cabeça termina onde a silhueta
#: alarga mais que isto (os ombros)...
OMBROS = 1.5
#: ...e, se não alargar, a faixa de cima com esta fração da silhueta.
FAIXA_DO_ROSTO = 0.26

#: A variável que liga o recorte falso (só testes).
VARIAVEL_FALSA = "EDITOR_RECORTE"

# O mesmo aviso que a transcrição desliga: no primeiro download o servidor do Hugging
# Face pede um token, e não é preciso conta nenhuma.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


@dataclass(frozen=True)
class Caixa:
    """Uma caixa em frações do quadro, de 0 a 1."""

    x0: float
    y0: float
    x1: float
    y1: float

    def para_dict(self) -> dict:
        return {k: round(v, 4) for k, v in (("x0", self.x0), ("y0", self.y0),
                                             ("x1", self.x1), ("y1", self.y1))}


@dataclass
class Recorte:
    #: O alfa no tamanho do quadro, de 0 a 1.
    alfa: np.ndarray
    pessoa: Caixa | None
    rosto: Caixa | None

    @property
    def ok(self) -> bool:
        return self.pessoa is not None


def _falso() -> bool:
    return os.environ.get(VARIAVEL_FALSA, "").strip().lower() == "falso"


def modelo_baixado() -> bool:
    """Se o modelo já está no cache — para avisar do download antes de começar."""
    if _falso():
        return True
    try:
        from huggingface_hub import hf_hub_download

        hf_hub_download(REPOSITORIO, ARQUIVO, revision=REVISAO, local_files_only=True)
        return True
    except Exception:
        return False


_sessao = None
_trava = threading.Lock()


def _carregar():
    """A sessão do onnxruntime, criada uma vez (e baixando o modelo na primeira)."""
    global _sessao
    with _trava:
        if _sessao is None:
            import onnxruntime
            from huggingface_hub import hf_hub_download

            caminho = hf_hub_download(REPOSITORIO, ARQUIVO, revision=REVISAO,
                                      local_files_only=modelo_baixado())
            opcoes = onnxruntime.SessionOptions()
            opcoes.log_severity_level = 3
            _sessao = onnxruntime.InferenceSession(caminho, sess_options=opcoes,
                                                   providers=["CPUExecutionProvider"])
        return _sessao


def tamanho_de_entrada(altura: int, largura: int) -> tuple[int, int]:
    """O tamanho que o modelo recebe: lado curto perto de 512, os dois múltiplos de 32."""
    escala = LADO_DO_MODELO / min(altura, largura)

    def multiplo(x: float) -> int:
        return max(MULTIPLO, round(x * escala / MULTIPLO) * MULTIPLO)

    return multiplo(altura), multiplo(largura)


def preparar(matriz: np.ndarray) -> np.ndarray:
    """O quadro (altura × largura × 3, uint8) no formato do modelo: 1 × 3 × A × L, de -1 a 1."""
    alt, lar = tamanho_de_entrada(*matriz.shape[:2])
    img = Image.fromarray(matriz).convert("RGB").resize((lar, alt), Image.BILINEAR)
    x = np.asarray(img, dtype=np.float32) / 255.0
    x = (x - 0.5) / 0.5
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


def _silhueta_falsa(altura: int, largura: int) -> np.ndarray:
    """Um busto: cabeça redonda em cima, ombros largos embaixo."""
    yy, xx = np.mgrid[0:altura, 0:largura]
    y, x = yy / altura, xx / largura
    cabeca = ((x - 0.5) / 0.13) ** 2 + ((y - 0.32) / 0.11) ** 2 <= 1
    ombros = (y >= 0.48) & (np.abs(x - 0.5) <= 0.16 + (y - 0.48) * 0.9)
    return (cabeca | ombros).astype(np.float32)


def mascara(matriz: np.ndarray) -> np.ndarray:
    """O alfa da pessoa no tamanho do quadro, de 0 a 1."""
    altura, largura = matriz.shape[:2]
    if _falso():
        return _silhueta_falsa(altura, largura)
    sessao = _carregar()
    entrada = preparar(matriz)
    saida = sessao.run(None, {sessao.get_inputs()[0].name: entrada})[0]
    alfa = np.clip(np.asarray(saida, dtype=np.float32).reshape(saida.shape[-2:]), 0.0, 1.0)
    img = Image.fromarray((alfa * 255).astype(np.uint8)).resize((largura, altura),
                                                                 Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def so_a_pessoa(alfa: np.ndarray) -> np.ndarray:
    """O alfa sem as manchas soltas: fica só a maior parte ligada.

    Visto com fala real: numa mesa, o modelo pega pedaços semitransparentes do tampo
    perto das mãos. Eles sujam o recorte e esticam a caixa da pessoa até a borda do
    quadro, e aí o enquadramento no rosto erra a conta.
    """
    alfa = np.where(alfa < ALFA_MINIMO, 0.0, alfa).astype(np.float32)
    altura, largura = alfa.shape
    passo = max(1, round(max(altura, largura) / 256))
    grade = alfa[::passo, ::passo] > LIMIAR
    if not grade.any():
        return alfa
    # A semente é a célula mais cercada de pessoa; dali a região cresce, presa à máscara.
    from numpy.lib.stride_tricks import sliding_window_view

    densidade = sliding_window_view(np.pad(grade, 4), (9, 9)).sum(axis=(2, 3))
    i, j = np.unravel_index(int(np.argmax(densidade)), densidade.shape)
    regiao = np.zeros_like(grade)
    regiao[i, j] = True
    while True:
        cresce = regiao.copy()
        cresce[1:] |= regiao[:-1]
        cresce[:-1] |= regiao[1:]
        cresce[:, 1:] |= regiao[:, :-1]
        cresce[:, :-1] |= regiao[:, 1:]
        cresce &= grade
        if np.array_equal(cresce, regiao):
            break
        regiao = cresce
    # Uma célula de folga em volta, para a borda macia (cabelo) não virar degrau.
    folga = regiao.copy()
    folga[1:] |= regiao[:-1]
    folga[:-1] |= regiao[1:]
    folga[:, 1:] |= regiao[:, :-1]
    folga[:, :-1] |= regiao[:, 1:]
    manter = np.repeat(np.repeat(folga, passo, axis=0), passo, axis=1)[:altura, :largura]
    return alfa * manter


def caixas(alfa: np.ndarray) -> tuple[Caixa | None, Caixa | None]:
    """A caixa da pessoa e uma estimativa da do rosto, ou ``(None, None)`` sem pessoa."""
    altura, largura = alfa.shape
    dentro = alfa > LIMIAR
    if dentro.mean() < AREA_MINIMA:
        return None, None
    linhas = np.flatnonzero(dentro.any(axis=1))
    colunas = np.flatnonzero(dentro.any(axis=0))
    y0, y1 = int(linhas[0]), int(linhas[-1]) + 1
    x0, x1 = int(colunas[0]), int(colunas[-1]) + 1
    pessoa = Caixa(x0 / largura, y0 / altura, x1 / largura, y1 / altura)
    # O rosto: de cima da silhueta até onde ela alarga nos ombros. A cabeça (com o fone)
    # é bem mais estreita que os ombros; sem ombros no quadro, vale a faixa de cima.
    larguras = dentro.sum(axis=1)
    minimo = max(2, round(0.04 * altura))
    fim, maior = None, 0
    for y in range(y0, y1):
        if y - y0 > minimo and maior and larguras[y] > OMBROS * maior:
            fim = y
            break
        maior = max(maior, int(larguras[y]))
    fim = min(fim or y0 + round((y1 - y0) * FAIXA_DO_ROSTO), y0 + (y1 - y0) // 2)
    fim = max(fim, y0 + 1)
    no_topo = np.flatnonzero(dentro[y0:fim].any(axis=0))
    rx0, rx1 = int(no_topo[0]), int(no_topo[-1]) + 1
    rosto = Caixa(rx0 / largura, y0 / altura, rx1 / largura, fim / altura)
    return pessoa, rosto


def recortar(matriz: np.ndarray) -> Recorte:
    alfa = so_a_pessoa(mascara(matriz))
    pessoa, rosto = caixas(alfa)
    return Recorte(alfa, pessoa, rosto)


def png(matriz: np.ndarray, alfa: np.ndarray, largura: int | None = None) -> bytes:
    """O quadro com o fundo transparente, em PNG."""
    rgba = np.dstack([matriz[..., :3], (np.clip(alfa, 0, 1) * 255).astype(np.uint8)])
    img = Image.fromarray(rgba, "RGBA")
    if largura and img.width > largura:
        img = img.resize((largura, round(img.height * largura / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False, compress_level=6)
    return buf.getvalue()


__all__ = ["ARQUIVO", "REPOSITORIO", "REVISAO", "TAMANHO", "Caixa", "Recorte", "caixas",
           "mascara", "modelo_baixado", "png", "preparar", "recortar", "so_a_pessoa",
           "tamanho_de_entrada"]
