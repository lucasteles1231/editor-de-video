"""
O roteiro do vídeo: as cenas de cada bloco da fala (com a biblioteca de cenas) e os
cartões animados, escritos pelo Gemini num pedido só de texto.

No vídeo de referência, as duas coisas foram feitas à mão: as cenas escolhidas
bloco a bloco no catálogo, e os cartões presos às palavras da fala ("o 18 entra em
'nota 18', o carimbo cai em 'apagada'"). Aqui o Gemini faz esse papel; o editor confere
cada resposta (as cenas existem e não se repetem, os cartões têm os campos do modelo, as
palavras estão em ordem), manda consertar uma vez o que veio errado e tira o que
continuar errado.

**Sem o Gemini** (sem chave, sem cota ou fora do ar), as cenas são escolhidas pelas
palavras (``cenas.escolher_por_palavras``) e não há cartões: ficam os adesivos de
palavra de sempre. O motivo vai para o plano e para a página.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from editor import cenas as cenas_mod
from editor import censura, ia, plano
from editor.cartoes import MODELOS, Cartao, Item
from editor.transcricao import Palavra

logger = logging.getLogger(__name__)

#: Os cartões entram um tico antes da palavra: na tela, isso lê como "no tempo" (o chat
#: usava 100 ms).
ANTES_S = 0.1
#: Um cartão a cada 5 a 8 s de fala, como no vídeo do chat (8 em 49 s); cada um dura
#: entre estes limites, e o seguinte só entra depois do último momento do anterior.
CARTAO_A_CADA_S = (5.0, 8.0)
CARTAO_MINIMO_S = 1.5
CARTAO_MAXIMO_S = 7.0
DEPOIS_DO_ULTIMO_S = 1.0
#: Os destaques da legenda: no máximo 4 palavras cada, e uma pílula a cada tantos
#: segundos (o chat teve 7 em 49 s).
DESTAQUE_PALAVRAS = 4
PILULA_ESPACO_S = 3.0
#: Os limites de texto de cada campo (em letras).
LIMITES = {"selo": 30, "item": 26, "valor": 14, "carimbo": 14, "rotulo": 24, "destaque": 16,
           "titulo": 30}
ITENS = {"lista": (2, 4), "quadro": (2, 5), "enquete": (2, 2)}

SISTEMA = """Você é editor de vídeos curtos (Shorts, Reels, TikTok) de um canal de notícias
e curiosidades. Você não desenha: escolhe, entre opções fechadas, as cenas de fundo e os
cartões animados que uma montagem pronta vai desenhar, presos às palavras da fala.
Responda só com o JSON pedido."""


@dataclass
class Roteiro:
    blocos: list[cenas_mod.BlocoDeFala] = field(default_factory=list)
    #: Os ids das cenas de cada bloco (vazio sem biblioteca).
    escolhas: list[list[str]] = field(default_factory=list)
    cartoes: list[Cartao] = field(default_factory=list)
    #: Os destaques da legenda: (primeira palavra, última, "rosa", "ciano" ou "pilula").
    destaques: list[tuple[int, int, str]] = field(default_factory=list)
    #: Quem escolheu: "gemini", "palavras" ou "falsa" (a dos testes).
    por: str = ""
    #: Por que faltou algo ("sem a chave do Gemini…"), para a página.
    aviso: str = ""
    pedidos: int = 0
    modelo: str = ""

    def para_json(self) -> dict:
        return {"por": self.por, "aviso": self.aviso, "pedidos": self.pedidos,
                "modelo": self.modelo,
                "blocos": [{"inicio": b.inicio, "fim": b.fim, "texto": b.texto,
                            "cenas": list(e)} for b, e in
                           zip(self.blocos, self.escolhas or [[]] * len(self.blocos),
                               strict=False)],
                "cartoes": [c.para_json() for c in self.cartoes],
                "destaques": [list(d) for d in self.destaques]}


# ── o pedido ─────────────────────────────────────────────────────────────


def esquema(com_cenas: bool, nomes_de_icones: Sequence[str], destaques: bool = False
            ) -> dict:
    """O formato da resposta. Os ids de cena ficam fora de enum: um enum grande dá 400 no
    Gemini 3.x (visto em 03/10/2026)."""
    item = {"type": "object", "properties": {
        "texto": {"type": "string"}, "valor": {"type": "string"},
        "icone": {"type": "string"}, "palavra": {"type": "integer"}},
        "required": ["texto", "palavra"]}
    cartao = {"type": "object", "properties": {
        "modelo": {"type": "string", "enum": list(MODELOS)},
        "palavra": {"type": "integer"}, "ate": {"type": "integer"},
        "forte": {"type": "integer"},
        "texto": {"type": "string"}, "rotulo": {"type": "string"},
        "icone": {"type": "string"}, "cor": {"type": "string", "enum": list(ia.CORES)},
        "itens": {"type": "array", "items": item}},
        "required": ["modelo", "palavra", "texto"]}
    propriedades: dict = {"cartoes": {"type": "array", "items": cartao}}
    obrigatorios = ["cartoes"]
    if com_cenas:
        propriedades["cenas"] = {"type": "array", "items": {
            "type": "object", "properties": {
                "bloco": {"type": "integer"},
                "cenas": {"type": "array", "items": {"type": "string"}}},
            "required": ["bloco", "cenas"]}}
        obrigatorios.insert(0, "cenas")
    if destaques:
        propriedades["destaques"] = {"type": "array", "items": {
            "type": "object", "properties": {
                "de": {"type": "integer"}, "ate": {"type": "integer"},
                "estilo": {"type": "string", "enum": list(plano.DESTAQUES)}},
            "required": ["de", "ate", "estilo"]}}
        obrigatorios.append("destaques")
    return {"type": "object", "properties": propriedades, "required": obrigatorios}


def quantos_cartoes(duracao: float) -> tuple[int, int]:
    """De quantos a quantos cartões uma fala pede: um a cada 5 a 8 s."""
    menos = max(1, round(duracao / CARTAO_A_CADA_S[1]))
    return menos, max(menos, round(duracao / CARTAO_A_CADA_S[0]))


def montar_pedido(palavras: Sequence[Palavra], blocos: Sequence[cenas_mod.BlocoDeFala],
                  biblioteca: cenas_mod.Biblioteca | None, *, cartoes: bool, idioma: str,
                  nomes_de_icones: Sequence[str], proibidas: Sequence[str],
                  destaques: bool = False) -> str:
    fala = " ".join(f"[{i}] {w.texto}" for i, w in enumerate(palavras))
    partes = [f"""A FALA (cada palavra com o número dela, entre colchetes; idioma: {idioma}):
{fala}
"""]
    if biblioteca is not None:
        linhas_dos_blocos = "\n".join(
            f"- bloco {k}: {b.inicio:.1f}–{b.fim:.1f} s (palavras {b.primeira} a "
            f"{b.ultima}), precisa de {cenas_mod.cenas_por_bloco(b)} cena(s): \"{b.texto}\""
            for k, b in enumerate(blocos))
        catalogo = "\n".join(c.linha() for c in biblioteca.cenas)
        partes.append(f"""OS BLOCOS DA FALA (cada um precisa de cenas de fundo):
{linhas_dos_blocos}

