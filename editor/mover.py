"""
A pessoa que muda de lugar no vídeo.

Nos trechos que o plano escolhe (``Plano.movimentos``, sempre começando num corte), a
pessoa é recortada quadro a quadro pelo MODNet e vai para um lado, para cima, para
baixo, para perto ou para longe. Atrás dela fica o próprio vídeo, desfocado e sem ela,
ou uma cor. Fora desses trechos, o quadro é o de sempre.

Três escolhas que vieram de olhar os quadros:

- **O recorte roda a 320 px no lado curto.** A 512, o custo por quadro mais que dobra, e
  no tamanho do vídeo a borda quase não muda. O alfa é suavizado entre um quadro e o
  seguinte, para a borda não tremer.
- **O fundo de vídeo é o quadro sem a pessoa.** Só desfocar deixava um fantasma dela atrás
  dela mesma. A região da pessoa é preenchida com as cores em volta (uma convolução
  normalizada), num quadro pequeno, onde isso custa quase nada.
- **Onde o quadro original cortava a pessoa** (o braço na borda, o tronco embaixo), ela
  some aos poucos quando essa borda entra na tela. Uma reta atravessando o ombro
  denunciava o recorte, como na thumbnail.

A entrada e a saída de cada trecho também são suaves: a pessoa desliza em
``TRANSICAO_S``. O fundo troca do quadro normal para o desfocado só no primeiro pedaço do
caminho (``TROCA_DO_FUNDO``): o quadro normal tem a pessoa no lugar antigo, e misturá-lo
com ela já andando deixava duas pessoas na tela.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

from editor import recorte
from editor.plano import Movimento, Plano

logger = logging.getLogger(__name__)

#: O lado curto que vai para o MODNet.
LADO_DO_RECORTE = 320
#: O MODNet roda num quadro do vídeo original a cada tantos; nos outros vale o último
#: recorte. É a maior parte do custo, e com a suavização a diferença não aparece.
RECORTAR_A_CADA = 2
#: O peso do alfa anterior: a borda fica estável sem atrasar o movimento.
SUAVIZAR = 0.4
#: Quanto a pessoa leva para chegar e para voltar, quando não volta num corte.
TRANSICAO_S = 0.25
#: A fração do caminho em que o fundo troca do quadro normal para o desfocado.
TROCA_DO_FUNDO = 0.2
#: Quanto da luz o fundo de vídeo mantém.
ESCURECER = 0.6
#: Onde o quadro original cortava a pessoa, quanto dela some aos poucos: nos lados, uma
#: fração da largura; em cima e embaixo, da altura.
SOME_DO_LADO = 0.14
SOME_EM_CIMA = 0.06
SOME_EMBAIXO = 0.18
#: A pessoa toca uma borda se mais que esta fração dela é pessoa.
TOCA = 0.02
#: O alfa passa por uma curva: abaixo do primeiro valor some, acima do segundo fica
#: inteiro. O MODNet dá meio alfa para o tampo da mesa perto das mãos, e numa cor lisa
#: isso aparecia como manchas escuras embaixo da pessoa.
ALFA_SOME, ALFA_INTEIRO = 0.2, 0.8
#: Com fundo de cor, a parte de baixo da pessoa (mãos, mesa, pé do microfone) sempre some
#: aos poucos nesta fração da altura: é onde o recorte erra, e a cor lisa não perdoa.
SOME_EMBAIXO_NA_COR = 0.22
#: O fundo de vídeo é calculado neste divisor do tamanho. O preenchimento busca cor a
#: duas distâncias, em fração do lado maior: perto, para o contorno; longe, para o meio
#: de um tronco que ocupa a largura toda.
REDUCAO = 8
RAIO_DO_FUNDO = 0.09
RAIO_LONGE = 0.3

#: As cores da thumbnail (web/src/thumb/Thumb.tsx, PALETA).
CORES = {
    "amarelo": (255, 212, 0), "rosa": (255, 61, 127), "ciano": (0, 194, 255),
    "lima": (155, 225, 93), "laranja": (255, 122, 0), "roxo": (179, 107, 255),
    "vermelho": (255, 45, 45),
}


@dataclass(frozen=True)
class Transformacao:
    """O quadro da pessoa vai para ``escala * ponto + (dx, dy)``, em pixels da saída."""

    escala: float
    dx: float
    dy: float

    def em(self, e: float) -> Transformacao:
        """A transformação a uma fração ``e`` do caminho, partindo de onde ela estava."""
        return Transformacao(1 + (self.escala - 1) * e, self.dx * e, self.dy * e)

    def empurrada(self, extra: float, cx: float, cy: float) -> Transformacao:
        """Mais ``extra`` de tamanho, em volta do ponto (cx, cy) da saída: o empurrão do
        adesivo, que no quadro normal é um zoom."""
        k = 1 + extra
        return Transformacao(self.escala * k, self.dx * k - extra * cx,
                             self.dy * k - extra * cy)

    def quase_parada(self, largura: int, altura: int) -> bool:
        return (abs(self.escala - 1) < 0.04 and abs(self.dx) < 0.03 * largura
                and abs(self.dy) < 0.03 * altura)


def suave(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def alvo(posicao: str, pessoa: recorte.Caixa, rosto: recorte.Caixa, largura: int,
         altura: int, *, vertical: bool) -> Transformacao:
    """Para onde a pessoa vai em cada posição.

    O rosto é a referência: perto e longe crescem e encolhem em volta dele, os lados e o
    alto levam ele para lá. Se a pessoa encosta na borda de baixo, ela continua
    encostada (senão o tronco acabaria no meio da tela); em cima, ela não tem como, e o
    tronco some aos poucos.
    """
    W, H = float(largura), float(altura)
    fx = (rosto.x0 + rosto.x1) / 2 * W
    fy = (rosto.y0 + rosto.y1) / 2 * H
    encostada = pessoa.y1 >= 0.97

    def no_chao(s: float) -> float:
        return H - s * H if encostada else fy - s * fy

    if posicao == "perto":
        s = 1.3
        return Transformacao(s, fx - s * fx, fy - s * fy)
    if posicao == "longe":
        s = 0.72
        return Transformacao(s, W / 2 - s * fx, no_chao(s))
    if posicao in ("esquerda", "direita"):
        s = 0.86
        destino = (0.34 if vertical else 0.3) * W
        if posicao == "direita":
            destino = W - destino
        return Transformacao(s, destino - s * fx, no_chao(s))
    if posicao == "cima":
        s = 0.74
        return Transformacao(s, W / 2 - s * fx, 0.26 * H - s * fy)
    if posicao == "baixo":
        # Mais baixo, mas com o rosto longe da legenda.
        return Transformacao(1.0, W / 2 - fx, max(0.0, min(0.16 * H, 0.58 * H - fy)))
    raise ValueError(f"posição desconhecida: {posicao}")


def bordas_tocadas(alfa: np.ndarray) -> dict[str, bool]:
    """As bordas do quadro original em que a pessoa encosta (onde ela vinha cortada)."""
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


def expostas(t: Transformacao, largura: int, altura: int) -> dict[str, bool]:
    """As bordas do quadro original que essa transformação traz para dentro da tela."""
    return {"esquerda": t.dx > 0.5, "direita": t.dx + t.escala * largura < largura - 0.5,
            "topo": t.dy > 0.5, "baixo": t.dy + t.escala * altura < altura - 0.5}


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


def fundo_sem_a_pessoa(img: Image.Image, alfa: np.ndarray, largura: int, altura: int
                       ) -> Image.Image:
    """O quadro desfocado e escurecido, com a região da pessoa preenchida pelas cores em
    volta dela."""
    ls, hs = max(8, largura // REDUCAO), max(8, altura // REDUCAO)
    pequeno = np.asarray(img.resize((ls, hs), Image.BILINEAR), dtype=np.float32)
    a = np.asarray(Image.fromarray((np.clip(alfa, 0, 1) * 255).astype(np.uint8))
                   .resize((ls, hs), Image.BILINEAR), dtype=np.float32) / 255.0
    # A borda macia da pessoa conta como pessoa: senão o cabelo mancha o fundo.
    peso = np.clip(1.0 - a * 1.6, 0.0, 1.0)
    lado = max(ls, hs)

    def preencher(raio: float, minimo: float) -> tuple[np.ndarray, np.ndarray]:
        soma = borrar(pequeno * peso[..., None], raio)
        quanto = borrar(peso, raio)
        cor = soma / np.maximum(quanto, 1e-4)[..., None]
        return cor, np.clip(quanto / minimo, 0.0, 1.0)[..., None]

    perto, c_perto = preencher(lado * RAIO_DO_FUNDO, 0.12)
    longe, c_longe = preencher(lado * RAIO_LONGE, 0.04)
    # Onde nem de longe há fundo (a pessoa ocupa o quadro todo), vale o quadro só borrado.
    simples = borrar(pequeno, lado * RAIO_DO_FUNDO)
    fundo = perto * c_perto + (longe * c_longe + simples * (1 - c_longe)) * (1 - c_perto)
    fundo *= ESCURECER
    return Image.fromarray(np.clip(fundo, 0, 255).astype(np.uint8)).resize(
        (largura, altura), Image.BILINEAR)


def fundo_de_cor(cor: str, largura: int, altura: int) -> Image.Image:
    """Um gradiente da cor, mais claro atrás do rosto e escuro nas bordas."""
    base = np.array(CORES[cor], dtype=np.float32)
    claro = base + (255 - base) * 0.15
    escuro = base * 0.4
    ls, hs = max(8, largura // REDUCAO), max(8, altura // REDUCAO)
    yy, xx = np.mgrid[0:hs, 0:ls].astype(np.float32)
    d = np.hypot((xx + 0.5) / ls - 0.5, ((yy + 0.5) / hs - 0.4) * hs / ls)
    d = np.clip(d / (0.75 * max(1.0, hs / ls)), 0.0, 1.0)[..., None]
    meio = np.clip(d / 0.45, 0, 1)
    fim = np.clip((d - 0.45) / 0.55, 0, 1)
    cor_ = claro * (1 - meio) + base * meio
    cor_ = cor_ * (1 - fim) + escuro * fim
    return Image.fromarray(np.clip(cor_, 0, 255).astype(np.uint8)).resize(
        (largura, altura), Image.BILINEAR)


def colar(tela: Image.Image, pessoa: Image.Image, tr: Transformacao) -> None:
    """Põe a pessoa (RGBA, do tamanho da tela) na tela, já transformada.

    Só a parte que cai dentro da tela é redimensionada: um ``resize`` com ``box`` em
    frações de pixel, que custa metade de uma transformação afim do quadro inteiro e
    mantém o deslize sem degraus."""
    largura, altura = tela.size
    s = tr.escala
    x0, y0 = max(0.0, tr.dx), max(0.0, tr.dy)
    x1 = min(float(largura), tr.dx + s * pessoa.width)
    y1 = min(float(altura), tr.dy + s * pessoa.height)
    ox0, oy0 = int(np.floor(x0)), int(np.floor(y0))
    ox1, oy1 = int(np.ceil(x1)), int(np.ceil(y1))
    if ox1 - ox0 < 1 or oy1 - oy0 < 1:
        return
    caixa = (min(max((ox0 - tr.dx) / s, 0.0), pessoa.width),
             min(max((oy0 - tr.dy) / s, 0.0), pessoa.height),
             min(max((ox1 - tr.dx) / s, 0.0), pessoa.width),
             min(max((oy1 - tr.dy) / s, 0.0), pessoa.height))
    parte = pessoa.resize((ox1 - ox0, oy1 - oy0), Image.BILINEAR, box=caixa)
    tela.alpha_composite(parte, dest=(ox0, oy0))


@dataclass
class _Trecho:
    movimento: Movimento
    transformacao: Transformacao | None
    rampa: np.ndarray | None
    rosto: tuple[float, float]


class Pessoa:
    """Desenha os quadros dos trechos em que a pessoa sai do lugar.

    Os quadros chegam em ordem. O recorte de cada quadro do vídeo original é feito uma
    vez, mesmo que ele vire mais de um quadro na saída.
    """

    def __init__(self, plano: Plano, largura: int, altura: int, *, fundo: str = "video",
                 cor: str = "roxo"):
        self.movimentos = sorted(plano.movimentos, key=lambda m: m.inicio)
        self.vertical = plano.vertical
        self.largura, self.altura = largura, altura
        self.fundo = fundo
        self._cor = fundo_de_cor(cor, largura, altura) if fundo == "cor" else None
        self._trecho: _Trecho | None = None
        self._origem: np.ndarray | None = None
        self._alfa: np.ndarray | None = None
        self._fundo: Image.Image | None = None
        self._vistos = 0
        #: Quantos quadros passaram pelo MODNet (para medir o custo).
        self.recortados = 0

    def em(self, t: float) -> tuple[Movimento, float] | None:
        """O movimento em andamento em ``t`` e quanto do caminho a pessoa já fez."""
        for m in self.movimentos:
            if m.inicio <= t < m.fim:
                e = suave((t - m.inicio) / TRANSICAO_S)
                if not m.volta_no_corte:
                    e = min(e, suave((m.fim - t) / TRANSICAO_S))
                return m, e
            if m.inicio > t:
                break
        return None

    def lado_livre(self, t: float) -> int:
        """O lado da tela que a pessoa deixou livre (-1 esquerda, 1 direita, 0 nenhum)."""
        achado = self.em(t)
        if achado is None:
            return 0
        return {"esquerda": 1, "direita": -1}.get(achado[0].posicao, 0)

    def _recortar(self, matriz: np.ndarray, novo_trecho: bool) -> tuple[np.ndarray, bool]:
        """O alfa (pequeno) deste quadro do vídeo original, e se ele é novo."""
        if novo_trecho:
            self._vistos = 0
        elif matriz is self._origem and self._alfa is not None:
            return self._alfa, False
        self._vistos += 1
        self._origem = matriz
        if not novo_trecho and self._alfa is not None and (self._vistos - 1) % RECORTAR_A_CADA:
            return self._alfa, False
        bruto = recorte.mascara_pequena(matriz, LADO_DO_RECORTE)
        bruto = np.where(bruto < recorte.ALFA_MINIMO, 0.0, bruto).astype(np.float32)
        # A região (o que tira as manchas soltas da mesa) é refeita a cada recorte:
        # reaproveitada, ela cortava a mão que saía dela no meio de um gesto.
        regiao = recorte.regiao_da_pessoa(bruto)
        self.recortados += 1
        alfa = bruto if regiao is None else bruto * regiao
        if not novo_trecho and self._alfa is not None and self._alfa.shape == alfa.shape:
            alfa = SUAVIZAR * self._alfa + (1 - SUAVIZAR) * alfa
        self._alfa = alfa
        return alfa, True

    def _comecar(self, m: Movimento, alfa: np.ndarray) -> _Trecho:
        pessoa, rosto = recorte.caixas(alfa)
        if pessoa is None or rosto is None:
            logger.info("sem pessoa no começo do trecho de %.2f s: fica no lugar", m.inicio)
            return _Trecho(m, None, None, (0.0, 0.0))
        t = alvo(m.posicao, pessoa, rosto, self.largura, self.altura, vertical=self.vertical)
        if t.quase_parada(self.largura, self.altura):
            # O quadro já estava assim (o rosto lá embaixo, por exemplo): vai para perto.
            t = alvo("perto", pessoa, rosto, self.largura, self.altura,
                     vertical=self.vertical)
        lados = bordas_tocadas(alfa)
        expo = expostas(t, self.largura, self.altura)
        somem = {k: lados[k] and expo[k] for k in lados}
        embaixo = SOME_EMBAIXO
        if self._cor is not None:
            somem["baixo"] = True
            embaixo = max(SOME_EMBAIXO, SOME_EMBAIXO_NA_COR)
        r = rampa(*alfa.shape, somem, embaixo) if any(somem.values()) else None
        cx = (rosto.x0 + rosto.x1) / 2 * self.largura
        cy = (rosto.y0 + rosto.y1) / 2 * self.altura
        return _Trecho(m, t, r, (cx, cy))

    def quadro(self, matriz: np.ndarray, t: float, extra: float = 0.0) -> Image.Image | None:
        """O quadro composto em ``t``, ou ``None`` fora dos trechos (o quadro de sempre)."""
        achado = self.em(t)
        if achado is None:
            self._trecho = None
            return None
        m, e = achado
        novo = self._trecho is None or self._trecho.movimento is not m
        alfa, alfa_novo = self._recortar(matriz, novo)
        if novo:
            self._trecho = self._comecar(m, alfa)
        trecho = self._trecho
        if trecho.transformacao is None:
            return None
        img = Image.fromarray(matriz)
        if img.size != (self.largura, self.altura):
            img = img.resize((self.largura, self.altura), Image.BILINEAR)
        if self._cor is not None:
            fundo = self._cor
        else:
            # O fundo borrado muda devagar: é refeito junto com o recorte.
            if alfa_novo or self._fundo is None:
                self._fundo = fundo_sem_a_pessoa(img, alfa, self.largura, self.altura)
            fundo = self._fundo
        troca = min(1.0, e / TROCA_DO_FUNDO)
        if troca < 1.0:
            fundo = Image.blend(img, fundo, troca)
        a = curva_do_alfa(alfa)
        if trecho.rampa is not None:
            a = a * (1 - e * (1 - trecho.rampa))
        mascara_ = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).resize(
            (self.largura, self.altura), Image.BILINEAR)
        pessoa = img.copy()
        pessoa.putalpha(mascara_)
        tr = trecho.transformacao.em(e)
        if extra > 0:
            cx, cy = trecho.rosto
            tr = tr.empurrada(extra, tr.escala * cx + tr.dx, tr.escala * cy + tr.dy)
        tela = fundo.convert("RGBA")
        colar(tela, pessoa, tr)
        return tela.convert("RGB")


__all__ = ["CORES", "LADO_DO_RECORTE", "Pessoa", "Transformacao", "alvo", "bordas_tocadas",
           "colar", "expostas", "fundo_de_cor", "fundo_sem_a_pessoa", "rampa"]
