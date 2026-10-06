"""
A biblioteca de cenas: o fundo da montagem feito de vários clipes, escolhidos pelo que
é dito.

No vídeo de referência, um trailer foi cortado em 128 cenas de ~2 s, descritas num
catálogo (``cenas.json``), e cada bloco do roteiro tocava as cenas que combinavam com
ele. Aqui a pessoa traz a pasta das cenas e o catálogo (a "matriz"), e quem escolhe é o
Gemini (:mod:`editor.roteiro`) ou, sem ele, as palavras.

**A matriz** é uma lista (ou ``{"cenas": [...]}``) com, por cena:

- ``arquivo`` (obrigatório): o clipe, casado pelo nome do arquivo com o que veio na pasta;
- ``descricao`` (obrigatória): o que aparece;
- opcionais, que ajudam a escolha: ``id``, ``categorias``, ``personagens``, ``periodo``,
  ``energia`` (baixa, media, alta), ``monetizacao`` (ok, cuidado, evitar) e ``obs``.

Cena marcada "evitar" nunca entra.
"""
from __future__ import annotations

import bisect
import json
import math
import re
import unicodedata
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from editor import video as video_mod
from editor.transcricao import Palavra

#: Os vídeos que a biblioteca aceita.
EXTENSOES = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
#: Um bloco de fala dura de 2 a 6 s; uma cena, uns 2 s.
BLOCO_MINIMO_S = 2.0
BLOCO_MAXIMO_S = 6.0
CENA_S = 2.2
#: Uma pausa maior que isto também fecha um bloco.
PAUSA_DO_BLOCO_S = 0.6
#: No máximo esta quantidade de cenas "cuidado" por vídeo.
CUIDADO_MAXIMO = 2
#: O corte para um quadro antes do fim da cena, para não pegar a próxima tomada do trailer.
SOBRA_S = 1 / 30
#: O tamanho em que as cenas são entregues (16:9, cortadas para cobrir).
TAMANHO = (1280, 720)

ENERGIAS = ("baixa", "media", "alta")
MONETIZACOES = ("ok", "cuidado", "evitar")


class MatrizInvalida(ValueError):
    """A matriz não é uma lista de cenas com arquivo e descrição."""


@dataclass
class Cena:
    id: str
    arquivo: Path
    descricao: str
    categorias: list[str] = field(default_factory=list)
    personagens: list[str] = field(default_factory=list)
    periodo: str = ""
    energia: str = ""
    monetizacao: str = "ok"
    obs: str = ""
    duracao: float = 0.0
    largura: int = 0
    altura: int = 0
    rotacao: int = 0

    def linha(self) -> str:
        """A cena numa linha, para o pedido do Gemini."""
        partes = [self.id, self.descricao]
        if self.categorias:
            partes.append("categorias: " + ", ".join(self.categorias))
        if self.personagens:
            partes.append("personagens: " + ", ".join(self.personagens))
        for rotulo, valor in (("período", self.periodo), ("energia", self.energia),
                              ("monetização", self.monetizacao), ("obs", self.obs)):
            if valor:
                partes.append(f"{rotulo}: {valor}")
        partes.append(f"{self.duracao:.1f} s")
        return " | ".join(partes)


@dataclass
class Biblioteca:
    #: As cenas que podem entrar (com clipe, sem as "evitar").
    cenas: list[Cena]
    evitadas: int = 0
    #: Entradas da matriz cujo clipe não veio na pasta.
    sem_clipe: list[str] = field(default_factory=list)
    #: Clipes da pasta que a matriz não descreve.
    sem_descricao: list[str] = field(default_factory=list)

    @property
    def duracao(self) -> float:
        return sum(c.duracao for c in self.cenas)

    def por_id(self) -> dict[str, Cena]:
        return {c.id: c for c in self.cenas}

    def ficha(self) -> dict:
        return {"cenas": len(self.cenas), "duracao": round(self.duracao, 1),
                "evitadas": self.evitadas, "sem_clipe": self.sem_clipe[:20],
                "sem_descricao": self.sem_descricao[:20]}


def clipes_da_pasta(pasta: Path) -> list[Path]:
    """Os vídeos de uma pasta e das subpastas."""
    return sorted(p for p in Path(pasta).rglob("*")
                  if p.is_file() and p.suffix.lower() in EXTENSOES
                  and not p.name.startswith("."))