AS CENAS DISPONÍVEIS (id | descrição | categorias | personagens | período | energia |
monetização | observações | duração):
{catalogo}

REGRAS DAS CENAS ("cenas": um item por bloco, com os ids na ordem em que tocam):
- Escolha as cenas que mostram o que está sendo dito: o assunto, o lugar, o personagem,
  a ação. Só ids da lista.
- Nunca repita uma cena no vídeo.
- Monetização "cuidado": no máximo {cenas_mod.CUIDADO_MAXIMO} no vídeo inteiro, e nunca
  no trecho que fala de sexo, drogas ou nudez. Nesses trechos, mostre algo que sugere sem
  mostrar (romance, balada, ação).
- Energia: o primeiro bloco (o gancho) pede cena de energia alta; trechos calmos aceitam
  energia baixa.
- Leia as observações: elas avisam de armadilhas (uma data antiga num logo, texto na
  tela). Cartelas de texto, só quando o assunto é aquele texto.
""")
    if cartoes:
        icones_ = ", ".join(nomes_de_icones)
        palavras_proibidas = ", ".join(proibidas) if proibidas else "nenhuma"
        duracao = palavras[-1].fim if palavras else 0.0
        menos, mais = quantos_cartoes(duracao)
        partes.append(f"""OS CARTÕES (animações por cima do vídeo, nos momentos fortes):
