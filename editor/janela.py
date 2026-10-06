"""
A janela e a câmera: o jeito do vídeo de referência (a direção, a janela e o mascote
dele, feitos no Remotion), em qualquer formato.

- **A janela:** a cena num quadro 16:9 (o "palco"), com ela mesma desfocada e escurecida
  cobrindo o resto da tela. No plano **padrão**, a janela fica na largura toda e o
  personagem, grande, em pé na borda de cima dela; no **foco**, ela cresce e o
  personagem diminui num canto. Deitado, a janela é a tela inteira, e o foco é só a
  câmera empurrando.
- **A câmera:** cobre a janela, empurra (zoom) e mira um ponto do palco sem nunca mostrar
  a borda dele. Cada mudança de plano leva 11 quadros, na curva do Remotion, e parte de
  onde a anterior estava: deixas mais perto que isso nunca dão pulo.
- **O personagem:** dá um pulinho quando troca de lugar e balança enquanto fala.
- **O diretor:** decide os planos por regras, igual a cada vez: num cartão do palco, o
  padrão (ele aparece inteiro) e, no momento forte, o foco com a câmera mirando nele; nos
  cartões da janela, o foco; sem cartão, os zooms de ênfase do plano viram foco e padrão.

As medidas são as do chat, num quadro em pé de 1080 × 1920, e escalam com ele.
"""
from __future__ import annotations

import functools
import math
from collections.abc import Sequence
from dataclasses import dataclass, fields

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from editor import animacao as a
from editor import cartoes as cartoes_mod

#: O palco de referência (1080 × 608, o 16:9 em que as medidas foram feitas).
PALCO = (1080, 608)
#: Quanto o personagem esconde atrás da borda da janela (o busto "entra" nela).
ENFIADO = 0.05
#: O pulinho na troca de lugar e o balanço da fala, em pixels de um quadro de 1080.
PULO = 45
GIRO_DO_PULO = 6
BALANCO = 3
#: As faixas coloridas em cima e embaixo da janela (roxo → rosa → laranja).
FAIXA = 6
DEGRADE = ((138, 63, 252), (255, 77, 157), (255, 159, 67))
#: O empurrão de um ponto forte, o do destaque e o da linha falada de um quadro.
ZOOM_FORTE = 1.0
ZOOM_DO_DESTAQUE = 1.3
ZOOM_DA_LINHA = 1.08
#: Planos mais perto que isto do anterior são descartados (o de mais prioridade fica).
PLANO_MINIMO_S = 0.6
#: Depois do momento forte, a câmera volta ao padrão.
VOLTA_DO_FORTE_S = 1.6


@dataclass(frozen=True)
class Estado:
    """Onde está tudo num instante: a janela, a legenda, a câmera e o personagem."""

    x: float                 # a janela
    y: float
    largura: float
    altura: float
    legenda: float           # a linha de base da legenda
    zoom: float              # o empurrão extra da câmera
    fx: float                # o ponto mirado, no palco de referência
    fy: float
    cx: float                # o personagem: o centro, o tamanho e onde ele pisa
    tamanho: float
    piso: float


def misturar(a_: Estado, b: Estado, t: float) -> Estado:
    return Estado(*(getattr(a_, f.name) + (getattr(b, f.name) - getattr(a_, f.name)) * t
                    for f in fields(Estado)))


@dataclass(frozen=True)
class Plano:
    """Um plano de câmera, a partir do instante ``t``."""

    t: float
    janela: str = "padrao"           # "padrao" ou "foco"
    lugar: str = "centro"            # "centro", "esquerda" ou "direita"
    zoom: float = 1.0
    foco: tuple[float, float] | None = None
    prioridade: int = 0