def _lista(valor) -> list[str]:
    if isinstance(valor, str):
        return [v.strip() for v in valor.split(",") if v.strip()]
    if isinstance(valor, list):
        return [str(v).strip() for v in valor if str(v).strip()]
    return []


def ler_matriz(dados: str | bytes | list | dict, clipes: Sequence[Path]) -> Biblioteca:
    """A biblioteca a partir da matriz (o texto do JSON, ou já lido) e dos clipes que
    vieram. Mede cada clipe (duração e tamanho)."""
    if isinstance(dados, (str, bytes)):
        try:
            dados = json.loads(dados)
        except json.JSONDecodeError as erro:
            raise MatrizInvalida(f"a matriz não é um JSON válido: {erro.msg} "
                                 f"(linha {erro.lineno})") from erro
    lista = dados.get("cenas") if isinstance(dados, dict) else dados
    if not isinstance(lista, list) or not lista:
        raise MatrizInvalida("a matriz precisa ser uma lista de cenas (ou "
                             '{"cenas": [...]}), como o cenas.json')
    por_nome = {Path(c).name.lower(): Path(c) for c in clipes}
    usados: set[str] = set()
    cenas, evitadas, sem_clipe = [], 0, []
    for k, item in enumerate(lista):
        if not isinstance(item, dict) or not item.get("arquivo") or not item.get("descricao"):
            raise MatrizInvalida(f"a cena {k + 1} da matriz não tem "
                                 '"arquivo" e "descricao"')
        nome = Path(str(item["arquivo"]).replace("\\", "/")).name.lower()
        caminho = por_nome.get(nome)
        ident = str(item.get("id") or Path(nome).stem)
        if caminho is None:
            sem_clipe.append(ident)
            continue
        usados.add(nome)
        monetizacao = str(item.get("monetizacao", "ok")).strip().lower() or "ok"
        if monetizacao == "evitar":
            evitadas += 1
            continue
        try:
            info = video_mod.sondar(caminho)
        except Exception:
            sem_clipe.append(ident)
            continue
        if info.duracao <= 0.2:
            continue
        energia = str(item.get("energia", "")).strip().lower()
        cenas.append(Cena(
            id=ident, arquivo=caminho, descricao=str(item["descricao"]).strip(),
            categorias=_lista(item.get("categorias")),
            personagens=_lista(item.get("personagens")),
            periodo=str(item.get("periodo", "")).strip(),
            energia=energia if energia in ENERGIAS else "",
            monetizacao=monetizacao if monetizacao in MONETIZACOES else "ok",
            obs=str(item.get("obs", "")).strip(), duracao=round(info.duracao, 3),
            largura=info.largura, altura=info.altura, rotacao=info.rotacao))
    sem_descricao = sorted(Path(c).name for n, c in por_nome.items() if n not in usados)
    if not cenas:
        raise MatrizInvalida("nenhuma cena da matriz casou com os clipes da pasta "
                             "(o nome do arquivo precisa ser o mesmo)")
    return Biblioteca(cenas, evitadas, sem_clipe, sem_descricao)


# ── os blocos da fala ────────────────────────────────────────────────────


@dataclass
class BlocoDeFala:
    inicio: float
    fim: float
    #: As palavras do bloco: da ``primeira`` à ``ultima`` (índices na fala).
    primeira: int
    ultima: int
    texto: str

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio


