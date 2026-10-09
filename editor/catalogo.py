"""
A matriz da biblioteca de cenas gerada a partir dos clipes: a pessoa traz a pasta das
cenas que já cortou, e o editor escreve o ``cenas.json``.

- **O Gemini descreve:** cada clipe vai em 3 quadros (começo, meio e fim), 12 clipes
  por pedido, e volta com a descrição, as categorias, os personagens que ele reconhece, o
  período, a monetização e o que atrapalha usar a cena de fundo (texto na tela, logo,
  troca de plano). As categorias já usadas vão no pedido seguinte, para a biblioteca
  falar uma língua só.
- **A energia é o clima da cena** (ação e festa, alta; paisagem e cartela, baixa), e
  quem julga é o Gemini. O movimento da imagem não serve: medido nos 128 clipes do vídeo
  de referência em 09/10, ele concordou com a energia escrita à mão em 51% das cenas, e
  os aéreos lentos de paisagem (a câmera mexe muito) saíam "alta". Ele fica só para o
  rascunho sem o Gemini.
- **Nada é descrito duas vezes:** cada descrição fica guardada pelo arquivo (nome,
  tamanho e data). Gerar de novo, ou depois que a cota acabou, só pede o que falta.
- **Um lote recusado** (o Gemini não descreve nudez, por exemplo) é dividido até achar a
  cena: ela fica "evitar", com o aviso.
- **Sem o Gemini** (sem chave, sem cota): um rascunho, com a descrição pelo nome do
  arquivo e a energia medida, para a pessoa completar na tabela da página.

O resultado é revisado pela pessoa antes de valer (a tabela da página, ou o arquivo,
no terminal): a descrição é o que o roteiro lê para escolher as cenas.
"""
from __future__ import annotations

import io
import itertools
import json
import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from editor import cenas as cenas_mod
from editor import ia

logger = logging.getLogger(__name__)

#: Quantos clipes vão em cada pedido (3 quadros cada: 36 imagens pequenas, umas 11 para 128 cenas).
POR_PEDIDO = 12
QUADROS_POR_CLIPE = 3
#: O lado maior de cada quadro enviado (pequeno: a cota conta pedidos, mas o modelo lê
#: mais rápido, e a descrição não precisa de detalhe).
LADO = 384
#: Quantos quadros por segundo entram na medida do movimento, e em que tamanho.
AMOSTRAS_POR_S = 6
TAMANHO_DO_MOVIMENTO = (64, 36)
PERIODOS = ("dia", "entardecer", "noite", "interno", "n/a")
DESCRICAO_MAXIMA = 140
CATEGORIAS_MAXIMAS = 4

SISTEMA = """Você cataloga cenas curtas de vídeo para um editor escolher o fundo de uma
narração (Shorts, Reels, TikTok). Descreva só o que se vê, sem inventar. Responda só com o
JSON pedido."""

Progresso = Callable[[int, int, int], None]          # (prontas, total, pedidos)


@dataclass
class Clipe:
    """Um clipe lido: os quadros para o Gemini e o quanto ele mexe."""

    caminho: Path
    arquivo: str                      # como vai na matriz, relativo à pasta
    duracao: float
    quadros: list[bytes] = field(default_factory=list)
    movimento: float = 0.0


@dataclass
class Geracao:
    cenas: list[dict]
    #: Quem descreveu: "gemini", "falsa" (a IA dos testes) ou "rascunho" (sem o Gemini).
    por: str = ""
    #: O que faltou ("sem a chave do Gemini…", "a cota acabou…"), para a página.
    aviso: str = ""
    pedidos: int = 0


# ── a leitura dos clipes ────────────────────────────────────────────────