class Geometria:
    """As medidas da janela, da legenda e do personagem num quadro ``largura`` ×
    ``altura``."""

    def __init__(self, largura: int, altura: int):
        self.largura, self.altura = largura, altura
        razao = altura / largura
        self.formato = "em_pe" if razao > 1.2 else "quadrado" if razao > 0.8 else "deitado"
        kx, ky = largura / 1080, altura / (1920 if self.formato == "em_pe" else 1080)
        self.k = kx
        if self.formato == "em_pe":
            # As medidas do chat: a janela de 608 em 640, ou de 960 em 400 no foco.
            self.janelas = {"padrao": (0, 640 * ky, largura, 608 * ky, 1290 * ky + 140 * ky),
                            "foco": (0, 400 * ky, largura, 960 * ky, 1385 * ky + 140 * ky)}
            self.lugares = {"centro": (540 * kx, 600 * kx), "esquerda": (220 * kx, 400 * kx),
                            "direita": (860 * kx, 400 * kx)}
        elif self.formato == "quadrado":
            larg = largura * 0.92
            self.janelas = {"padrao": ((largura - larg) / 2, 0.34 * altura, larg,
                                       larg * 9 / 16, 0.34 * altura + larg * 9 / 16 + 120 * ky),
                            "foco": (0, 0.17 * altura, largura, 0.66 * altura,
                                     0.83 * altura + 120 * ky)}
            self.lugares = {"centro": (0.5 * largura, 0.34 * altura),
                            "esquerda": (0.17 * largura, 0.18 * altura),
                            "direita": (0.83 * largura, 0.18 * altura)}
        else:
            base = altura * 0.93
            self.janelas = {"padrao": (0, 0, largura, altura, base),
                            "foco": (0, 0, largura, altura, base)}
            self.lugares = {"centro": (0.82 * largura, 0.62 * altura),
                            "esquerda": (0.15 * largura, 0.45 * altura),
                            "direita": (0.85 * largura, 0.45 * altura)}
        # O palco: o 16:9 na largura da janela padrão.
        _, _, lp, _, _ = self.janelas["padrao"]
        self.palco = (round(lp), round(lp * 9 / 16))

    def estado(self, plano: Plano) -> Estado:
        x, y, w, h, legenda = self.janelas[plano.janela]
        cx, tamanho = self.lugares[plano.lugar]
        fx, fy = plano.foco or (PALCO[0] / 2, PALCO[1] / 2)
        piso = self.altura if self.formato == "deitado" else y + tamanho * ENFIADO
        return Estado(x, y, w, h, legenda, plano.zoom, fx, fy, cx, tamanho, piso)


# ── a direção ────────────────────────────────────────────────────────────


class Direcao:
    """Os planos ao longo do vídeo, com as transições."""

    def __init__(self, planos: Sequence[Plano], geometria: Geometria):
        self.planos = sorted(planos, key=lambda p: p.t) or [Plano(0.0)]
        if self.planos[0].t > 0:
            self.planos.insert(0, Plano(0.0))
        self.geo = geometria

    def em(self, t: float) -> tuple[Estado, float]:
        """O estado em ``t`` e o arco do pulinho (0 a 1) se o personagem está trocando de
        lugar. Cada transição parte de onde a anterior tinha chegado."""
        de = para = self.geo.estado(self.planos[0])
        comeco, trocando = 0.0, False
        for i in range(1, len(self.planos)):
            p = self.planos[i]
            if p.t > t:
                break
            andou = a.CAMERA(min(1.0, (p.t - comeco) / a.TRANSICAO))
            de = misturar(de, para, andou)
            para = self.geo.estado(p)
            trocando = p.lugar != self.planos[i - 1].lugar
            comeco = p.t
        bruto = min(1.0, max(0.0, (t - comeco) / a.TRANSICAO))
        estado = misturar(de, para, a.CAMERA(bruto))
        pulo = math.sin(bruto * math.pi) if trocando and bruto < 1 else 0.0
        return estado, pulo


