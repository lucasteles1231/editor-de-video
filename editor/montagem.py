"""
A montagem em camadas: um vídeo de fundo sem pessoa e, por cima, o vídeo da pessoa
falando ou um personagem animado em loop.

A ideia é do dono (03/10/2026): com as camadas separadas, a pessoa anda por cima do
fundo sem precisar apagar nada dele, e o fundo é o vídeo de verdade (uma tela gravada,
um jogo, slides), e não um borrão do mesmo quadro.

- **O quadro final** tem o formato escolhido: igual ao fundo, em pé, deitado ou
  quadrado. O fundo é encaixado inteiro, e as sobras são ele mesmo, cobrindo tudo,
  desfocado e escurecido. Em pé, a faixa fica um pouco acima do meio, e o lugar de baixo
  é da pessoa.
- **A pessoa** vem de um vídeo já sem fundo (o alfa do próprio arquivo) ou é recortada
  pelo MODNet quadro a quadro. **O personagem** é um GIF, PNG animado ou WebP, em loop
  pelo tempo de saída: assim a animação não pula nos cortes.
- **Onde ela fica:** a posição de casa (embaixo no meio em pé; embaixo à direita deitado
  e quadrado, a câmera clássica de quem grava a tela) e, nos movimentos do plano, um
  lado, o meio, em cima, embaixo, perto ou longe. A posição é calculada pelo que
  aparece (a silhueta), e não pelo quadro inteiro da camada.
- **A fala** vem do áudio à parte, se houver; senão do vídeo da pessoa, se ele tiver
  som; senão do fundo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence

from editor import recorte
from editor import video as video_mod
from editor.mover import (
    TRANSICAO_S,
    RecorteContinuo,
    Transformacao,
    bordas_tocadas,
    borrar,
    colar,
    curva_do_alfa,
    expostas,
    rampa,
    suave,
)
from editor.plano import Movimento, Plano

logger = logging.getLogger(__name__)

RECORTES = ("modnet", "transparente")
FORMATOS = ("fundo", "vertical", "horizontal", "quadrado")
PROPORCOES = {"vertical": (9, 16), "horizontal": (16, 9), "quadrado": (1, 1)}

#: Em pé, o centro da faixa do fundo fica nesta fração da altura.
CENTRO_DO_FUNDO_EM_PE = 0.4
#: As sobras: o quadro reduzido neste divisor, borrado e escurecido.
REDUCAO_DAS_SOBRAS = 8
RAIO_DAS_SOBRAS = 0.06
LUZ_DAS_SOBRAS = 0.55
#: A altura do que aparece da camada, na posição de casa, em fração do quadro.
ALTURA_EM_PE = 0.5
ALTURA_DEITADO = 0.55
#: A largura máxima dela, em fração do quadro.
LARGURA_MAXIMA = 0.9
#: As margens, em fração do quadro.
MARGEM = 0.03
#: Um busto encosta na borda de baixo do próprio quadro se o que aparece vai até aqui.
ENCOSTA_EMBAIXO = 0.97

#: O personagem: o teto do arquivo, dos quadros e dos pixels guardados (RGBA, uns 4 bytes
#: cada), e o maior lado de cada quadro.
PERSONAGEM_TETO_BYTES = 20 * 1024 * 1024
PERSONAGEM_TETO_QUADROS = 600
PERSONAGEM_TETO_PIXELS = 60_000_000
PERSONAGEM_LADO_MAXIMO = 1080
#: Duração de quadro abaixo disto vira 100 ms, como fazem os navegadores.
DURACAO_MINIMA_S = 0.02
DURACAO_PADRAO_S = 0.1
#: O fundo de cor única do personagem: os quatro cantos parecidos (distância RGB), a
#: tolerância em volta da cor e a borda macia.
CANTOS_PARECIDOS = 36.0
TOLERANCIA_DA_COR = 40.0
BORDA_DA_COR = 30.0


# ── as entradas ──────────────────────────────────────────────────────────


@dataclass
class Montagem:
    """O que vai em cada camada, e como."""

    fundo: Path
    pessoa: Path | None = None
    personagem: Path | None = None
    audio: Path | None = None
    #: Como tirar o fundo da pessoa: "transparente" (o alfa do arquivo) ou "modnet".
    recorte: str = "modnet"
    #: O formato do quadro final: "fundo", "vertical", "horizontal" ou "quadrado".
    formato: str = "fundo"
    tirar_fundo_do_personagem: bool = True

    def problemas(self) -> list[str]:
        erros = []
        if (self.pessoa is None) == (self.personagem is None):
            erros.append("a montagem leva o vídeo da pessoa ou um personagem, um dos dois")
        if self.recorte not in RECORTES:
            erros.append(f"recorte desconhecido: {self.recorte} (use {' ou '.join(RECORTES)})")
        if self.formato not in FORMATOS:
            erros.append(f"formato desconhecido: {self.formato} (use {', '.join(FORMATOS)})")
        return erros

    def fonte_da_fala(self) -> Path:
        """De onde vem a fala: o áudio à parte; senão o vídeo da pessoa, se tiver som;
        senão o fundo."""
        if self.audio is not None:
            return Path(self.audio)
        if self.pessoa is not None and video_mod.sondar(Path(self.pessoa)).tem_audio:
            return Path(self.pessoa)
        return Path(self.fundo)


# ── o quadro final ───────────────────────────────────────────────────────


def tamanho_do_quadro(formato: str, largura: int, altura: int) -> tuple[int, int]:
    """O tamanho do quadro final antes da resolução escolhida: o do fundo, ou a proporção
    pedida com o lado curto igual ao do fundo."""
    if formato == "fundo":
        return largura, altura
    curto = min(largura, altura)
    a, b = PROPORCOES[formato]
    if a <= b:
        return curto, round(curto * b / a)
    return round(curto * a / b), curto


def encaixe(largura_do_fundo: int, altura_do_fundo: int, largura: int, altura: int
            ) -> tuple[int, int, int, int]:
    """Onde o fundo encaixado inteiro fica no quadro: (x, y, largura, altura)."""
    s = min(largura / largura_do_fundo, altura / altura_do_fundo)
    w = min(largura, max(1, round(largura_do_fundo * s)))
    h = min(altura, max(1, round(altura_do_fundo * s)))
    x = (largura - w) // 2
    centro = CENTRO_DO_FUNDO_EM_PE * altura if altura > largura and h < altura else altura / 2
    y = round(min(max(centro - h / 2, 0.0), altura - h))
    return x, y, w, h


def sobras(img: Image.Image, largura: int, altura: int) -> Image.Image:
    """O fundo cobrindo o quadro todo, desfocado e escurecido (feito num quadro pequeno)."""
    ls, hs = max(8, largura // REDUCAO_DAS_SOBRAS), max(8, altura // REDUCAO_DAS_SOBRAS)
    s = max(ls / img.width, hs / img.height)
    cw, ch = ls / s, hs / s
    x0, y0 = (img.width - cw) / 2, (img.height - ch) / 2
    pequeno = np.asarray(img.resize((ls, hs), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch)),
                         dtype=np.float32)
    borrado = borrar(pequeno, max(ls, hs) * RAIO_DAS_SOBRAS) * LUZ_DAS_SOBRAS
    return Image.fromarray(np.clip(borrado, 0, 255).astype(np.uint8)).resize(
        (largura, altura), Image.BILINEAR)


# ── o personagem ─────────────────────────────────────────────────────────


@dataclass
class Personagem:
    """Os quadros RGBA do personagem e quanto cada um dura, em loop."""

    quadros: list[np.ndarray]
    duracoes: list[float]
    tem_alfa: bool

    def __post_init__(self) -> None:
        self._fins = np.cumsum(self.duracoes)

    @property
    def duracao(self) -> float:
        return float(self._fins[-1]) if len(self._fins) else 0.0

    @property
    def largura(self) -> int:
        return int(self.quadros[0].shape[1])

    @property
    def altura(self) -> int:
        return int(self.quadros[0].shape[0])

    def quadro_em(self, t: float) -> np.ndarray:
        if len(self.quadros) == 1 or self.duracao <= 0:
            return self.quadros[0]
        i = int(np.searchsorted(self._fins, t % self.duracao, side="right"))
        return self.quadros[min(i, len(self.quadros) - 1)]


def _cantos(rgba: np.ndarray) -> np.ndarray:
    return np.array([rgba[0, 0, :3], rgba[0, -1, :3], rgba[-1, 0, :3], rgba[-1, -1, :3]],
                    dtype=np.float32)


def cor_do_fundo(rgba: np.ndarray) -> np.ndarray | None:
    """A cor do fundo, se os quatro cantos são da mesma cor (senão ``None``)."""
    cantos = _cantos(rgba)
    cor = np.median(cantos, axis=0)
    if np.linalg.norm(cantos - cor, axis=1).max() > CANTOS_PARECIDOS:
        return None
    return cor


def tirar_fundo_de_cor(rgba: np.ndarray, cor: np.ndarray) -> np.ndarray:
    """O alfa zerado onde a cor é a do fundo, com uma borda macia."""
    distancia = np.linalg.norm(rgba[..., :3].astype(np.float32) - cor, axis=-1)
    alfa = np.clip((distancia - TOLERANCIA_DA_COR) / BORDA_DA_COR, 0.0, 1.0)
    saida = rgba.copy()
    saida[..., 3] = (np.minimum(rgba[..., 3] / 255.0, alfa) * 255).astype(np.uint8)
    return saida


class PersonagemInvalido(ValueError):
    """O arquivo não serve de personagem (com a explicação para quem usa)."""


def ler_personagem(caminho: Path, *, tirar_fundo: bool = True,
                   lado_maximo: int = PERSONAGEM_LADO_MAXIMO) -> Personagem:
    """Os quadros de um GIF, PNG animado ou WebP, em RGBA."""
    caminho = Path(caminho)
    if caminho.stat().st_size > PERSONAGEM_TETO_BYTES:
        raise PersonagemInvalido("O personagem passa de 20 MB.")
    try:
        img = Image.open(caminho)
        img.load()
    except Exception as erro:
        raise PersonagemInvalido("Não consegui abrir este personagem. Use um GIF, um PNG "
                                 "animado ou um WebP.") from erro
    n = getattr(img, "n_frames", 1)
    if n > PERSONAGEM_TETO_QUADROS:
        raise PersonagemInvalido(f"O personagem tem {n} quadros; o teto é "
                                 f"{PERSONAGEM_TETO_QUADROS}.")
    escala = min(1.0, lado_maximo / max(img.size))
    if n * img.width * img.height * escala * escala > PERSONAGEM_TETO_PIXELS:
        escala = (PERSONAGEM_TETO_PIXELS / (n * img.width * img.height)) ** 0.5
    tamanho = (max(1, round(img.width * escala)), max(1, round(img.height * escala)))
    quadros, duracoes = [], []
    for quadro in ImageSequence.Iterator(img):
        rgba = quadro.convert("RGBA")
        if rgba.size != tamanho:
            rgba = rgba.resize(tamanho, Image.LANCZOS)
        quadros.append(np.asarray(rgba, dtype=np.uint8).copy())
        d = float(quadro.info.get("duration", img.info.get("duration", 100)) or 0) / 1000
        duracoes.append(d if d >= DURACAO_MINIMA_S else DURACAO_PADRAO_S)
    tem_alfa = any(int(q[..., 3].min()) < 250 for q in quadros)
    if not tem_alfa and tirar_fundo:
        cor = cor_do_fundo(quadros[0])
        if cor is not None:
            quadros = [tirar_fundo_de_cor(q, cor) for q in quadros]
    return Personagem(quadros, duracoes, tem_alfa)


# ── as camadas de cima ───────────────────────────────────────────────────


class Camada:
    """O que vai por cima do fundo. ``rgba`` devolve o quadro com alfa no tamanho dela."""

    largura: int
    altura: int
    #: O que aparece dela (a silhueta) e uma estimativa do rosto, em frações do quadro.
    pessoa: recorte.Caixa
    rosto: recorte.Caixa
    #: As bordas do quadro dela em que a pessoa encosta (onde ela vinha cortada).
    bordas: dict[str, bool]

    def rgba(self, t_origem: float, t_saida: float) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def _medir(self, alfas: list[np.ndarray]) -> None:
        """As caixas pela união dos alfas de alguns quadros."""
        uniao = np.max(np.stack(alfas), axis=0) if alfas else np.zeros((2, 2), np.float32)
        pessoa, rosto = recorte.caixas(uniao)
        if pessoa is None or rosto is None:
            pessoa = rosto = recorte.Caixa(0.0, 0.0, 1.0, 1.0)
        self.pessoa, self.rosto = pessoa, rosto
        self.bordas = bordas_tocadas(uniao)


class CamadaComAlfa(Camada):
    """O vídeo da pessoa já sem fundo: o alfa vem do próprio arquivo."""

    def __init__(self, caminho: Path, info: video_mod.Info):
        self.cursor = video_mod.Cursor(caminho, info.rotacao, alfa=True, duracao=info.duracao)
        self.largura, self.altura = info.largura, info.altura
        amostras = []
        for k, (_t, q) in enumerate(video_mod.quadros(caminho, info.rotacao, alfa=True)):
            if k % 10 == 0:
                amostras.append(q[..., 3].astype(np.float32) / 255.0)
            if len(amostras) >= 6:
                break
        self._medir(amostras)

    def rgba(self, t_origem: float, t_saida: float) -> np.ndarray:
        q = self.cursor.em(t_origem)
        return q if q is not None else np.zeros((self.altura, self.largura, 4), np.uint8)


class CamadaRecortada(Camada):
    """O vídeo da pessoa recortado pelo MODNet, quadro a quadro."""

    def __init__(self, caminho: Path, info: video_mod.Info):
        self.cursor = video_mod.Cursor(caminho, info.rotacao, duracao=info.duracao)
        self.largura, self.altura = info.largura, info.altura
        self.recorte = RecorteContinuo()
        amostras = []
        medidor = RecorteContinuo(a_cada=1, suavizar=0.0)
        for k, (_t, q) in enumerate(video_mod.quadros(caminho, info.rotacao)):
            if k % 15 == 0:
                amostras.append(medidor.alfa(q))
            if len(amostras) >= 3:
                break
        self._medir(amostras)
        self._origem: np.ndarray | None = None
        self._rgba: np.ndarray | None = None

    def rgba(self, t_origem: float, t_saida: float) -> np.ndarray:
        q = self.cursor.em(t_origem)
        if q is None:
            return np.zeros((self.altura, self.largura, 4), np.uint8)
        if q is self._origem and self._rgba is not None:
            return self._rgba
        alfa = curva_do_alfa(self.recorte.alfa(q))
        mascara = Image.fromarray((np.clip(alfa, 0, 1) * 255).astype(np.uint8)).resize(
            (q.shape[1], q.shape[0]), Image.BILINEAR)
        self._origem = q
        self._rgba = np.dstack([q, np.asarray(mascara)])
        return self._rgba


class CamadaDePersonagem(Camada):
    """O personagem em loop, pelo tempo de saída."""

    def __init__(self, personagem: Personagem):
        self.personagem = personagem
        self.largura, self.altura = personagem.largura, personagem.altura
        self._medir([q[..., 3].astype(np.float32) / 255.0 for q in personagem.quadros])

    def rgba(self, t_origem: float, t_saida: float) -> np.ndarray:
        return self.personagem.quadro_em(t_saida)


# ── onde ela fica ────────────────────────────────────────────────────────


def casa(camada: Camada, largura: int, altura: int) -> Transformacao:
    """A posição de casa: embaixo no meio em pé; embaixo à direita deitado e quadrado."""
    em_pe = altura > largura
    p = camada.pessoa
    ph = (p.y1 - p.y0) * camada.altura
    pw = (p.x1 - p.x0) * camada.largura
    s = (ALTURA_EM_PE if em_pe else ALTURA_DEITADO) * altura / max(ph, 1.0)
    s = min(s, LARGURA_MAXIMA * largura / max(pw, 1.0))
    if em_pe:
        dx = largura / 2 - s * (p.x0 + p.x1) / 2 * camada.largura
    else:
        dx = largura * (1 - MARGEM) - s * p.x1 * camada.largura
    return Transformacao(s, dx, _no_chao(camada, s, altura))


def _no_chao(camada: Camada, s: float, altura: int) -> float:
    """O ``dy`` que põe a base do que aparece embaixo: colada na borda, se é um busto
    cortado embaixo; com margem, se é um corpo inteiro."""
    base = camada.pessoa.y1 * camada.altura
    if camada.pessoa.y1 >= ENCOSTA_EMBAIXO:
        return altura - s * base
    return altura * (1 - MARGEM) - s * base


def alvo(posicao: str, de_casa: Transformacao, camada: Camada, largura: int, altura: int
         ) -> Transformacao:
    """Para onde a camada vai em cada posição do plano, a partir da casa."""
    p, r = camada.pessoa, camada.rosto
    lc, ac = camada.largura, camada.altura
    s0 = de_casa.escala
    base = de_casa.dy + s0 * p.y1 * ac                     # onde fica a base, na tela

    def centro_em(x_tela: float, s: float) -> Transformacao:
        dx = x_tela - s * (p.x0 + p.x1) / 2 * lc
        return Transformacao(s, dx, base - s * p.y1 * ac)

    if posicao in ("esquerda", "direita"):
        # Encostada na borda: num personagem estreito, "o centro a 72%" deixava ele quase
        # no mesmo lugar da casa deitada.
        dx = (MARGEM * largura - s0 * p.x0 * lc if posicao == "esquerda"
              else largura * (1 - MARGEM) - s0 * p.x1 * lc)
        return Transformacao(s0, dx, de_casa.dy)
    if posicao == "meio":
        return centro_em(0.5 * largura, s0)
    if posicao == "cima":
        s = s0 * 0.8
        cx = s0 * (p.x0 + p.x1) / 2 * lc + de_casa.dx
        return Transformacao(s, cx - s * (p.x0 + p.x1) / 2 * lc,
                             2 * MARGEM * altura - s * p.y0 * ac)
    if posicao == "baixo":
        return Transformacao(s0, de_casa.dx, de_casa.dy + 0.15 * altura)
    if posicao == "perto":
        fx, fy = de_casa.ponto((r.x0 + r.x1) / 2 * lc, (r.y0 + r.y1) / 2 * ac)
        return de_casa.empurrada(0.35, fx, fy)
    if posicao == "longe":
        bx, by = de_casa.ponto((p.x0 + p.x1) / 2 * lc, p.y1 * ac)
        return de_casa.empurrada(-0.3, bx, by)
    raise ValueError(f"posição desconhecida: {posicao}")


# ── o quadro composto ────────────────────────────────────────────────────


class Montador:
    """Compõe cada quadro: o fundo encaixado e, por cima, a pessoa ou o personagem."""

    def __init__(self, montagem: Montagem, plano: Plano, largura: int, altura: int,
                 info_do_fundo: video_mod.Info, *, mover: bool = True):
        self.largura, self.altura = largura, altura
        self.fundo = video_mod.Cursor(montagem.fundo, info_do_fundo.rotacao,
                                      duracao=info_do_fundo.duracao)
        self.caixa_do_fundo = encaixe(info_do_fundo.largura, info_do_fundo.altura,
                                      largura, altura)
        if montagem.personagem is not None:
            self.camada: Camada = CamadaDePersonagem(ler_personagem(
                montagem.personagem, tirar_fundo=montagem.tirar_fundo_do_personagem))
        else:
            info = video_mod.sondar(montagem.pessoa)
            self.camada = (CamadaComAlfa(montagem.pessoa, info)
                           if montagem.recorte == "transparente"
                           else CamadaRecortada(montagem.pessoa, info))
        self.casa = casa(self.camada, largura, altura)
        self.movimentos = sorted(plano.movimentos, key=lambda m: m.inicio) if mover else []
        self._alvos: dict[int, Transformacao] = {}
        self._rampas: dict[tuple, np.ndarray | None] = {}

    # o tempo e o lugar

    def em(self, t: float) -> tuple[Movimento, float] | None:
        """O movimento em andamento em ``t`` e quanto do caminho a camada já fez."""
        for m in self.movimentos:
            if m.inicio <= t < m.fim:
                e = suave((t - m.inicio) / TRANSICAO_S)
                if not m.volta_no_corte:
                    e = min(e, suave((m.fim - t) / TRANSICAO_S))
                return m, e
            if m.inicio > t:
                break
        return None

    def _alvo(self, m: Movimento) -> Transformacao:
        chave = id(m)
        if chave not in self._alvos:
            t = alvo(m.posicao, self.casa, self.camada, self.largura, self.altura)
            if t.perto_de(self.casa, self.largura, self.altura):
                # Ela já estava lá (a casa deitada é à direita): vem para perto.
                t = alvo("perto", self.casa, self.camada, self.largura, self.altura)
            self._alvos[chave] = t
        return self._alvos[chave]

    def transformacao(self, t: float, extra: float = 0.0) -> Transformacao:
        achado = self.em(t)
        tr = self.casa if achado is None else self.casa.ate(self._alvo(achado[0]), achado[1])
        if extra > 0:
            r = self.camada.rosto
            fx, fy = tr.ponto((r.x0 + r.x1) / 2 * self.camada.largura,
                              (r.y0 + r.y1) / 2 * self.camada.altura)
            tr = tr.empurrada(extra, fx, fy)
        return tr

    def lado_livre(self, t: float) -> int:
        """O lado que a camada deixou livre para o ícone (-1 esquerda, 1 direita, 0)."""
        achado = self.em(t)
        if achado is None:
            return 0
        return {"esquerda": 1, "direita": -1}.get(achado[0].posicao, 0)

    # o desenho

    def _rampa(self, tr: Transformacao) -> np.ndarray | None:
        expo = expostas(tr, self.largura, self.altura, self.camada.largura, self.camada.altura)
        somem = tuple(sorted(k for k, v in self.camada.bordas.items() if v and expo[k]))
        if somem not in self._rampas:
            self._rampas[somem] = (rampa(self.camada.altura, self.camada.largura,
                                         dict.fromkeys(somem, True)) if somem else None)
        return self._rampas[somem]

    def tela_do_fundo(self, t_origem: float, nivel: float = 1.0) -> Image.Image:
        from editor.render import janela

        q = self.fundo.em(t_origem)
        img = Image.fromarray(q) if q is not None else Image.new(
            "RGB", (self.largura, self.altura))
        x, y, w, h = self.caixa_do_fundo
        caixa = janela(img.width, img.height, nivel, 0.5, 0.5)
        faixa = img.resize((w, h), Image.BILINEAR, box=caixa)
        if (w, h) == (self.largura, self.altura):
            return faixa
        tela = sobras(img, self.largura, self.altura)
        tela.paste(faixa, (x, y))
        return tela

    def quadro(self, t_origem: float, t_saida: float, *, nivel: float = 1.0,
               extra: float = 0.0) -> Image.Image:
        tela = self.tela_do_fundo(t_origem, nivel).convert("RGBA")
        rgba = self.camada.rgba(t_origem, t_saida)
        tr = self.transformacao(t_saida, extra)
        r = self._rampa(tr)
        if r is not None:
            rgba = rgba.copy()
            rgba[..., 3] = (rgba[..., 3] * r).astype(np.uint8)
        colar(tela, Image.fromarray(rgba, "RGBA"), tr)
        return tela.convert("RGB")


__all__ = ["FORMATOS", "RECORTES", "Camada", "CamadaComAlfa", "CamadaDePersonagem",
           "CamadaRecortada", "Montador", "Montagem", "Personagem", "PersonagemInvalido",
           "alvo", "casa", "cor_do_fundo", "encaixe", "ler_personagem", "sobras",
           "tamanho_do_quadro", "tirar_fundo_de_cor"]
