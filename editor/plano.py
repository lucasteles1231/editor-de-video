"""
O plano de edição: tudo o que o editor decide, antes de desenhar um quadro.

Nada aqui chama modelo de IA. As decisões são regras — as mesmas que o canal
Instituto Palito usa nos Shorts dele:

- **blocos de legenda**: uma linha curta, que quebra em pontuação e em pausa e
  nunca termina numa palavra que pede a seguinte ("e", "de", "não"...);
- **palavra-chave** de cada bloco: a mais longa que não é palavra de serviço;
- **adesivos**: a palavra que salta da legenda — número primeiro, depois nome
  próprio, depois palavra-chave longa —, com espaço entre um e outro;
- **zoom**: alterna entre perto e normal nos cortes;
- **ícones**: quando a fala cita uma coisa que tem desenho na biblioteca;
- **sons**: um som quando algo aparece, outro quando o zoom troca, um por palavra
  ("dinheiro" chama moedas) e, se pedido, um curto em cada corte — todos do tema
  escolhido (ver ``editor/sons.py``);
- **ritmo**: um multiplicador que encurta ou alonga o espaço entre os efeitos;
- **a pessoa que muda de lugar** (na montagem em camadas): em alguns cortes, os de
  ênfase, ela vai para um lado, o meio, para cima, para baixo, para perto ou para longe.
"""
from __future__ import annotations

import functools
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from editor.opcoes import OpcoesDeEdicao
from editor.transcricao import Palavra

# ── Legenda ──────────────────────────────────────────────────────────────

#: Quantos caracteres cabem numa linha de legenda.
TETO_VERTICAL = 18
TETO_HORIZONTAL = 32
#: Uma pausa maior que isto entre duas palavras quebra o bloco.
PAUSA_QUEBRA_S = 0.30
#: Uma vírgula quebra o bloco se ele já tem pelo menos metade do teto.
FIM_DE_FRASE = (".", "?", "!", "…")
#: Se a próxima fala demora mais que isto, o bloco some antes dela.
SOME_DEPOIS_S = 0.60
SEGURA_S = 0.30

#: Os estilos da legenda: "classica" (uma linha, karaokê) e "destaques" (a do vídeo de
#: referência): páginas de até 4 palavras, que entram uma a uma, com as cores dos
#: destaques e a frase de efeito numa pílula amarela.
ESTILOS_DA_LEGENDA = ("classica", "destaques")
#: As cores de um destaque: "rosa" (expressão forte), "ciano" (nome, marca, lugar) e
#: "pilula" (a frase de efeito, sozinha numa placa).
DESTAQUES = ("rosa", "ciano", "pilula")
#: A página quebra em 4 palavras, na vírgula e no ponto, em 1,7 s ou numa pausa maior
#: que 350 ms; uma de uma ou duas palavras com menos de meio segundo junta com a vizinha.
PAGINA_PALAVRAS = 4
PAGINA_MAXIMA_S = 1.7
PAGINA_PAUSA_S = 0.35
PAGINA_CURTA_S = 0.5
#: A página entra 80 ms antes da primeira palavra e fica 450 ms depois da última (ou até
#: 30 ms antes da seguinte).
PAGINA_ANTES_S = 0.08
PAGINA_DEPOIS_S = 0.45

#: Palavras que não podem terminar um bloco: anunciam a seguinte e não significam
#: nada sozinhas. Num karaokê o olho chega no "e se" e fica esperando o resto.
PENDURADAS = frozenset({
    "e", "ou", "mas", "que", "se", "de", "do", "da", "dos", "das", "em",
    "no", "na", "nos", "nas", "a", "o", "as", "os", "um", "uma", "uns",
    "umas", "ao", "aos", "à", "às", "por", "para", "com", "sem", "sob",
    "sobre", "entre", "como", "quando", "onde", "porque", "pois", "nem",
    "até", "ate", "desde", "durante", "após", "apos", "perante", "conforme",
    "pelo", "pela", "pelos", "pelas", "num", "numa", "seu", "sua", "meu",
    "minha", "este", "esta", "esse", "essa", "aquele", "aquela", "ser",
    "não", "nao", "nunca", "jamais",
    "é", "são", "sao", "foi", "foram", "era", "eram", "está", "estão", "estao",
    "tem", "têm", "tinha", "vai", "vão", "vao", "pode", "podem", "deve", "devem",
    "fica", "ficam",
    "todo", "toda", "todos", "todas", "outro", "outra", "outros", "outras",
    "cada", "qualquer", "muito", "muita", "muitos", "muitas", "tão", "tao",
})