- selo: uma etiqueta inclinada com 1 a 5 palavras ("SEM CENSURA", "SEGUE PRA MAIS",
  "PEGI = CLASSIFICAÇÃO EUROPEIA"). Campos: texto, icone, cor.
- lista: 2 a 4 itens que entram um a um, cada um na palavra em que é dito. Campos: texto
  (um título curto, ou vazio), itens (texto, icone, palavra); cada item com um ícone do
  catálogo que combine com ele.
- quadro: um título e 2 a 5 linhas com nome e valor (país e nota, plataforma e preço),
  cada linha na palavra em que é dita. Campos: texto (o título), itens (texto, valor,
  palavra).
- enquete: as duas respostas de uma pergunta à audiência, cada uma na palavra em que é
  dita, primeiro o sim e depois o não. Campos: texto (a pergunta curta), itens (2),
  forte (a palavra do "comenta"/"deixa sua opinião").
- carimbo: um cartão com um rótulo curto ("404", "FICHA PEGI", "O POST") que recebe um
  carimbo vermelho com uma ou duas palavras ("APAGADA", "REMOVIDA DO AR") na palavra
  forte. Campos: rotulo, texto (o carimbo), forte.
- destaque: um número ou uma data grande ("18", "R$ 400", "19 DE NOVEMBRO") com um rótulo
  pequeno em cima. Campos: texto, rotulo, cor, forte (a palavra em que ele cai).
- flash: o flash de uma foto ("os fãs printaram"), seguido de um selo. Campos: texto (o
  selo), forte (a palavra do flash).

REGRAS DOS CARTÕES ("cartoes"):
- De {menos} a {mais} cartões (um a cada 5 a 8 segundos de fala), sem sobrepor: o
  seguinte só entra depois do último item ou do momento forte do anterior.
- O gancho: o vídeo começa com um selo na palavra 0, com 1 a 3 palavras que resumem a
  promessa do vídeo ("SEM CENSURA", "VAZOU TUDO").
- O fim: se a fala pede para seguir, comentar ou curtir, um selo entra nessa palavra
  ("SEGUE PRA MAIS", "COMENTA AÍ"), a não ser que uma enquete já esteja na tela.
- Um termo que nem todo mundo conhece pode ganhar um selo que explica
  ("PEGI = CLASSIFICAÇÃO EUROPEIA").
- "palavra" é o número da palavra em que o cartão entra; "ate" (opcional), a palavra em
  que ele sai; "forte", a do momento forte; os itens, cada um na sua palavra, em ordem.
- Textos em MAIÚSCULAS e curtos: selo até {LIMITES['selo']} letras, item até
  {LIMITES['item']}, valor até {LIMITES['valor']}, carimbo até {LIMITES['carimbo']},
  destaque até {LIMITES['destaque']}.
- Só fatos da fala, nada inventado. Prefira o modelo que combina com o que é dito (uma
  enumeração vira lista; uma comparação, quadro; uma pergunta à audiência, enquete).
- icone: um destes nomes, ou vazio: {icones_}.
- cor: {', '.join(ia.CORES)}.
- Palavras proibidas (escreva normalmente: o editor censura sozinho): {palavras_proibidas}.
""")
    else:
        partes.append('"cartoes": deixe a lista vazia.\n')
    if destaques:
        duracao = palavras[-1].fim if palavras else 0.0
        pilulas = (max(1, round(duracao / 8)), max(1, round(duracao / 6)))
        marcas = (max(1, round(duracao / 3)), max(1, round(duracao / 1.5)))
        partes.append(f"""OS DESTAQUES DA LEGENDA ("destaques"): trechos da fala que a legenda
pinta, pelos números das palavras ("de" e "ate", inclusive), de 1 a {DESTAQUE_PALAVRAS}
palavras cada. Para esta fala, de {marcas[0]} a {marcas[1]} trechos, sem sobrepor:
- pilula: a frase de efeito, que entra sozinha numa placa amarela ("não vai pegar leve",
  "nota 18", "fãs printaram tudo", "passou do ponto?", "19 de novembro"): de
  {pilulas[0]} a {pilulas[1]}, uma a cada 6 a 8 segundos.