def blocos_da_fala(palavras: Sequence[Palavra], duracao: float) -> list[BlocoDeFala]:
    """A fala em blocos de 2 a 6 s, fechados no fim das frases ou nas pausas. Os blocos
    cobrem o vídeo inteiro, do zero à ``duracao``."""
    if not palavras:
        return [BlocoDeFala(0.0, duracao, 0, -1, "")] if duracao > 0 else []
    grupos: list[list[int]] = [[]]
    for i, w in enumerate(palavras):
        atual = grupos[-1]
        if atual:
            comeco = palavras[atual[0]].inicio
            longo = w.fim - comeco > BLOCO_MAXIMO_S
            pausa = w.inicio - palavras[atual[-1]].fim > PAUSA_DO_BLOCO_S
            if longo or (pausa and palavras[atual[-1]].fim - comeco >= BLOCO_MINIMO_S):
                grupos.append([])
                atual = grupos[-1]
        atual.append(i)
        fecha = w.texto.rstrip().endswith((".", "!", "?", "…"))
        if fecha and w.fim - palavras[atual[0]].inicio >= BLOCO_MINIMO_S:
            grupos.append([])
    grupos = [g for g in grupos if g]
    # um último bloco curto demais vai para o anterior
    if len(grupos) > 1 and palavras[grupos[-1][-1]].fim - palavras[grupos[-1][0]].inicio \
            < BLOCO_MINIMO_S:
        grupos[-2].extend(grupos.pop())
    blocos = []
    for k, g in enumerate(grupos):
        inicio = 0.0 if k == 0 else palavras[g[0]].inicio
        fim = duracao if k == len(grupos) - 1 else palavras[grupos[k + 1][0]].inicio
        texto = " ".join(palavras[i].texto for i in g)
        blocos.append(BlocoDeFala(round(inicio, 3), round(max(fim, inicio + 0.1), 3), g[0],
                                  g[-1], texto))
    return blocos


def cenas_por_bloco(bloco: BlocoDeFala) -> int:
    """Quantas cenas um bloco pede: uma a cada ~2 s."""
    return max(1, math.ceil(bloco.duracao / CENA_S))


# ── a escolha pelas palavras (sem o Gemini) ──────────────────────────────


def _nua(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in base if not unicodedata.combining(c))


def _termos(texto: str) -> set[str]:
    """As palavras de um texto, sem acento e no singular, só as que dizem algo."""
    from editor.plano import VAZIAS, _formas

    termos = set()
    for w in re.findall(r"[a-z0-9]+", _nua(texto)):
        if len(w) < 4 or w in VAZIAS:
            continue
        termos.update(_formas(w))
    return termos


def escolher_por_palavras(blocos: Sequence[BlocoDeFala], biblioteca: Biblioteca
                          ) -> list[list[str]]:
    """As cenas de cada bloco, casando as palavras dele com a descrição, as categorias,
    os personagens e as observações de cada cena. Sem repetir cena; desempate pela
    energia (o primeiro bloco, o gancho, pede cena forte); sem casamento, as cenas "ok"
    ainda não usadas, em rodízio."""
    termos_da_cena = {c.id: _termos(" ".join([c.descricao, *c.categorias, *c.personagens,
                                               c.obs])) for c in biblioteca.cenas}
    usadas: set[str] = set()
    cuidado = 0
    escolhas: list[list[str]] = []
    reserva = [c for c in biblioteca.cenas if c.monetizacao == "ok"]
    vez = 0
    for k, bloco in enumerate(blocos):
        termos = _termos(bloco.texto)
        quer_forte = k == 0

        def nota(c: Cena, termos=termos, quer_forte=quer_forte) -> tuple:
            casam = len(termos & termos_da_cena[c.id])
            energia = ENERGIAS.index(c.energia) if c.energia in ENERGIAS else 1
            return (casam, energia if quer_forte else 0, -biblioteca.cenas.index(c))

        precisa = cenas_por_bloco(bloco)
        candidatas = sorted((c for c in biblioteca.cenas if c.id not in usadas),
                            key=nota, reverse=True)
        escolhidas: list[str] = []
        for c in candidatas:
            if len(escolhidas) >= precisa or nota(c)[0] == 0:
                break
            if c.monetizacao == "cuidado":
                if cuidado >= CUIDADO_MAXIMO:
                    continue
                cuidado += 1
            escolhidas.append(c.id)
            usadas.add(c.id)
        if len(escolhidas) < precisa and reserva:
            livres = [c for c in reserva if c.id not in usadas]
            if not livres:                  # todas já tocaram: repetem, em rodízio
                livres = reserva[vez % len(reserva):] + reserva[:vez % len(reserva)]
                vez += 1
            if quer_forte:                  # o gancho sem casamento ainda pede cena forte
                livres = sorted(livres, key=lambda c: c.energia != "alta")
            for c in livres[:precisa - len(escolhidas)]:
                escolhidas.append(c.id)
                usadas.add(c.id)
        if quer_forte and escolhidas:
            fortes = [i for i in escolhidas
                      if biblioteca.por_id()[i].energia == "alta"]
            escolhidas = fortes + [i for i in escolhidas if i not in fortes]
        escolhas.append(escolhidas or [biblioteca.cenas[k % len(biblioteca.cenas)].id])
    return escolhas