def ler_clipe(caminho: Path, arquivo: str) -> Clipe:
    """Os 3 quadros (a 20%, 50% e 80% do clipe, em JPEG pequeno) e o movimento (a
    diferença média entre quadros seguidos, em cinza e pequenos), numa leitura só."""
    import av

    info = cenas_mod.video_mod.sondar(caminho)
    duracao = max(0.04, info.duracao)
    alvos = [duracao * f for f in (0.2, 0.5, 0.8)][:QUADROS_POR_CLIPE]
    passo = 1.0 / AMOSTRAS_POR_S
    quadros: list[bytes] = []
    cinzas: list[np.ndarray] = []
    proxima_amostra = 0.0
    ultimo = None
    with av.open(str(caminho)) as c:
        fluxo = c.streams.video[0]
        fluxo.thread_type = "AUTO"
        for quadro in c.decode(fluxo):
            t = float(quadro.time or 0.0)
            ultimo = quadro
            if t >= proxima_amostra:
                cinza = quadro.reformat(width=TAMANHO_DO_MOVIMENTO[0],
                                        height=TAMANHO_DO_MOVIMENTO[1], format="gray")
                cinzas.append(cinza.to_ndarray().astype(np.float32))
                proxima_amostra = t + passo
            while alvos and t >= alvos[0]:
                alvos.pop(0)
                quadros.append(_jpeg(quadro.to_image(), info.rotacao))
    while alvos and ultimo is not None:                 # um clipe curto demais
        alvos.pop(0)
        quadros.append(_jpeg(ultimo.to_image(), info.rotacao))
    movimento = (float(np.mean([np.abs(b - a).mean() for a, b in itertools.pairwise(cinzas)]))
                 if len(cinzas) > 1 else 0.0)
    return Clipe(caminho, arquivo, round(info.duracao, 3), quadros, round(movimento, 3))


def _jpeg(img: Image.Image, rotacao: int) -> bytes:
    if rotacao:
        img = img.rotate(rotacao, expand=True)
    img = img.convert("RGB")
    img.thumbnail((LADO, LADO), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def energias(movimentos: Sequence[float]) -> list[str]:
    """A energia de cada clipe pela posição dele entre os da biblioteca: a terça parte que
    menos mexe é "baixa", a que mais mexe, "alta". Com menos de 3 clipes, "media"."""
    if len(movimentos) < 3:
        return ["media"] * len(movimentos)
    ordem = sorted(range(len(movimentos)), key=lambda i: movimentos[i])
    saida = [""] * len(movimentos)
    for posicao, i in enumerate(ordem):
        terco = posicao * 3 // len(movimentos)
        saida[i] = ("baixa", "media", "alta")[terco]
    return saida


# ── o pedido ─────────────────────────────────────────────────────────────


def esquema() -> dict:
    cena = {"type": "object", "properties": {
        "k": {"type": "integer"},
        "descricao": {"type": "string"},
        "categorias": {"type": "array", "items": {"type": "string"}},
        "personagens": {"type": "array", "items": {"type": "string"}},
        "periodo": {"type": "string", "enum": list(PERIODOS)},
        "energia": {"type": "string", "enum": list(cenas_mod.ENERGIAS)},
        "monetizacao": {"type": "string", "enum": list(cenas_mod.MONETIZACOES)},
        "obs": {"type": "string"}},
        "required": ["k", "descricao", "categorias", "periodo", "energia", "monetizacao"]}
    return {"type": "object", "properties": {"cenas": {"type": "array", "items": cena}},
            "required": ["cenas"]}


def montar_pedido(lote: Sequence[Clipe], vocabulario: Sequence[str], assunto: str) -> str:
    linhas = "\n".join(f"- cena {k}: imagens {k * QUADROS_POR_CLIPE + 1} a "
                       f"{k * QUADROS_POR_CLIPE + QUADROS_POR_CLIPE} (arquivo \"{c.arquivo}\", "
                       f"{c.duracao:.1f} s)" for k, c in enumerate(lote))
    sobre = f"\nSobre o que são as cenas (dito por quem enviou): {assunto}\n" if assunto else ""
    usadas = ", ".join(vocabulario) if vocabulario else "nenhuma ainda"
    return f"""As imagens são quadros de {len(lote)} cenas curtas, {QUADROS_POR_CLIPE} por cena
(começo, meio e fim), na ordem:
{linhas}
{sobre}
Para cada cena ("k" é o número dela), devolva:
- descricao: o que aparece, em português, numa frase concreta de até 100 letras: quem,
  fazendo o quê, onde. Se o plano muda no meio, diga as duas coisas.
- categorias: de 1 a {CATEGORIAS_MAXIMAS} palavras em minúsculas, sem acento (acao, carro, praia,
  cidade, festa, close, dialogo, paisagem...). Reaproveite as que já existem quando
  servirem: {usadas}.
- personagens: os nomes de personagens que você reconhece com segurança (de um jogo,
  filme ou série, pelo assunto) ou que estejam escritos na tela; vazio se não souber.
- periodo: dia, entardecer, noite, interno (dentro de um lugar) ou n/a (cartela, tela).
- energia: o clima da cena, e não o movimento da câmera. alta: ação, perseguição,
  explosão, festa, multidão agitada. baixa: paisagem calma, cartela, close parado,
  conversa tranquila (um aéreo lento de paisagem é baixa). media: o resto.
- monetizacao: evitar (sexo, nudez, strip club, violência gráfica), cuidado (sensual,
  sugestivo, violência forte) ou ok.
- obs: o que atrapalha usar a cena de fundo (texto ou logo na tela, marca d'água, tarja
  preta, troca de plano no meio), ou para que ela serve bem. Vazio se nada.
"""


def _nua(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto).lower())
    return "".join(c for c in base if not unicodedata.combining(c))