def dirigir(duracao: float, cartoes: Sequence[cartoes_mod.Cartao],
            zooms: Sequence[tuple[float, float]], *, deitado: bool = False) -> list[Plano]:
    """Os planos do vídeo, por regras (as do vídeo do chat):

    - o começo é foco, com o personagem à esquerda;
    - um cartão do palco (carimbo, quadro, destaque) entra no padrão, inteiro; no momento
      forte, a câmera empurra até ele (foco, ou zoom no destaque) e depois volta;
    - as linhas de um quadro trocam o personagem de lado; a última leva um zoom leve;
    - um cartão da janela (lista, enquete) pede o foco, e cada item troca o lado;
    - sem cartão, os zooms de ênfase do plano viram foco (com o personagem num canto) e
      padrão;
    - o fim é padrão, com o personagem no centro.
    """
    planos: list[Plano] = [Plano(0.0, "foco", "esquerda", prioridade=3)]
    lado = ["direita"]

    def canto() -> str:
        lado[0] = "esquerda" if lado[0] == "direita" else "direita"
        return lado[0]

    ocupado: list[tuple[float, float]] = []
    for c in cartoes:
        ocupado.append((c.inicio - 0.8, c.fim))
        if c.modelo in ("carimbo", "quadro", "destaque"):
            planos.append(Plano(c.inicio, "padrao", "centro", prioridade=2))
            forte = cartoes_mod.ponto_forte(c)
            if forte is not None:
                t, ponto = forte
                if c.modelo == "destaque":
                    planos.append(Plano(t, "padrao", "centro", ZOOM_DO_DESTAQUE, ponto, 3))
                else:
                    planos.append(Plano(t, "foco", canto(), ZOOM_FORTE, ponto, 3))
                    volta = min(t + VOLTA_DO_FORTE_S, c.fim - 0.3)
                    if volta > t + PLANO_MINIMO_S:
                        planos.append(Plano(volta, "padrao", "centro", prioridade=2))
            if c.modelo == "quadro":
                n = len(c.itens)
                topo = 24 + (66 if c.texto else 20)
                altura = min(112, (560 - (topo - 24) - 24) / max(1, n))
                for j, item in enumerate(c.itens):
                    ponto = (540, 24 + topo + altura * (j + 0.5))
                    ultimo = j == n - 1
                    planos.append(Plano(item.em, "padrao", canto(),
                                        ZOOM_DA_LINHA if ultimo else 1.0,
                                        ponto if ultimo else None, 2))
        elif c.modelo in ("lista", "enquete"):
            planos.append(Plano(c.inicio, "foco", canto(), prioridade=2))
            for item in c.itens[1:]:
                planos.append(Plano(item.em, "foco", canto(), prioridade=1))
            if c.modelo == "enquete" and c.forte is not None:
                planos.append(Plano(c.forte, "foco", canto(), prioridade=1))
        elif c.modelo == "flash":
            planos.append(Plano(c.forte if c.forte is not None else c.inicio, "padrao",
                                "centro", prioridade=2))
    for t, nivel in zooms[1:]:
        if any(a0 <= t <= a1 for a0, a1 in ocupado):
            continue
        planos.append(Plano(t, "foco", canto(), prioridade=0) if nivel > 1.0
                      else Plano(t, "padrao", "centro", prioridade=0))
    if duracao > 4:
        planos.append(Plano(max(0.0, duracao - 2.0), "padrao", "centro", prioridade=1))
    if deitado:
        # Deitado, a janela não cresce: o foco é um empurrão leve da câmera.
        planos = [Plano(p.t, p.janela, p.lugar, p.zoom * (1.12 if p.janela == "foco" else 1),
                        p.foco, p.prioridade) for p in planos]
    planos.sort(key=lambda p: (p.t, -p.prioridade))
    finais: list[Plano] = []
    for p in planos:
        if p.t >= duracao:
            continue
        if finais and p.t - finais[-1].t < PLANO_MINIMO_S:
            if p.prioridade > finais[-1].prioridade and len(finais) > 1:
                finais[-1] = p
            continue
        finais.append(p)
    return finais


# ── o desenho ────────────────────────────────────────────────────────────


def fundo_desfocado(cena: Image.Image, largura: int, altura: int) -> Image.Image:
    """A cena cobrindo a tela, desfocada, escurecida e mais saturada (``blur(30px)
    brightness(0.4) saturate(1.35)`` e escala de 1,15 no chat), feita num quadro pequeno."""
    ls, hs = max(8, largura // 8), max(8, altura // 8)
    s = max(ls / cena.width, hs / cena.height) * 1.15
    cw, ch = ls / s, hs / s
    x0, y0 = (cena.width - cw) / 2, (cena.height - ch) / 2
    pequeno = cena.convert("RGB").resize((ls, hs), Image.BILINEAR,
                                         box=(x0, y0, x0 + cw, y0 + ch))
    pequeno = pequeno.filter(ImageFilter.GaussianBlur(30 / 8 * largura / 1080))
    pequeno = ImageEnhance.Color(pequeno).enhance(1.35)
    pequeno = ImageEnhance.Brightness(pequeno).enhance(0.4)
    return pequeno.resize((largura, altura), Image.BILINEAR)


def camera(palco: Image.Image, estado: Estado, extra: float = 0.0) -> Image.Image:
    """O que a janela mostra do palco: cobre a janela, empurra e mira, sem mostrar a
    borda (``direcao.ts``)."""
    lp, ap = palco.size
    w, h = max(1, round(estado.largura)), max(1, round(estado.altura))
    escala = max(1.0, w / lp, h / ap) * estado.zoom * (1 + extra)
    fx, fy = estado.fx * lp / PALCO[0], estado.fy * ap / PALCO[1]
    x = min(0.0, max(w - lp * escala, w / 2 - fx * escala))
    y = min(0.0, max(h - ap * escala, h / 2 - fy * escala))
    caixa = (-x / escala, -y / escala, (-x + w) / escala, (-y + h) / escala)
    return palco.resize((w, h), Image.BILINEAR, box=caixa)


@functools.lru_cache(maxsize=8)
def _faixa(largura: int, altura: int) -> Image.Image:
    """A faixa em degradê (roxo → rosa a 45% → laranja) das bordas da janela."""
    x = np.linspace(0, 1, largura)[:, None]
    pontos, cores = [0.0, 0.45, 1.0], np.array(DEGRADE, np.float32)
    linha = np.stack([np.interp(x[:, 0], pontos, cores[:, c]) for c in range(3)], axis=1)
    rgb = np.repeat(linha[None, :, :], altura, axis=0).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, np.full((altura, largura), 255, np.uint8)]),
                           "RGBA")