# ── a trilha ─────────────────────────────────────────────────────────────


@dataclass
class Corte:
    """Um pedaço da trilha: a cena tocando de ``desde`` em diante, de ``inicio`` a
    ``fim`` (no tempo do vídeo editado)."""

    inicio: float
    fim: float
    cena: Cena
    desde: float = 0.0
    bloco: int = 0


def montar_trilha(blocos: Sequence[BlocoDeFala], escolhas: Sequence[Sequence[str]],
                  biblioteca: Biblioteca) -> list[Corte]:
    """As cenas de cada bloco em ordem, até o bloco seguinte; se faltar cena, elas
    repetem em vez de congelar."""
    por_id = biblioteca.por_id()
    cortes: list[Corte] = []
    for k, (bloco, ids) in enumerate(zip(blocos, escolhas, strict=True)):
        cenas = [por_id[i] for i in ids if i in por_id] or [biblioteca.cenas[0]]
        t, i = bloco.inicio, 0
        while t < bloco.fim - 1e-3:
            cena = cenas[i % len(cenas)]
            dura = max(0.3, cena.duracao - SOBRA_S)
            fim = min(bloco.fim, t + dura)
            cortes.append(Corte(round(t, 3), round(fim, 3), cena, 0.0, k))
            t, i = fim, i + 1
    return cortes


class FundoDeCenas:
    """A trilha de cenas com a cara de um ``video.Cursor``: ``em(t)`` devolve o quadro
    do instante ``t`` do vídeo editado, em 16:9, cortado para cobrir."""

    def __init__(self, cortes: Sequence[Corte], tamanho: tuple[int, int] = TAMANHO):
        self.cortes = list(cortes)
        self.inicios = [c.inicio for c in self.cortes]
        self.largura, self.altura = tamanho
        self._cursores: OrderedDict[Path, video_mod.Cursor] = OrderedDict()

    def corte_em(self, t: float) -> Corte | None:
        if not self.cortes:
            return None
        k = max(0, bisect.bisect_right(self.inicios, t) - 1)
        return self.cortes[k]

    def _cursor(self, cena: Cena) -> video_mod.Cursor:
        cursor = self._cursores.get(cena.arquivo)
        if cursor is None:
            cursor = video_mod.Cursor(cena.arquivo, cena.rotacao, duracao=cena.duracao)
            self._cursores[cena.arquivo] = cursor
            while len(self._cursores) > 4:
                self._cursores.popitem(last=False)
        else:
            self._cursores.move_to_end(cena.arquivo)
        return cursor

    def em(self, t: float) -> np.ndarray | None:
        corte = self.corte_em(t)
        if corte is None:
            return None
        local = min(corte.cena.duracao - SOBRA_S, corte.desde + max(0.0, t - corte.inicio))
        q = self._cursor(corte.cena).em(max(0.0, local))
        if q is None:
            return None
        return cobrir(q, self.largura, self.altura)


def cobrir(q: np.ndarray, largura: int, altura: int) -> np.ndarray:
    """O quadro cortado e redimensionado para cobrir ``largura`` × ``altura``."""
    h, w = q.shape[:2]
    if (w, h) == (largura, altura):
        return q
    escala = max(largura / w, altura / h)
    cw, ch = largura / escala, altura / escala
    x0, y0 = (w - cw) / 2, (h - ch) / 2
    img = Image.fromarray(q).resize((largura, altura), Image.BILINEAR,
                                    box=(x0, y0, x0 + cw, y0 + ch))
    return np.asarray(img)


__all__ = ["Biblioteca", "BlocoDeFala", "Cena", "Corte", "FundoDeCenas", "MatrizInvalida",
           "blocos_da_fala", "cenas_por_bloco", "clipes_da_pasta", "cobrir",
           "escolher_por_palavras", "ler_matriz", "montar_trilha"]
