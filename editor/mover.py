"""
As peças para mover uma camada (a pessoa ou o personagem) por cima de um fundo.

Elas vieram do "Mover a pessoa" de um vídeo só, que recortava a pessoa e apagava ela do
próprio quadro. Esse modo saiu em 03/10/2026, a pedido do dono: agora o fundo vem num
vídeo separado (``editor/montagem.py``), e daqui ficaram as partes que valem para
qualquer camada:

- **O recorte quadro a quadro** (``RecorteContinuo``): o MODNet a 320 px, num quadro
  sim, num não, com o alfa suavizado entre eles. A 512 px o custo mais que dobrava, e no
  tamanho do vídeo a borda quase não mudava.
- **A transformação** (``Transformacao``): tamanho e lugar da camada na tela, com o
  deslize de um lugar para outro e o empurrão do adesivo.
- **Onde a pessoa vinha cortada** (o busto embaixo, o braço na borda): ela some aos
  poucos quando essa borda entra na tela. Uma reta atravessando o ombro denunciava o
  recorte, como na thumbnail.
- **O borrão** e o **colar** com frações de pixel, sem degraus no deslize.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

from editor import recorte

logger = logging.getLogger(__name__)

#: O lado curto que vai para o MODNet.
LADO_DO_RECORTE = 320
#: O MODNet roda num quadro do vídeo a cada tantos; nos outros vale o último recorte. É a
#: maior parte do custo, e com a suavização a diferença não aparece.
RECORTAR_A_CADA = 2
#: O peso do alfa anterior: a borda fica estável sem atrasar o movimento.
SUAVIZAR = 0.4
#: Quanto a camada leva para ir de um lugar a outro.
TRANSICAO_S = 0.25
#: Onde a pessoa vinha cortada, quanto dela some aos poucos: nos lados, uma fração da
#: largura; em cima e embaixo, da altura.
SOME_DO_LADO = 0.14
SOME_EM_CIMA = 0.06
SOME_EMBAIXO = 0.18
#: A pessoa toca uma borda se mais que esta fração dela é pessoa.
TOCA = 0.02
#: O alfa passa por uma curva: abaixo do primeiro valor some, acima do segundo fica
#: inteiro. O MODNet dá meio alfa para o tampo da mesa perto das mãos, e sobre outro fundo
#: isso aparecia como manchas escuras embaixo da pessoa.
ALFA_SOME, ALFA_INTEIRO = 0.2, 0.8


@dataclass(frozen=True)
class Transformacao:
    """A camada vai para ``escala * ponto + (dx, dy)``, em pixels da tela."""

    escala: float
    dx: float
    dy: float

    def ate(self, outra: Transformacao, e: float) -> Transformacao:
        """O caminho daqui até ``outra``, na fração ``e``."""
        return Transformacao(self.escala + (outra.escala - self.escala) * e,
                             self.dx + (outra.dx - self.dx) * e,
                             self.dy + (outra.dy - self.dy) * e)

    def ponto(self, x: float, y: float) -> tuple[float, float]:
        """Onde o ponto (x, y) da camada cai na tela."""
        return self.escala * x + self.dx, self.escala * y + self.dy

    def empurrada(self, extra: float, cx: float, cy: float) -> Transformacao:
        """Mais ``extra`` de tamanho, em volta do ponto (cx, cy) da tela: o empurrão do
        adesivo, que no quadro normal é um zoom."""
        k = 1 + extra
        return Transformacao(self.escala * k, self.dx * k - extra * cx,
                             self.dy * k - extra * cy)

    def perto_de(self, outra: Transformacao, largura: int, altura: int) -> bool:
        """Se as duas deixam a camada quase no mesmo lugar e tamanho."""
        return (abs(self.escala - outra.escala) < 0.04 * max(self.escala, 1e-6)
                and abs(self.dx - outra.dx) < 0.03 * largura
                and abs(self.dy - outra.dy) < 0.03 * altura)


def suave(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def bordas_tocadas(alfa: np.ndarray) -> dict[str, bool]:
    """As bordas do quadro da camada em que a pessoa encosta (onde ela vinha cortada)."""
    a = alfa > recorte.LIMIAR
    return {"esquerda": bool(a[:, 0].mean() > TOCA), "direita": bool(a[:, -1].mean() > TOCA),
            "topo": bool(a[0].mean() > TOCA), "baixo": bool(a[-1].mean() > TOCA)}


def curva_do_alfa(alfa: np.ndarray) -> np.ndarray:
    v = np.clip((alfa - ALFA_SOME) / (ALFA_INTEIRO - ALFA_SOME), 0.0, 1.0)
    return v * v * (3 - 2 * v)


def rampa(altura: int, largura: int, lados: dict[str, bool],
          embaixo: float = SOME_EMBAIXO) -> np.ndarray:
    """O quanto da pessoa fica em cada ponto (1 = toda), sumindo nos lados pedidos."""
    r = np.ones((altura, largura), np.float32)
    x = (np.arange(largura, dtype=np.float32) + 0.5) / largura
    y = (np.arange(altura, dtype=np.float32) + 0.5) / altura

    def curva(v: np.ndarray, largura_da_rampa: float) -> np.ndarray:
        v = np.clip(v / largura_da_rampa, 0.0, 1.0)
        return v * v * (3 - 2 * v)

    if lados.get("esquerda"):
        r *= curva(x, SOME_DO_LADO)[None, :]
    if lados.get("direita"):
        r *= curva(1 - x, SOME_DO_LADO)[None, :]
    if lados.get("topo"):
        r *= curva(y, SOME_EM_CIMA)[:, None]
    if lados.get("baixo"):
        r *= curva(1 - y, embaixo)[:, None]
    return r


def expostas(t: Transformacao, largura: int, altura: int, largura_da_camada: int | None = None,
             altura_da_camada: int | None = None) -> dict[str, bool]:
    """As bordas do quadro da camada que essa transformação traz para dentro da tela."""
    lc = largura if largura_da_camada is None else largura_da_camada
    ac = altura if altura_da_camada is None else altura_da_camada
    return {"esquerda": t.dx > 0.5, "direita": t.dx + t.escala * lc < largura - 0.5,
            "topo": t.dy > 0.5, "baixo": t.dy + t.escala * ac < altura - 0.5}


def _media(x: np.ndarray, r: int, eixo: int) -> np.ndarray:
    """Média móvel de largura 2r+1 ao longo de um eixo, com a borda repetida."""
    if r <= 0:
        return x
    pad = [(0, 0)] * x.ndim
    pad[eixo] = (r + 1, r)
    c = np.cumsum(np.pad(x, pad, mode="edge"), axis=eixo, dtype=np.float64)
    n = x.shape[eixo]
    alto = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=eixo)
    baixo = np.take(c, np.arange(0, n), axis=eixo)
    return ((alto - baixo) / (2 * r + 1)).astype(np.float32)


def borrar(x: np.ndarray, raio: float) -> np.ndarray:
    """Três passadas de média, que dão quase uma gaussiana."""
    r = max(1, round(raio / 1.7))
    for _ in range(3):
        x = _media(_media(x, r, 0), r, 1)
    return x


def colar(tela: Image.Image, camada: Image.Image, tr: Transformacao) -> None:
    """Põe a camada (RGBA) na tela (RGBA), já transformada.

    Só a parte que cai dentro da tela é redimensionada: um ``resize`` com ``box`` em
    frações de pixel, que custa metade de uma transformação afim do quadro inteiro e
    mantém o deslize sem degraus."""
    largura, altura = tela.size
    s = tr.escala
    x0, y0 = max(0.0, tr.dx), max(0.0, tr.dy)
    x1 = min(float(largura), tr.dx + s * camada.width)
    y1 = min(float(altura), tr.dy + s * camada.height)
    ox0, oy0 = int(np.floor(x0)), int(np.floor(y0))
    ox1, oy1 = int(np.ceil(x1)), int(np.ceil(y1))
    if ox1 - ox0 < 1 or oy1 - oy0 < 1:
        return
    caixa = (min(max((ox0 - tr.dx) / s, 0.0), camada.width),
             min(max((oy0 - tr.dy) / s, 0.0), camada.height),
             min(max((ox1 - tr.dx) / s, 0.0), camada.width),
             min(max((oy1 - tr.dy) / s, 0.0), camada.height))
    parte = camada.resize((ox1 - ox0, oy1 - oy0), Image.BILINEAR, box=caixa)
    tela.alpha_composite(parte, dest=(ox0, oy0))


class RecorteContinuo:
    """O MODNet num vídeo inteiro, quadro a quadro.

    Os quadros chegam em ordem. Um quadro repetido (o vídeo da pessoa com menos quadros
    por segundo que a saída) não é recortado de novo. A região da pessoa, que tira as
    manchas soltas da mesa, é refeita a cada recorte: reaproveitada, ela cortava a mão
    que saía dela no meio de um gesto.
    """

    def __init__(self, lado: int = LADO_DO_RECORTE, a_cada: int = RECORTAR_A_CADA,
                 suavizar: float = SUAVIZAR):
        self.lado, self.a_cada, self.suavizar = lado, a_cada, suavizar
        self._origem: np.ndarray | None = None
        self._alfa: np.ndarray | None = None
        self._vistos = 0
        #: Quantos quadros passaram pelo MODNet (para medir o custo).
        self.recortados = 0

    def alfa(self, matriz: np.ndarray) -> np.ndarray:
        """O alfa do quadro, no tamanho do modelo (lado curto perto de ``lado``)."""
        if matriz is self._origem and self._alfa is not None:
            return self._alfa
        self._origem = matriz
        self._vistos += 1
        if self._alfa is not None and (self._vistos - 1) % self.a_cada:
            return self._alfa
        bruto = recorte.mascara_pequena(matriz, self.lado)
        bruto = np.where(bruto < recorte.ALFA_MINIMO, 0.0, bruto).astype(np.float32)
        regiao = recorte.regiao_da_pessoa(bruto)
        self.recortados += 1
        alfa = bruto if regiao is None else bruto * regiao
        if self._alfa is not None and self._alfa.shape == alfa.shape:
            alfa = self.suavizar * self._alfa + (1 - self.suavizar) * alfa
        self._alfa = alfa
        return alfa


__all__ = ["LADO_DO_RECORTE", "TRANSICAO_S", "RecorteContinuo", "Transformacao",
           "bordas_tocadas", "borrar", "colar", "curva_do_alfa", "expostas", "rampa", "suave"]