#: Palavras que nunca são o assunto da frase, mesmo sendo compridas.
VAZIAS = frozenset({
    "que", "para", "porque", "quando", "como", "onde", "quem", "qual",
    "próprio", "proprio", "própria", "propria", "próprios", "proprios",
    "próprias", "proprias", "inteiro", "inteira", "inteiros", "inteiras",
    "próximo", "proximo", "próxima", "proxima", "próximos", "proximos",
    "próximas", "proximas", "mesmo", "mesma", "mesmos", "mesmas",
    "original", "originais", "grande", "grandes", "pequeno", "pequena",
    "simples", "comum", "comuns", "qualquer", "quaisquer", "consegue",
    "conseguem", "chamado", "chamada", "chamados", "chamadas",
    "mas", "porem", "porém", "entao", "então", "assim", "ainda", "sempre",
    "nunca", "muito", "pouco", "mais", "menos", "cada", "todo", "toda",
    "todos", "todas", "outro", "outra", "este", "esta", "isso", "aquilo",
    "esse", "essa", "aqui", "ali", "com", "sem", "por", "pelo", "pela",
    "dos", "das", "nos", "nas", "uma", "uns", "umas", "seu", "sua", "seus",
    "suas", "ele", "ela", "eles", "elas", "voce", "você", "nao", "não",
    "sao", "são", "está", "estao", "estão", "tem", "temos", "ser", "estar",
    "fica", "vira", "pode", "podem", "vai", "vao", "vão", "foi", "foram",
    "depois", "antes", "durante", "sobre", "entre", "desde", "ate", "até",
})
#: Abaixo de quatro letras não há substantivo que mereça a única cor do quadro.
MINIMO_DA_CHAVE = 4

# ── Adesivos, zoom, ícones, sons ─────────────────────────────────────────

ADESIVO_ESPACO_S = 4.0
ADESIVO_A_CADA_S = 12.0
ADESIVO_MINIMO_S = 0.5
ZOOM_ESPACO_S = 2.5
ICONE_ESPACO_S = 5.0
ICONE_DURA_S = 1.5
WHOOSH_ESPACO_S = 6.0
SOM_ESPACO_S = 0.25
#: Os sons de palavra ficam pelo menos isto um do outro; os de corte, isto.
SOM_DE_PALAVRA_ESPACO_S = 4.0
SOM_DE_CORTE_ESPACO_S = 1.5
#: O som de corte não toca colado numa transição (os dois marcam o mesmo pulo).
CORTE_LONGE_DA_TRANSICAO_S = 0.2
#: O empurrão de zoom no adesivo, sem escolha: 6%.
EMPURRAO_PADRAO = 0.06

#: Outras palavras que chamam um ícone.
SINONIMOS = {
    "grana": "dinheiro", "reais": "dinheiro", "dolar": "dinheiro", "dolares": "dinheiro",
    "pix": "celular", "telefone": "celular", "smartphone": "celular", "iphone": "celular",
    "internet": "wifi", "agua": "gota", "ideia": "lampada", "ideias": "lampada",
    "senha": "chave", "senhas": "chave", "seguranca": "escudo", "compras": "carrinho",
    "jogo": "controle", "jogos": "controle", "videogame": "controle", "game": "controle",
    "games": "controle", "foto": "camera", "fotos": "camera", "medico": "hospital",
    "medicos": "hospital", "inteligencia": "robo", "carta": "email", "cartas": "email",
    "aula": "escola", "aulas": "escola", "professor": "escola",
}
# ── A pessoa que muda de lugar ───────────────────────────────────────────

#: As posições sem motivo próprio, na ordem em que se revezam. Com um ícone no trecho, a
#: pessoa vai para o lado oposto ao dele; com um adesivo, vem para perto. Deitado, a casa
#: é embaixo à direita, então o meio entra na fila.
ORDEM_VERTICAL = ("longe", "esquerda", "cima", "direita", "baixo", "perto")
ORDEM_HORIZONTAL = ("meio", "esquerda", "longe", "cima", "perto", "baixo")
POSICOES = frozenset(ORDEM_VERTICAL + ORDEM_HORIZONTAL)
#: Um trecho entre cortes mais curto que isto fica como está: a pessoa mal chegaria.
MOVER_MINIMO_S = 1.2
#: O mais longo: passou disso, ela volta sozinha, deslizando.
MOVER_MAXIMO_S = 5.0
#: O mínimo entre a volta de um e a saída do próximo.
MOVER_ESPACO_S = 2.5
#: Sem ênfase, ela sai do lugar quando já está parada há tanto tempo.
MOVER_PARADA_S = 4.5
#: Nada no primeiro segundo.
MOVER_DO_COMECO_S = 1.0