@functools.lru_cache(maxsize=8)
def _sombra_da_borda(largura: int, altura: int, em_cima: bool) -> Image.Image:
    """A sombra em cima e embaixo da janela (``0 ±18px 60px rgba(0,0,0,0.55)``): escura
    junto dela, sumindo para longe."""
    perto = np.linspace(0, 1, altura)               # em cima: a janela está embaixo
    if not em_cima:
        perto = perto[::-1]
    alfa = np.repeat((140 * perto ** 2).astype(np.uint8)[:, None], largura, axis=1)
    preto = np.zeros((altura, largura, 3), np.uint8)
    return Image.fromarray(np.dstack([preto, alfa]), "RGBA")


class MontadorDeJanela:
    """Compõe cada quadro no jeito da janela: o fundo desfocado, o personagem, a janela
    com a câmera e os cartões. A legenda fica com o render, na linha que este devolve."""

    def __init__(self, largura: int, altura: int, *, fundo, fundo_na_saida: bool,
                 camada=None, planos: Sequence[Plano] = (),
                 cartoes: Sequence[cartoes_mod.Cartao] = (),
                 falas: Sequence[tuple[float, float]] = ()):
        self.geo = Geometria(largura, altura)
        self.direcao = Direcao(planos, self.geo)
        self.fundo, self.fundo_na_saida = fundo, fundo_na_saida
        self.camada = camada
        self.cartoes = list(cartoes)
        self.falas = list(falas)

    def falando(self, t: float) -> bool:
        """Se há fala em ``t`` (com 40 ms antes e 60 ms depois, como no chat)."""
        return any(a0 - 0.04 <= t <= a1 + 0.06 for a0, a1 in self.falas)

    def quadro(self, t_origem: float, t_saida: float, extra: float = 0.0
               ) -> tuple[Image.Image, Estado]:
        estado, pulo = self.direcao.em(t_saida)
        q = self.fundo.em(t_saida if self.fundo_na_saida else t_origem)
        largura, altura = self.geo.largura, self.geo.altura
        cena = (Image.fromarray(q) if q is not None
                else Image.new("RGB", self.geo.palco, (0, 0, 0)))
        lp, ap = self.geo.palco
        s = max(lp / cena.width, ap / cena.height)
        cw, ch = lp / s, ap / s
        x0, y0 = (cena.width - cw) / 2, (cena.height - ch) / 2
        palco = cena.resize((lp, ap), Image.BILINEAR,
                            box=(x0, y0, x0 + cw, y0 + ch)).convert("RGBA")
        ativos = [c for c in self.cartoes if c.inicio <= t_saida < c.fim]
        if self.geo.formato == "deitado":
            # Deitado, o personagem fica num canto, por cima da cena; os cartões vêm por
            # cima dele, como numa transmissão com a câmera no canto.
            tela = camera(palco, estado, extra)
            self._personagem(tela, estado, pulo, t_origem, t_saida)
            if any(c.no_palco for c in ativos):
                cartoes_no_palco = Image.new("RGBA", palco.size, (0, 0, 0, 0))
                for c in ativos:
                    cartoes_mod.desenhar(cartoes_no_palco, c, t_saida, palco=True)
                tela.alpha_composite(camera(cartoes_no_palco, estado, extra))
            for c in ativos:
                cartoes_mod.desenhar(tela, c, t_saida, palco=False)
            return tela.convert("RGB"), estado
        for c in ativos:
            cartoes_mod.desenhar(palco, c, t_saida, palco=True)
        janela = camera(palco, estado, extra)
        for c in ativos:
            cartoes_mod.desenhar(janela, c, t_saida, palco=False)
        tela = fundo_desfocado(cena, largura, altura).convert("RGBA")
        self._personagem(tela, estado, pulo, t_origem, t_saida)
        self._bordas(tela, estado)
        tela.alpha_composite(janela, (round(estado.x), round(estado.y)))
        faixa = _faixa(janela.width, max(2, round(FAIXA * self.geo.k)))
        tela.alpha_composite(faixa, (round(estado.x), round(estado.y)))
        tela.alpha_composite(faixa, (round(estado.x),
                                     round(estado.y + estado.altura - faixa.height)))
        return tela.convert("RGB"), estado

    def _bordas(self, tela: Image.Image, estado: Estado) -> None:
        alto = max(4, round(60 * self.geo.k))
        largura = max(1, round(estado.largura))
        de_cima = _sombra_da_borda(largura, alto, True)
        de_baixo = _sombra_da_borda(largura, alto, False)
        _colar_dentro(tela, de_cima, round(estado.x), round(estado.y) - alto)
        _colar_dentro(tela, de_baixo, round(estado.x), round(estado.y + estado.altura))

    def _personagem(self, tela: Image.Image, estado: Estado, pulo: float, t_origem: float,
                    t_saida: float) -> None:
        if self.camada is None:
            return
        from editor.montagem import CamadaDePersonagem

        if isinstance(self.camada, CamadaDePersonagem):
            # A boca só mexe com fala: nas pausas, fica o primeiro quadro (o de boca
            # fechada, no personagem do vídeo de referência).
            rgba = (self.camada.personagem.quadro_em(t_saida) if self.falando(t_saida)
                    else self.camada.personagem.quadros[0])
        else:
            rgba = self.camada.rgba(t_origem, t_saida)
        p = self.camada.pessoa
        lc, ac = self.camada.largura, self.camada.altura
        visivel = max(1.0, (p.y1 - p.y0) * ac)
        s = estado.tamanho * 0.9 / visivel
        k = self.geo.k
        balanco = math.sin(t_saida * 6) * BALANCO * k if self.falando(t_saida) else 0.0
        dy = balanco - pulo * PULO * k
        img = Image.fromarray(rgba, "RGBA")
        img = img.resize((max(1, round(lc * s)), max(1, round(ac * s))), Image.BILINEAR)
        sombra = _sombra_do_personagem(img, k)
        # o centro da silhueta em cx, e a base dela no piso
        cx = estado.cx - ((p.x0 + p.x1) / 2 - 0.5) * img.width
        base = estado.piso - p.y1 * img.height
        cy = base + img.height / 2 + dy
        giro = pulo * GIRO_DO_PULO
        cartoes_mod.colar(tela, sombra, cx, cy + 18 * k, giro=giro, opacidade=0.55)
        cartoes_mod.colar(tela, img, cx, cy, giro=giro)