def conferir(resposta: dict, lote: Sequence[Clipe]) -> dict[int, dict]:
    """As descrições que vieram certas, pelo número da cena no lote."""
    prontas: dict[int, dict] = {}
    for item in resposta.get("cenas") or []:
        if not isinstance(item, dict):
            continue
        k = item.get("k")
        descricao = re.sub(r"\s+", " ", str(item.get("descricao") or "")).strip()
        if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < len(lote) \
                or not descricao or k in prontas:
            continue
        categorias = []
        for c in item.get("categorias") or []:
            c = re.sub(r"[^a-z0-9 -]", "", _nua(c)).strip().replace(" ", "-")
            if c and c not in categorias:
                categorias.append(c)
        personagens = [str(p).strip() for p in item.get("personagens") or [] if str(p).strip()]
        periodo = item.get("periodo") if item.get("periodo") in PERIODOS else "n/a"
        energia = item.get("energia") if item.get("energia") in cenas_mod.ENERGIAS else ""
        monetizacao = (item.get("monetizacao") if item.get("monetizacao")
                       in cenas_mod.MONETIZACOES else "ok")
        prontas[k] = {"descricao": descricao[:DESCRICAO_MAXIMA],
                      "categorias": categorias[:CATEGORIAS_MAXIMAS],
                      "personagens": personagens[:4], "periodo": periodo,
                      "energia": energia, "monetizacao": monetizacao,
                      "obs": re.sub(r"\s+", " ", str(item.get("obs") or "")).strip()[:160]}
    return prontas


# ── o que já foi descrito ────────────────────────────────────────────────


def _guardadas_em() -> Path:
    return ia.pasta_de_dados() / "descricoes-de-cenas.json"


def _chave(clipe: Clipe, assunto: str) -> str:
    st = clipe.caminho.stat()
    return f"{clipe.caminho.name}|{st.st_size}|{int(st.st_mtime)}|{assunto.strip().lower()}"