#: Nomes de ícone que são palavras comuns demais ou ambíguas ("dado", "certo").
NAO_CHAMAM = frozenset({"certo", "errado", "sobe", "desce", "lugar", "dado", "pessoa",
                        "pessoas", "video", "joinha", "alerta", "chave", "folha", "planta"})


def _sem_acento(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in plano if not unicodedata.combining(c))


def nua(palavra: str) -> str:
    """A palavra sem pontuação e em minúsculas, para comparar com as listas."""
    return re.sub(r"[^0-9a-zà-ú]", "", palavra.lower())


def _pendurada(palavra: str) -> bool:
    return palavra.strip(",.;:!?\"'()—–-").lower() in PENDURADAS


def _e_adverbio(n: str) -> bool:
    return len(n) >= 6 and n.endswith("mente")


def chave(palavras: Sequence[str]) -> int:
    """A palavra-chave de um bloco: a mais longa que não é de serviço; ``-1`` se nenhuma."""
    melhor, tamanho = -1, 0
    for i, w in enumerate(palavras):
        n = nua(w)
        if len(n) < MINIMO_DA_CHAVE or n in VAZIAS or _e_adverbio(n):
            continue
        if len(n) > tamanho:
            melhor, tamanho = i, len(n)
    return melhor


@dataclass
class Bloco:
    palavras: list[Palavra]
    inicio: float
    fim: float
    chave: int = -1
    #: Se a primeira palavra abre uma frase (para distinguir nome próprio).
    abre_frase: list[bool] = field(default_factory=list)
    #: "classica", ou, na legenda "destaques", "linha" ou "pilula".
    tipo: str = "classica"
    #: Na legenda "destaques", o destaque de cada palavra ("" é a comum).
    estilos: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palavras)


@dataclass
class Adesivo:
    bloco: int
    palavra: int
    inicio: float
    fim: float
    #: 0 a 3: a forma (balão ou estrela) e a cor, alternando.
    estilo: int


@dataclass
class Icone:
    nome: str
    inicio: float
    fim: float
    #: -1 à esquerda, 1 à direita.
    lado: int


@dataclass
class Som:
    nome: str
    t: float
    #: O volume deste som em relação aos outros (o corte entra mais baixo).
    ganho: float = 1.0


@dataclass
class Movimento:
    """Um trecho em que a pessoa sai do lugar. Ele sempre começa num corte."""

    inicio: float
    fim: float
    posicao: str
    #: Se acaba num corte: ela volta de uma vez, e o corte esconde a volta. Senão, volta
    #: deslizando.
    volta_no_corte: bool = True


@dataclass
class Plano:
    duracao: float
    vertical: bool
    blocos: list[Bloco]
    adesivos: list[Adesivo]
    #: (instante, nível): o nível de zoom vale a partir do instante.
    zoom: list[tuple[float, float]]
    #: (início, fim) dos empurrões de zoom nos adesivos.
    empurroes: list[tuple[float, float]]
    icones: list[Icone]
    sons: list[Som]
    #: Os instantes do vídeo editado em que houve corte.
    cortes: list[float] = field(default_factory=list)
    #: Os trechos do vídeo original que ficaram (início, fim).
    trechos: list[tuple[float, float]] = field(default_factory=list)
    #: Onde a pessoa sai do lugar (vazio com a opção desligada).
    movimentos: list[Movimento] = field(default_factory=list)
    #: O quanto o adesivo empurra o zoom (0,06 = 6%).
    forca_do_empurrao: float = EMPURRAO_PADRAO
    #: Os cartões animados (``editor/cartoes.py``), escritos pelo Gemini.
    cartoes: list = field(default_factory=list)
    #: O que o roteiro decidiu: as cenas de cada bloco, quem escolheu e por quê.
    roteiro: dict = field(default_factory=dict)
    #: Onde a voz leva bipe, no tempo do vídeo editado.
    bipes: list[tuple[float, float]] = field(default_factory=list)

    def para_json(self) -> dict:
        dados = asdict(self)
        for b in dados["blocos"]:
            b["texto"] = " ".join(p["texto"] for p in b["palavras"])
        return dados