def _sombra_do_personagem(img: Image.Image, k: float) -> Image.Image:
    """A sombra borrada (``drop-shadow(0 18px 40px)``), feita num tamanho pequeno."""
    pequeno = img.getchannel("A").resize((max(1, img.width // 6), max(1, img.height // 6)),
                                         Image.BILINEAR)
    pequeno = pequeno.filter(ImageFilter.GaussianBlur(max(1.0, 40 * k / 6)))
    alfa = pequeno.resize(img.size, Image.BILINEAR)
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 255))
    sombra.putalpha(alfa)
    return sombra


def _colar_dentro(tela: Image.Image, img: Image.Image, x: int, y: int) -> bool:
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(tela.width, x + img.width), min(tela.height, y + img.height)
    if x1 <= x0 or y1 <= y0:
        return False
    tela.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))
    return True


def falas(palavras: Sequence, juntar_abaixo_de: float = 0.25) -> list[tuple[float, float]]:
    """Os trechos com fala: palavras separadas por menos de 250 ms contam como um, para a
    boca não fechar entre elas (a regra do vídeo de referência)."""
    trechos: list[list[float]] = []
    for w in palavras:
        if trechos and w.inicio - trechos[-1][1] < juntar_abaixo_de:
            trechos[-1][1] = max(trechos[-1][1], w.fim)
        else:
            trechos.append([w.inicio, w.fim])
    return [(a0, a1) for a0, a1 in trechos]


__all__ = ["PALCO", "Direcao", "Estado", "Geometria", "MontadorDeJanela", "Plano", "camera",
           "dirigir", "falas", "fundo_desfocado"]