def _ler_guardadas() -> dict[str, dict]:
    try:
        dados = json.loads(_guardadas_em().read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar(guardadas: dict[str, dict]) -> None:
    try:
        caminho = _guardadas_em()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        parcial = caminho.with_suffix(".parcial")
        parcial.write_text(json.dumps(guardadas, ensure_ascii=False), encoding="utf-8")
        parcial.replace(caminho)
    except OSError:
        logger.debug("não deu para guardar as descrições", exc_info=True)


# ── a geração ────────────────────────────────────────────────────────────


def _pelo_nome(clipe: Clipe) -> str:
    """A descrição do rascunho: o nome do arquivo, sem os números do começo ("t1-001-")
    e sem os hífens."""
    nome = re.sub(r"^(?:[a-z]*\d+[-_ ]*)+", "", clipe.caminho.stem, flags=re.I)
    nome = re.sub(r"[-_]+", " ", nome or clipe.caminho.stem).strip()
    return nome[:1].upper() + nome[1:] if nome else clipe.caminho.stem


def _rascunho(clipe: Clipe) -> dict:
    return {"descricao": _pelo_nome(clipe), "categorias": [], "personagens": [],
            "periodo": "n/a", "monetizacao": "ok", "obs": "descreva esta cena"}


def _falsa(clipe: Clipe) -> dict:
    return {"descricao": f"Cena de teste: {_pelo_nome(clipe)}", "categorias": ["teste"],
            "personagens": [], "periodo": "dia", "energia": "", "monetizacao": "ok",
            "obs": ""}


def gerar(clipes: Sequence[tuple[Path, str]], *, assunto: str = "",
          progresso: Progresso | None = None, parar: Callable[[], bool] = lambda: False,
          transporte=None) -> Geracao:
    """A matriz dos clipes (caminho, como vai no ``arquivo``), em ordem, com a energia
    medida e a descrição do Gemini (ou o rascunho, sem ele)."""
    lidos: list[Clipe] = []
    for caminho, arquivo in clipes:
        try:
            lidos.append(ler_clipe(Path(caminho), arquivo))
        except Exception:                       # um arquivo que não abre fica de fora
            logger.info("clipe ilegível: %s", caminho, exc_info=True)
    total = len(lidos)
    descricoes: dict[int, dict] = {}
    por, aviso, pedidos = "gemini", "", 0

    def avisar() -> None:
        if progresso:
            progresso(len(descricoes), total, pedidos)

    if ia.falsa():
        descricoes = {i: _falsa(c) for i, c in enumerate(lidos)}
        por = "falsa"
    elif not ia.ligada():
        por, aviso = "rascunho", ("sem a chave do Gemini, a descrição veio do nome de cada "
                                  "arquivo: revise na tabela")
    else:
        guardadas = _ler_guardadas()
        faltam: list[int] = []
        for i, c in enumerate(lidos):
            guardada = guardadas.get(_chave(c, assunto))
            if guardada:
                descricoes[i] = guardada
            else:
                faltam.append(i)
        avisar()
        vocabulario = sorted({cat for d in descricoes.values() for cat in d.get("categorias", [])})
        fila = [faltam[k:k + POR_PEDIDO] for k in range(0, len(faltam), POR_PEDIDO)]
        segunda_vez: set[int] = set()
        while fila and not parar():
            lote = fila.pop(0)
            clipes_do_lote = [lidos[i] for i in lote]
            gasto: list[str] = []
            try:
                resposta, _modelo = ia.perguntar_json(
                    SISTEMA, montar_pedido(clipes_do_lote, vocabulario[:60], assunto),
                    esquema(), temperatura=0.3, transporte=transporte, gasto=gasto,
                    imagens=[q for c in clipes_do_lote for q in c.quadros])
            except ia.Bloqueado:
                pedidos += len(gasto)
                if len(lote) > 1:                 # divide até achar a cena recusada
                    meio = len(lote) // 2
                    fila[:0] = [lote[:meio], lote[meio:]]
                else:
                    i = lote[0]
                    descricoes[i] = {**_rascunho(lidos[i]), "monetizacao": "evitar",
                                     "obs": "o Gemini não quis descrever esta cena "
                                            "(conteúdo sensível?): confira"}
                avisar()
                continue
            except ia.ErroDaIA as erro:
                pedidos += len(gasto)
                aviso = f"{erro} As cenas que faltam vieram do nome do arquivo: gere de novo "\
                        "depois, e só elas são pedidas."
                break
            pedidos += len(gasto)
            prontas = conferir(resposta, clipes_do_lote)
            for k, d in prontas.items():
                descricoes[lote[k]] = d
                guardadas[_chave(lidos[lote[k]], assunto)] = d
                for cat in d["categorias"]:
                    if cat not in vocabulario:
                        vocabulario.append(cat)
            _guardar(guardadas)
            # o que não veio volta uma vez, num lote só dele
            sem = [i for k, i in enumerate(lote) if k not in prontas and i not in segunda_vez]
            if sem:
                segunda_vez.update(sem)
                fila.append(sem)
            avisar()
        if parar() and not aviso:
            aviso = "a geração foi interrompida: as cenas que faltam vieram do nome do arquivo"
    # A energia do Gemini vale; sem ela (o rascunho), a do movimento medido.
    medidas = energias([c.movimento for c in lidos])
    cenas = []
    for i, c in enumerate(lidos):
        d = dict(descricoes.get(i) or _rascunho(c))
        if not d.get("energia"):
            d["energia"] = medidas[i]
        cenas.append({"id": c.caminho.stem, "arquivo": c.arquivo, **d, "duracao": c.duracao})
    if por == "gemini" and any(i not in descricoes for i in range(total)) and not aviso:
        aviso = "algumas cenas vieram sem descrição do Gemini: revise as marcadas"
    if progresso:
        progresso(total, total, pedidos)
    return Geracao(cenas, por, aviso, pedidos)


def clipes_relativos(pasta: Path) -> list[tuple[Path, str]]:
    """Os clipes da pasta (e das subpastas) com o caminho relativo a ela, como vai na
    matriz."""
    pasta = Path(pasta)
    return [(c, c.relative_to(pasta).as_posix()) for c in cenas_mod.clipes_da_pasta(pasta)]


__all__ = ["Clipe", "Geracao", "clipes_relativos", "conferir", "energias", "esquema",
           "gerar", "ler_clipe", "montar_pedido"]