def montar_blocos(palavras: Sequence[Palavra], duracao: float, teto: int) -> list[Bloco]:
    """As palavras em blocos de legenda, cada um com o tempo em que fica na tela."""
    abre = [i == 0 or palavras[i - 1].texto.rstrip().endswith(FIM_DE_FRASE)
            for i in range(len(palavras))]
    grupos: list[list[int]] = []
    atual: list[int] = []

    def texto(ids: list[int]) -> str:
        return " ".join(palavras[i].texto for i in ids)

    for i, w in enumerate(palavras):
        if atual:
            ultima = palavras[atual[-1]]
            pausa = w.inicio - ultima.fim
            if (pausa > PAUSA_QUEBRA_S or ultima.texto.rstrip().endswith(FIM_DE_FRASE)
                    or (ultima.texto.endswith(",") and len(texto(atual)) >= teto // 2)):
                grupos.append(atual)
                atual = [i]
                continue
            if len(texto([*atual, i])) > teto:
                fechado, devolver = list(atual), []
                while len(fechado) > 1 and _pendurada(palavras[fechado[-1]].texto):
                    devolver.insert(0, fechado.pop())
                if devolver and len(texto([*devolver, i])) <= teto:
                    grupos.append(fechado)
                    atual = [*devolver, i]
                else:
                    grupos.append(atual)
                    atual = [i]
                continue
        atual.append(i)
    if atual:
        grupos.append(atual)

    blocos = []
    for k, ids in enumerate(grupos):
        ws = [palavras[i] for i in ids]
        if k + 1 < len(grupos):
            proxima = palavras[grupos[k + 1][0]].inicio
            fim = proxima if proxima - ws[-1].fim <= SOME_DEPOIS_S else ws[-1].fim + SEGURA_S
        else:
            fim = min(duracao, ws[-1].fim + SEGURA_S + 0.1)
        blocos.append(Bloco(ws, ws[0].inicio, max(fim, ws[-1].fim), chave([w.texto for w in ws]),
                            [abre[i] for i in ids]))
    return blocos


def destaques_pelas_palavras(palavras: Sequence[Palavra]) -> list[tuple[int, int, str]]:
    """Os destaques sem o Gemini: ciano nos nomes próprios (seguidos viram um só:
    "Estados Unidos"), rosa nos números e na palavra-chave longa de cada bloco. Sem
    pílula: a frase de efeito pede quem entenda a fala."""
    abre = [i == 0 or palavras[i - 1].texto.rstrip().endswith(FIM_DE_FRASE)
            for i in range(len(palavras))]
    marcas: dict[int, str] = {}
    for i, w in enumerate(palavras):
        n = nua(w.texto)
        if any(c.isdigit() for c in w.texto):
            marcas[i] = "ciano" if marcas.get(i - 1) == "ciano" else "rosa"   # "GTA 6"
        elif w.texto[:1].isupper() and not abre[i] and len(n) >= 3 and n not in VAZIAS:
            marcas[i] = "ciano"
    inicio = 0
    for b in montar_blocos(palavras, palavras[-1].fim if palavras else 0.0, TETO_VERTICAL):
        if b.chave >= 0 and len(nua(b.palavras[b.chave].texto)) >= 6:
            marcas.setdefault(inicio + b.chave, "rosa")
        inicio += len(b.palavras)
    trechos: list[tuple[int, int, str]] = []
    for i in sorted(marcas):
        if trechos and trechos[-1][1] == i - 1 and trechos[-1][2] == marcas[i] == "ciano" \
                and i - trechos[-1][0] < PAGINA_PALAVRAS:
            trechos[-1] = (trechos[-1][0], i, "ciano")
        else:
            trechos.append((i, i, marcas[i]))
    return trechos


def montar_paginas(palavras: Sequence[Palavra], duracao: float,
                   destaques: Sequence[tuple[int, int, str]]) -> list[Bloco]:
    """A legenda "destaques" (``full-track.mjs`` do chat): as palavras em páginas de até
    4, a frase de efeito numa página sozinha, e o destaque de cada palavra."""
    n = len(palavras)
    estilo = [""] * n
    pilulas: dict[int, int] = {}
    for de, ate, qual in destaques:
        if 0 <= de <= ate < n and qual in DESTAQUES:
            for i in range(de, ate + 1):
                estilo[i] = qual
            if qual == "pilula":
                pilulas[de] = ate
    paginas: list[list] = []                   # [tipo, primeira, última]
    i = 0
    while i < n:
        if i in pilulas:
            paginas.append(["pilula", i, pilulas[i]])
            i = pilulas[i] + 1
            continue
        j, conta = i, 0
        while j < n:
            if j > i and j in pilulas:
                break
            conta += 1
            fecha = palavras[j].texto.strip().endswith((".", ",", "!", "?", "…"))
            dura = palavras[j].fim - palavras[i].inicio
            folga = palavras[j + 1].inicio - palavras[j].fim if j + 1 < n else math.inf
            j += 1
            if (conta >= PAGINA_PALAVRAS or fecha or dura >= PAGINA_MAXIMA_S
                    or folga > PAGINA_PAUSA_S):
                break
        paginas.append(["linha", i, j - 1])
        i = j
    # Uma ou duas palavras em menos de meio segundo piscam: juntam com a página de antes
    # (ou com a de depois, quando a de antes é uma pílula, que fica sozinha).
    for k in range(len(paginas) - 1, -1, -1):
        tipo, a0, b0 = paginas[k]
        if tipo != "linha" or b0 - a0 + 1 > 2 \
                or palavras[b0].fim - palavras[a0].inicio >= PAGINA_CURTA_S:
            continue
        if k > 0 and paginas[k - 1][0] == "linha":
            paginas[k - 1][2] = b0
            del paginas[k]
        elif k + 1 < len(paginas) and paginas[k + 1][0] == "linha":
            paginas[k + 1][1] = a0
            del paginas[k]
    abre = [i == 0 or palavras[i - 1].texto.rstrip().endswith(FIM_DE_FRASE)
            for i in range(n)]
    entradas = [max(0.0, palavras[a0].inicio - PAGINA_ANTES_S) for _, a0, _ in paginas]
    blocos = []
    for k, (tipo, a0, b0) in enumerate(paginas):
        ws = list(palavras[a0:b0 + 1])
        if tipo == "pilula":            # a placa lê mal com o ponto ou a vírgula no fim
            ws = [Palavra(w.texto.rstrip(".,;:"), w.inicio, w.fim) for w in ws]
        # Até 30 ms antes da seguinte, mesmo que a última palavra ainda soe: a seguinte
        # entra 80 ms antes da fala dela, e duas páginas nunca dividem a tela.
        fim = ws[-1].fim + PAGINA_DEPOIS_S
        fim = min(fim, entradas[k + 1] - 0.03) if k + 1 < len(paginas) else min(fim, duracao)
        blocos.append(Bloco(ws, round(entradas[k], 3), round(max(fim, entradas[k] + 0.1), 3),
                            chave([w.texto for w in ws]), abre[a0:b0 + 1], tipo,
                            estilo[a0:b0 + 1]))
    return blocos


def escolher_adesivos(blocos: Sequence[Bloco], duracao: float, ritmo: float = 1.0
                      ) -> list[Adesivo]:
    """As palavras que saltam: número > nome próprio > palavra-chave longa, espaçadas. O
    ``ritmo`` multiplica quantas e encurta o espaço entre elas."""
    candidatos = []
    for bi, b in enumerate(blocos):
        for wi, w in enumerate(b.palavras):
            n = nua(w.texto)
            if any(c.isdigit() for c in w.texto):
                pontos = 3
            elif w.texto[:1].isupper() and not b.abre_frase[wi] and len(n) >= 3:
                pontos = 2
            elif wi == b.chave and len(n) >= 7:
                pontos = 1
            else:
                continue
            if b.fim - w.inicio >= ADESIVO_MINIMO_S:
                candidatos.append((pontos, w.inicio, bi, wi))
    quantos = 0 if duracao < 4 else max(1, int(duracao * ritmo // ADESIVO_A_CADA_S))
    escolhidos: list[tuple[float, int, int]] = []
    for _pontos, t, bi, wi in sorted(candidatos, key=lambda c: (-c[0], c[1])):
        if len(escolhidos) >= quantos:
            break
        if all(abs(t - e[0]) >= ADESIVO_ESPACO_S / ritmo for e in escolhidos):
            escolhidos.append((t, bi, wi))
    escolhidos.sort()
    return [Adesivo(bi, wi, t, blocos[bi].fim, k % 4) for k, (t, bi, wi) in enumerate(escolhidos)]


def montar_zoom(duracao: float, cortes: Sequence[float], blocos: Sequence[Bloco],
                nivel: float, ritmo: float = 1.0) -> list[tuple[float, float]]:
    """Os níveis de zoom: alterna nos cortes; sem corte, no começo de cada frase."""
    pontos = list(cortes) or [b.inicio for b in blocos if b.abre_frase and b.abre_frase[0]]
    saida, atual, ultimo = [(0.0, 1.0)], 1.0, 0.0
    for t in sorted(pontos):
        if t <= 0 or t >= duracao - 0.5 or t - ultimo < ZOOM_ESPACO_S / ritmo:
            continue
        atual = nivel if atual == 1.0 else 1.0
        saida.append((round(t, 3), atual))
        ultimo = t
    return saida


def _formas(n: str) -> list[str]:
    """A palavra (sem acento) e os singulares que ela pode ter: "moedas" → "moeda"."""
    formas = [n]
    for fim, troca in (("oes", "ao"), ("aes", "ao"), ("ns", "m"), ("is", "l"), ("es", ""),
                       ("s", "")):
        if n.endswith(fim) and len(n) > len(fim) + 2:
            formas.append(n[: -len(fim)] + troca)
    return formas


def casar_icone(palavra: str, anterior: str, nomes: set[str]) -> str:
    """O ícone que esta palavra chama, ou ""."""
    n = _sem_acento(nua(palavra))
    if len(n) < 3:
        return ""
    if n == "mundo" and _sem_acento(nua(anterior)) in ("todo", "toda"):
        return ""
    for c in _formas(n):
        nome = SINONIMOS.get(c, c)
        if nome in nomes and nome not in NAO_CHAMAM:
            return nome
    return ""


def escolher_icones(palavras: Sequence[Palavra], duracao: float, nomes: set[str],
                    ritmo: float = 1.0) -> list[Icone]:
    escolhidos: list[Icone] = []
    ultimo, lado = -99.0, 1
    for i, w in enumerate(palavras):
        nome = casar_icone(w.texto, palavras[i - 1].texto if i else "", nomes)
        if not nome or w.inicio - ultimo < ICONE_ESPACO_S / ritmo:
            continue
        escolhidos.append(Icone(nome, w.inicio, min(duracao, w.inicio + ICONE_DURA_S), lado))
        lado, ultimo = -lado, w.inicio
    return escolhidos


@dataclass
class _Candidato:
    inicio: float
    fim: float
    volta_no_corte: bool
    icone: Icone | None
    adesivo: bool


def montar_movimentos(duracao: float, cortes: Sequence[float], adesivos: Sequence[Adesivo],
                      icones: Sequence[Icone], *, vertical: bool, ritmo: float = 1.0
                      ) -> list[Movimento]:
    """Onde a pessoa sai do lugar: só em cortes, e só em alguns trechos.

    Um trecho vai de um corte ao seguinte e tem pelo menos ``MOVER_MINIMO_S``. Primeiro
    entram os de ênfase (um adesivo ou um ícone começando dentro); depois, os que tiram a
    pessoa de uma parada de ``MOVER_PARADA_S``. Entre um e outro há sempre
    ``MOVER_ESPACO_S``. Tudo por regra: o mesmo vídeo sai sempre igual.
    """
    todos = sorted(c for c in cortes if 0 < c < duracao)
    candidatos: list[_Candidato] = []
    for i, c in enumerate(todos):
        if c < MOVER_DO_COMECO_S:
            continue
        seguinte = todos[i + 1] if i + 1 < len(todos) else duracao
        if seguinte - c < MOVER_MINIMO_S:
            continue
        # Até o próximo corte (ou o fim do vídeo); se for longe demais, ela volta antes.
        volta_no_corte = seguinte - c <= MOVER_MAXIMO_S
        fim = seguinte if volta_no_corte else c + MOVER_MAXIMO_S
        icone = next((ic for ic in icones if c <= ic.inicio < fim), None)
        adesivo = any(c <= a.inicio < fim for a in adesivos)
        candidatos.append(_Candidato(c, fim, volta_no_corte, icone, adesivo))

    escolhidos: list[_Candidato] = []

    def cabe(x: _Candidato) -> bool:
        espaco = MOVER_ESPACO_S / ritmo
        return all(x.inicio >= e.fim + espaco or x.fim + espaco <= e.inicio
                   for e in escolhidos)

    for x in candidatos:
        if (x.icone is not None or x.adesivo) and cabe(x):
            escolhidos.append(x)
    for x in candidatos:
        if x in escolhidos:
            continue
        parada_desde = max((e.fim for e in escolhidos if e.fim <= x.inicio), default=0.0)
        if x.inicio - parada_desde >= MOVER_PARADA_S / ritmo and cabe(x):
            escolhidos.append(x)

    ordem = ORDEM_VERTICAL if vertical else ORDEM_HORIZONTAL
    saida: list[Movimento] = []
    k, anterior = 0, ""
    for x in sorted(escolhidos, key=lambda e: e.inicio):
        if x.icone is not None:
            posicao = "direita" if x.icone.lado < 0 else "esquerda"
        elif x.adesivo and anterior != "perto":
            # Perto, mas não duas vezes seguidas: num vídeo de 1 min 46 s, os quatro
            # primeiros movimentos tinham adesivo, e os quatro iam para perto.
            posicao = "perto"
        else:
            posicao = ordem[k % len(ordem)]
            k += 1
            if posicao == anterior:
                posicao = ordem[k % len(ordem)]
                k += 1
        saida.append(Movimento(round(x.inicio, 3), round(x.fim, 3), posicao,
                               x.volta_no_corte))
        anterior = posicao
    return saida


@functools.lru_cache(maxsize=1)
def _familias() -> tuple[dict[str, str], dict[str, str]]:
    """Palavra → família e ícone → família, do catálogo de sons."""
    from editor import sons as sons_mod

    por_palavra, por_icone = {}, {}
    for nome, f in sons_mod.catalogo()["familias"].items():
        for w in f.get("palavras", []):
            por_palavra[w] = nome
        for i in f.get("icones", []):
            por_icone[i] = nome
    return por_palavra, por_icone


def casar_som(palavra: str) -> str:
    """A família de som que esta palavra chama ("moedas", "erro"...), ou "". A palavra que
    fecha uma pergunta chama a pergunta."""
    if palavra.rstrip().endswith("?"):
        return "pergunta"
    n = _sem_acento(nua(palavra))
    if len(n) < 3:
        return ""
    por_palavra, _ = _familias()
    return next((por_palavra[f] for f in _formas(n) if f in por_palavra), "")


def montar_sons(adesivos: Sequence[Adesivo], icones: Sequence[Icone],
                zoom: Sequence[tuple[float, float]],
                movimentos: Sequence[Movimento] = (), *, palavras: Sequence[Palavra] = (),
                cortes: Sequence[float] = (), tema: str = "padrao",
                som_nos_cortes: bool = False, sons_por_palavra: bool = True,
                ritmo: float = 1.0) -> list[Som]:
    """Os efeitos do vídeo, do tema escolhido: um som no que aparece, outro na troca de
    zoom e quando a pessoa sai do lugar, um por palavra e, se pedido, um curto em cada
    corte. Nenhum som em cima do outro.

    A prioridade é o adesivo, o ícone, a palavra, a transição e o corte. Um ícone que tem
    família ("dinheiro") aparece com o som dela (as moedas), e não com o do tema. As
    variações de cada evento se revezam na ordem em que tocam."""
    from editor import sons as sons_mod

    _, por_icone = _familias()
    # (prioridade, instante, "tema" ou "familia", evento ou família)
    candidatos: list[tuple[int, float, str, str]] = []
    candidatos += [(0, a.inicio, "tema", "aparicao") for a in adesivos]
    for ic in icones:
        familia = por_icone.get(ic.nome) if sons_por_palavra else None
        candidatos.append((1, ic.inicio, "familia", familia) if familia
                          else (1, ic.inicio, "tema", "aparicao"))
    if sons_por_palavra:
        ultimo = -99.0
        for w in palavras:
            familia = casar_som(w.texto)
            if not familia or w.inicio - ultimo < SOM_DE_PALAVRA_ESPACO_S / ritmo:
                continue
            # A palavra que já chamou um ícone toca pelo ícone.
            if any(abs(w.inicio - ic.inicio) < 0.05 for ic in icones):
                continue
            candidatos.append((2, w.inicio, "familia", familia))
            ultimo = w.inicio
    # A pessoa saindo do lugar é o movimento maior: o som dela entra primeiro, e os do
    # zoom ocupam o espaço que sobra.
    transicoes: list[float] = []
    for t in [m.inicio for m in movimentos] + [t for t, _nivel in zoom[1:]]:
        if all(abs(t - u) >= WHOOSH_ESPACO_S / ritmo for u in transicoes):
            transicoes.append(t)
    candidatos += [(3, t, "tema", "transicao") for t in transicoes]
    if som_nos_cortes:
        ultimo = -99.0
        for c in sorted(cortes):
            if c - ultimo < SOM_DE_CORTE_ESPACO_S / ritmo:
                continue
            if any(abs(c - u) < CORTE_LONGE_DA_TRANSICAO_S for u in transicoes):
                continue
            candidatos.append((4, c, "tema", "corte"))
            ultimo = c
    # Um evento sem som no tema (a transição, no de notícia) não ocupa lugar de ninguém.
    candidatos = [c for c in candidatos if c[2] != "tema" or sons_mod.do_tema(tema, c[3])]
    ficam: list[tuple[int, float, str, str]] = []
    for c in sorted(candidatos, key=lambda c: (c[0], c[1])):
        if all(abs(c[1] - f[1]) >= SOM_ESPACO_S for f in ficam):
            ficam.append(c)

    familias = sons_mod.catalogo()["familias"]
    vez: dict[str, int] = {}
    saida: list[Som] = []
    for _prioridade, t, origem, qual in sorted(ficam, key=lambda c: c[1]):
        if origem == "tema":
            opcoes, ganho = sons_mod.do_tema(tema, qual), sons_mod.ganho_do_evento(qual)
        else:
            opcoes, ganho = familias[qual]["sons"], sons_mod.ganho_do_evento("palavra")
        k = vez.get(f"{origem}:{qual}", 0)
        vez[f"{origem}:{qual}"] = k + 1
        saida.append(Som(opcoes[k % len(opcoes)], t, ganho))
    return saida


#: O bipe cai no meio da palavra: até tanto depois de o item entrar, ele é da palavra do
#: item.
BIPE_NA_PALAVRA_S = 0.8


def com_sons_dos_cartoes(sons_: Sequence[Som], cartoes: Sequence,
                         silencios: Sequence[tuple[float, float]] = (),
                         tema: str = "padrao") -> list[Som]:
    """Os sons do plano com os dos cartões animados (os do ``tema``, se ele tem os seus),
    que ganham dos outros quando caem juntos; e nenhum som dentro de um bipe (os dois
    embolavam, no vídeo de referência)."""
    from editor import cartoes as cartoes_mod
    from editor import sons as sons_mod

    novos: list[Som] = []
    vez: dict[str, int] = {}
    for c in cartoes:
        for evento, t in cartoes_mod.eventos_de_som(c):
            nomes, ganhos = sons_mod.do_cartao(evento, tema)
            if not nomes:
                continue                     # calado de propósito no tema
            # O item entra na palavra dele: se ela leva bipe, o clique cairia em cima
            # ("no clicks on cocaína: the narration beeps them", no vídeo de referência).
            if evento == "item" and any(0 <= a - t <= BIPE_NA_PALAVRA_S for a, _ in silencios):
                continue
            k = vez.get(evento, 0)
            vez[evento] = k + 1
            novos.append(Som(nomes[k % len(nomes)], round(t, 3), ganhos[k % len(ganhos)]))
    ficam = [s for s in sons_ if all(abs(s.t - n.t) >= SOM_ESPACO_S for n in novos)]
    todos = sorted([*ficam, *novos], key=lambda s: s.t)
    return [s for s in todos
            if not any(a - 0.15 <= s.t <= b + 0.1 for a, b in silencios)]


def montar(palavras: Sequence[Palavra], duracao: float, *, vertical: bool,
           cortes: Sequence[float], opcoes: OpcoesDeEdicao, nomes_de_icones: set[str],
           mover: bool = False) -> Plano:
    """O plano inteiro, a partir das palavras já no tempo do vídeo editado.

    ``mover`` liga os movimentos da pessoa: só a montagem em camadas tem para onde
    levá-la."""
    teto = opcoes.caracteres_por_linha or (TETO_VERTICAL if vertical else TETO_HORIZONTAL)
    ritmo = opcoes.ritmo
    blocos = montar_blocos(palavras, duracao, teto)
    # Os adesivos são da legenda clássica (a palavra salta da linha); os destaques
    # fazem esse papel na outra.
    adesivos = (escolher_adesivos(blocos, duracao, ritmo)
                if opcoes.adesivos and opcoes.estilo_da_legenda == "classica" else [])
    zoom = (montar_zoom(duracao, cortes if opcoes.cortes else [], blocos, opcoes.nivel_zoom,
                        ritmo) if opcoes.zoom else [(0.0, 1.0)])
    empurroes = [(a.inicio, a.fim) for a in adesivos] if opcoes.zoom else []
    icones = (escolher_icones(palavras, duracao, nomes_de_icones, ritmo) if opcoes.icones
              else [])
    movimentos = (montar_movimentos(duracao, cortes, adesivos, icones, vertical=vertical,
                                    ritmo=ritmo) if mover and opcoes.cortes else [])
    sons = (montar_sons(adesivos, icones, zoom, movimentos, palavras=palavras,
                        cortes=cortes if opcoes.cortes else [], tema=opcoes.tema_dos_sons,
                        som_nos_cortes=opcoes.som_nos_cortes,
                        sons_por_palavra=opcoes.sons_por_palavra, ritmo=ritmo)
            if opcoes.sons else [])
    if opcoes.estilo_da_legenda == "destaques":
        blocos = montar_paginas(palavras, duracao, destaques_pelas_palavras(palavras))
    return Plano(round(duracao, 3), vertical, blocos, adesivos, zoom, empurroes, icones, sons,
                 [round(c, 3) for c in cortes], movimentos=movimentos,
                 forca_do_empurrao=opcoes.empurrao)


__all__ = ["DESTAQUES", "ESTILOS_DA_LEGENDA", "PENDURADAS", "POSICOES", "TETO_HORIZONTAL",
           "TETO_VERTICAL", "VAZIAS", "Adesivo", "Bloco", "Icone", "Movimento", "Plano", "Som",
           "casar_icone", "casar_som", "chave", "destaques_pelas_palavras",
           "escolher_adesivos", "escolher_icones", "montar", "montar_blocos",
           "montar_movimentos", "montar_paginas", "montar_sons", "montar_zoom", "nua"]