- rosa: as expressões fortes ("página que foi apagada", "tirou do ar", "ainda nem
  avaliou", "danças privadas").
- ciano: nomes de pessoas, marcas, lugares e siglas ("Rockstar", "Estados Unidos").
""")
    return "\n".join(partes)


# ── a conferência ────────────────────────────────────────────────────────


def _tempo(palavras: Sequence[Palavra], i) -> float | None:
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(palavras):
        return None
    return max(0.0, palavras[i].inicio - ANTES_S)


def _curto(texto, limite: int) -> str:
    texto = re.sub(r"\s+", " ", str(texto or "")).strip().upper()
    return texto[:limite].rstrip() if len(texto) > limite else texto


def conferir_cenas(resposta: dict, blocos: Sequence[cenas_mod.BlocoDeFala],
                   biblioteca: cenas_mod.Biblioteca) -> tuple[list[list[str]], list[str]]:
    """As cenas de cada bloco que passam, e os problemas do resto."""
    por_id = biblioteca.por_id()
    escolhas: list[list[str]] = [[] for _ in blocos]
    problemas: list[str] = []
    usadas: set[str] = set()
    cuidado = 0
    for item in resposta.get("cenas") or []:
        if not isinstance(item, dict):
            continue
        k = item.get("bloco")
        if not isinstance(k, int) or not 0 <= k < len(blocos):
            problemas.append(f"bloco {k!r} não existe")
            continue
        for i in item.get("cenas") or []:
            i = str(i)
            if i not in por_id:
                problemas.append(f"bloco {k}: a cena {i!r} não está na lista")
            elif i in usadas:
                problemas.append(f"bloco {k}: a cena {i} já foi usada")
            elif por_id[i].monetizacao == "cuidado" and cuidado >= cenas_mod.CUIDADO_MAXIMO:
                problemas.append(f"bloco {k}: cenas 'cuidado' demais ({i})")
            else:
                cuidado += por_id[i].monetizacao == "cuidado"
                usadas.add(i)
                escolhas[k].append(i)
    for k, e in enumerate(escolhas):
        if not e:
            problemas.append(f"o bloco {k} ficou sem cena")
    return escolhas, problemas


def conferir_cartoes(resposta: dict, palavras: Sequence[Palavra], duracao: float,
                     nomes_de_icones: set[str], proibidas: Sequence[str]
                     ) -> tuple[list[Cartao], list[str]]:
    """Os cartões que passam (em ordem, sem sobrepor, com os tempos), e os problemas."""
    prontos: list[Cartao] = []
    problemas: list[str] = []
    for n, bruto in enumerate(resposta.get("cartoes") or []):
        if not isinstance(bruto, dict):
            continue
        cartao, erro = _um_cartao(bruto, palavras, nomes_de_icones, proibidas)
        if erro:
            problemas.append(f"cartão {n} ({bruto.get('modelo')}): {erro}")
        elif cartao is not None:
            prontos.append(cartao)
    prontos.sort(key=lambda c: c.inicio)
    finais: list[Cartao] = []
    for c in prontos:
        if finais and c.inicio < _livre_a_partir(finais[-1]):
            problemas.append(f"o {c.modelo} em {c.inicio:.1f} s entra antes de o "
                             f"{finais[-1].modelo} de {finais[-1].inicio:.1f} s terminar")
            continue
        finais.append(c)
    # Cada um vai até o próximo (ou até onde a fala pediu), entre os limites.
    for j, c in enumerate(finais):
        proximo = finais[j + 1].inicio if j + 1 < len(finais) else duracao
        ultimo_item = max([i.em for i in c.itens] + [c.forte or c.inicio])
        fim = min(c.fim, proximo, c.inicio + CARTAO_MAXIMO_S, duracao)
        c.fim = max(fim, min(proximo, duracao, max(c.inicio + CARTAO_MINIMO_S,
                                                   ultimo_item + 1.2)))
    return [c for c in finais if c.fim - c.inicio >= 0.6], problemas


def conferir_destaques(resposta: dict, palavras: Sequence[Palavra]
                       ) -> list[tuple[int, int, str]]:
    """Os destaques que passam: dentro da fala, em ordem, sem sobrepor, de até 4
    palavras, e as pílulas espaçadas. O resto sai calado (é só a cor da legenda: não
    vale um pedido de conserto)."""
    brutos = []
    for d in resposta.get("destaques") or []:
        if not isinstance(d, dict):
            continue
        de, ate, estilo = d.get("de"), d.get("ate"), d.get("estilo")
        if (isinstance(de, int) and isinstance(ate, int) and not isinstance(de, bool)
                and 0 <= de <= ate < len(palavras) and ate - de < DESTAQUE_PALAVRAS
                and estilo in plano.DESTAQUES):
            brutos.append((de, ate, estilo))
    prontos: list[tuple[int, int, str]] = []
    ultima_pilula = -math.inf
    for de, ate, estilo in sorted(brutos):
        if prontos and de <= prontos[-1][1]:
            continue
        if estilo == "pilula":
            if palavras[de].inicio - ultima_pilula < PILULA_ESPACO_S:
                estilo = "rosa"                 # perto demais da outra: fica só a cor
            else:
                ultima_pilula = palavras[de].inicio
        prontos.append((de, ate, estilo))
    return prontos


def _livre_a_partir(c: Cartao) -> float:
    """Quando o cartão seguinte já pode entrar: com o anterior lido (o mínimo dele) e
    depois do último item ou do momento forte dele."""
    ultimo = max([i.em for i in c.itens] + [c.forte if c.forte is not None else c.inicio])
    return max(c.inicio + CARTAO_MINIMO_S, ultimo + DEPOIS_DO_ULTIMO_S)


def _um_cartao(bruto: dict, palavras: Sequence[Palavra], nomes_de_icones: set[str],
               proibidas: Sequence[str]) -> tuple[Cartao | None, str]:
    modelo = bruto.get("modelo")
    if modelo not in MODELOS:
        return None, "modelo desconhecido"
    inicio = _tempo(palavras, bruto.get("palavra"))
    if inicio is None:
        return None, "a palavra de entrada não existe"
    ate = _tempo(palavras, bruto.get("ate"))
    forte = _tempo(palavras, bruto.get("forte"))
    cor = bruto.get("cor") if bruto.get("cor") in ia.CORES else "amarelo"
    icone = str(bruto.get("icone") or "")
    icone = icone if icone in nomes_de_icones else ""
    limite = {"selo": "selo", "carimbo": "carimbo", "destaque": "destaque",
              "flash": "selo"}.get(modelo, "titulo")
    texto = censura.censurar_texto(_curto(bruto.get("texto"), LIMITES[limite]), proibidas)
    rotulo = censura.censurar_texto(_curto(bruto.get("rotulo"), LIMITES["rotulo"]), proibidas)
    itens: list[Item] = []
    for bruto_item in bruto.get("itens") or []:
        if not isinstance(bruto_item, dict):
            continue
        em = _tempo(palavras, bruto_item.get("palavra"))
        if em is None or em < inicio:
            return None, "um item está fora da fala ou antes do cartão"
        if itens and em <= itens[-1].em:
            return None, "os itens não estão em ordem"
        nome = str(bruto_item.get("icone") or "")
        itens.append(Item(
            censura.censurar_texto(_curto(bruto_item.get("texto"), LIMITES["item"]), proibidas),
            em, censura.censurar_texto(_curto(bruto_item.get("valor"), LIMITES["valor"]),
                                       proibidas),
            nome if nome in nomes_de_icones else ""))
    if modelo in ITENS:
        minimo, maximo = ITENS[modelo]
        if not minimo <= len(itens) <= maximo:
            return None, f"pede de {minimo} a {maximo} itens, vieram {len(itens)}"
        if any(not i.texto for i in itens):
            return None, "um item veio sem texto"
    elif not texto:
        return None, "veio sem texto"
    if modelo == "carimbo" and not rotulo:
        rotulo = "PÁGINA"
    if modelo in ("carimbo", "destaque", "flash") and forte is None:
        forte = inicio if modelo != "carimbo" else min(inicio + 0.6, palavras[-1].fim)
    if forte is not None and forte < inicio:
        forte = inicio
    if modelo == "selo" and forte is None and bruto.get("palavra") == 0:
        forte = inicio                                  # o selo do gancho entra carimbado
    fim = ate if ate is not None and ate > inicio else inicio + CARTAO_MAXIMO_S
    return Cartao(modelo, inicio, fim, texto, rotulo, icone, cor, itens, forte), ""


# ── a escrita ────────────────────────────────────────────────────────────


def _falsos(palavras: Sequence[Palavra], duracao: float) -> list[dict]:
    """Os cartões da IA falsa (testes e quem desenvolve sem chave): um de cada modelo
    principal, espalhados pela fala."""
    n = len(palavras)
    if n < 16:
        return [{"modelo": "selo", "palavra": 0, "texto": "ATENÇÃO", "icone": "alerta",
                 "cor": "rosa"}] if n else []
    q = n // 6
    return [
        {"modelo": "selo", "palavra": 0, "texto": "ATENÇÃO", "icone": "alerta", "cor": "rosa"},
        {"modelo": "lista", "palavra": q, "texto": "", "itens": [
            {"texto": "PRIMEIRO", "palavra": q}, {"texto": "SEGUNDO", "palavra": q + 2},
            {"texto": "TERCEIRO", "palavra": q + 4}]},
        {"modelo": "carimbo", "palavra": 2 * q, "rotulo": "404", "texto": "APAGADA",
         "forte": 2 * q + 2},
        {"modelo": "quadro", "palavra": 3 * q, "texto": "COMPARAÇÃO", "itens": [
            {"texto": "UM", "valor": "10", "palavra": 3 * q},
            {"texto": "DOIS", "valor": "20", "palavra": 3 * q + 2}]},
        {"modelo": "enquete", "palavra": 4 * q, "texto": "E AÍ?", "forte": 4 * q + 4,
         "itens": [{"texto": "SIM", "palavra": 4 * q + 1},
                   {"texto": "NÃO", "palavra": 4 * q + 2}]},
        {"modelo": "destaque", "palavra": 5 * q, "texto": "19 DE NOVEMBRO",
         "rotulo": "LANÇAMENTO", "cor": "rosa", "forte": 5 * q + 1},
    ]


def _sem_repetir(escolhas: Sequence[Sequence[str]], reserva: Sequence[Sequence[str]]
                 ) -> list[list[str]]:
    """As cenas de cada bloco sem repetir no vídeo: a junção da resposta com o conserto
    pode repetir. Um bloco que fica vazio pega as da reserva (a escolha pelas palavras)
    que ainda não tocaram, ou as da reserva mesmo assim."""
    usadas: set[str] = set()
    saida: list[list[str]] = []
    for e, r in zip(escolhas, reserva, strict=True):
        novas = ([i for i in e if i not in usadas] or [i for i in r if i not in usadas]
                 or list(r))
        usadas.update(novas)
        saida.append(novas)
    return saida


def escrever(palavras: Sequence[Palavra], duracao: float, *,
             biblioteca: cenas_mod.Biblioteca | None, cartoes: bool, idioma: str,
             nomes_de_icones: Sequence[str], proibidas: Sequence[str] = (),
             destaques: bool = False, transporte=None) -> Roteiro:
    """O roteiro do vídeo: as cenas (com a ``biblioteca``), os cartões (com
    ``cartoes``) e os destaques da legenda (com ``destaques``), pelo Gemini ou, sem ele,
    pelas palavras."""
    blocos = cenas_mod.blocos_da_fala(palavras, duracao) if biblioteca is not None else []
    roteiro = Roteiro(blocos=blocos)
    if biblioteca is None and not cartoes and not destaques:
        return roteiro
    nomes = set(nomes_de_icones)

    def pelas_palavras(aviso: str) -> Roteiro:
        roteiro.escolhas = (cenas_mod.escolher_por_palavras(blocos, biblioteca)
                            if biblioteca is not None else [])
        roteiro.destaques = plano.destaques_pelas_palavras(palavras) if destaques else []
        roteiro.cartoes, roteiro.por, roteiro.aviso = [], "palavras", aviso
        return roteiro

    if ia.falsa():
        roteiro.escolhas = (cenas_mod.escolher_por_palavras(blocos, biblioteca)
                            if biblioteca is not None else [])
        if cartoes:
            roteiro.cartoes, _ = conferir_cartoes({"cartoes": _falsos(palavras, duracao)},
                                                  palavras, duracao, nomes, proibidas)
        if destaques:
            roteiro.destaques = conferir_destaques({"destaques": [
                {"de": 0, "ate": 0, "estilo": "ciano"},
                {"de": 2, "ate": 3, "estilo": "pilula"},
                {"de": 5, "ate": 6, "estilo": "rosa"}]}, palavras)
        roteiro.por = "falsa"
        return roteiro
    if not palavras:
        return pelas_palavras("sem fala, não há o que o Gemini ler")
    if not ia.ligada():
        return pelas_palavras("sem a chave do Gemini, as cenas foram escolhidas pelas "
                              "palavras e não há cartões")

    pedido = montar_pedido(palavras, blocos, biblioteca, cartoes=cartoes, idioma=idioma,
                           nomes_de_icones=sorted(nomes), proibidas=proibidas,
                           destaques=destaques)
    formato = esquema(biblioteca is not None, sorted(nomes), destaques)
    gasto: list[str] = []
    try:
        resposta, modelo = ia.perguntar_json(SISTEMA, pedido, formato, temperatura=0.7,
                                             transporte=transporte, gasto=gasto)
    except ia.ErroDaIA as erro:
        logger.info("roteiro sem Gemini: %s", erro)
        return pelas_palavras(f"o Gemini não respondeu ({erro}); as cenas foram escolhidas "
                              "pelas palavras e não há cartões")

    escolhas, problemas = (conferir_cenas(resposta, blocos, biblioteca)
                           if biblioteca is not None else ([], []))
    prontos, ruins = (conferir_cartoes(resposta, palavras, duracao, nomes, proibidas)
                      if cartoes else ([], []))
    marcas = conferir_destaques(resposta, palavras) if destaques else []
    problemas += ruins
    if problemas:
        logger.info("conserto do roteiro: %s", " | ".join(problemas))
        conserto = (pedido + "\n\nA RESPOSTA ANTERIOR TEVE ESTES PROBLEMAS. Mande o JSON "
                    "inteiro de novo, corrigido:\n" + "\n".join(f"- {p}" for p in problemas)
                    + "\n\nA resposta anterior:\n" + json.dumps(resposta, ensure_ascii=False))
        try:
            resposta2, modelo = ia.perguntar_json(SISTEMA, conserto, formato, temperatura=0.4,
                                                  transporte=transporte, gasto=gasto)
            if biblioteca is not None:
                escolhas2, _ = conferir_cenas(resposta2, blocos, biblioteca)
                escolhas = [b or a for a, b in zip(escolhas, escolhas2, strict=True)]
            if cartoes:
                prontos2, _ = conferir_cartoes(resposta2, palavras, duracao, nomes, proibidas)
                prontos = prontos2 if len(prontos2) >= len(prontos) else prontos
            if destaques:
                marcas2 = conferir_destaques(resposta2, palavras)
                marcas = marcas2 if len(marcas2) >= len(marcas) else marcas
        except ia.ErroDaIA:
            logger.info("o conserto não veio; fica o que já estava bom")
    if biblioteca is not None:
        escolhas = _sem_repetir(escolhas, cenas_mod.escolher_por_palavras(blocos, biblioteca))
    roteiro.escolhas, roteiro.cartoes = escolhas, prontos
    if destaques:   # sem nenhum do Gemini, os das palavras: a legenda não fica sem cor
        roteiro.destaques = marcas or plano.destaques_pelas_palavras(palavras)
    roteiro.por, roteiro.pedidos, roteiro.modelo = "gemini", len(gasto), modelo
    return roteiro


__all__ = ["ANTES_S", "SISTEMA", "Roteiro", "conferir_cartoes", "conferir_cenas",
           "conferir_destaques", "escrever", "esquema", "montar_pedido", "quantos_cartoes"]
