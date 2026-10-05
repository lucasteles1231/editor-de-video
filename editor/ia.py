"""
A thumbnail com IA: o Gemini lê o que foi dito, olha 8 quadros do vídeo e devolve três
ideias de thumbnail.

**O Gemini não desenha nem escreve código.** Cada ideia é uma ficha preenchida com
catálogos fechados — o modelo de layout, a cor, o ícone, o quadro — mais a chamada que
ele escreve; quem desenha é a composição da página (Remotion). Assim o resultado é
sempre legível e continua editável nos controles.

**É opcional, e é a única parte do editor que sai do computador.** Vão para o Google o
texto da fala e 8 quadros pequenos (512 px), com a chave de quem usa. O vídeo não vai.
Sem chave, a thumbnail continua sendo feita por regras, aqui mesmo.

O jeito de conversar com o Gemini vem do Stickman, que fala com ele todo dia
(``stickman/ai/client.py``):

- uma **escada de modelos**: se um está sem cota ou fora do ar, tenta o próximo;
- **sem raciocínio estendido** (``thinkingBudget: 0``): o modelo que pensa gastava 96%
  do orçamento de saída pensando, e o JSON chegava pela metade;
- **JSON com esquema**, e uma resposta parada por falta de espaço é recusada dizendo
  isso, e não como "erro de sintaxe na linha 25";
- **as imagens vêm antes da pergunta**: o modelo lê na ordem.

Para testes há uma IA falsa, ligada por ``EDITOR_IA=falsa``: três ideias fixas, sem rede.
Nenhum teste chama a API de verdade.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import unicodedata
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta"
#: Tentados em ordem. Os ``-latest`` não envelhecem (em 03/10/2026 o flash-latest era o
#: 3.8 e o flash-lite-latest, o 3.5-flash-lite). O ``gemini-2.5-flash`` saiu da escada no
#: mesmo dia: a chave nova recebia 404 dele, e um degrau morto é uma ida e volta gasta em
#: toda queda. Cada modelo tem a própria cota — no 3.8, a grátis era de 20 pedidos por
#: dia —, por isso a escada desce quando um deles esgota.
MODELOS = ("gemini-flash-latest", "gemini-3.5-flash", "gemini-flash-lite-latest")
#: A maior fração do quadro, em altura ou largura, que uma caixa de rosto pode ter.
ROSTO_MAXIMO = 0.6
#: A espera antes de tentar de novo o mesmo modelo quando ele diz que está sobrecarregado
#: (503): passa em segundos, e pular direto para o próximo desperdiçava o melhor modelo.
ESPERA_S = 3.0
ONDE_PEGAR_A_CHAVE = "https://aistudio.google.com/apikey"

VARIAVEL_DA_CHAVE = "GEMINI_API_KEY"
VARIAVEL_FALSA = "EDITOR_IA"

#: Quantas ideias e quantos quadros.
VARIANTES = 3
QUADROS = 8
LADO_DO_QUADRO = 512
#: Quanto da fala vai no pedido. Uns 10 minutos de vídeo; num vídeo maior vão o começo
#: (onde o assunto costuma ser dito) e o fim.
TETO_DA_FALA = 15_000
#: O orçamento de saída: três fichas gastam uns 700 tokens.
TOKENS_DE_SAIDA = 4096

#: Onde o vídeo vai ser postado, como o pedido descreve cada plataforma (a página escolhe
#: no passo 1). As capas em pé são cortadas: o perfil do TikTok e do Instagram mostra o
#: meio em 3:4, e a busca do YouTube mostra o meio da capa do Short em 3:2.
PLATAFORMAS = {
    "youtube": "YouTube (vídeo deitado; a thumbnail é 16:9 e aparece inteira)",
    "shorts": "YouTube Shorts (capa em pé, 9:16; na busca e no início, só o meio dela aparece)",
    "tiktok": "TikTok (capa em pé, 9:16; o perfil mostra só o meio dela)",
    "reels": "Instagram Reels (capa em pé, 9:16; o perfil e o feed mostram só o meio dela)",
}
EM_PE = frozenset({"shorts", "tiktok", "reels"})

#: A chamada, com as regras do Stickman (``stickman/titulo.py``): ela é lida num quadro
#: de 120 px de largura, ao lado de outros vídeos.
CHAMADA_PALAVRAS = (2, 5)
CHAMADA_TETO = 28
SELO_TETO = 12
NUMERO_TETO = 6
IDEIA_TETO = 90

#: Os modelos de layout que a página sabe desenhar, com o que dizer ao Gemini sobre cada um.
LAYOUTS = {
    "classico": "a chamada grande ao lado do rosto, com a palavra de destaque num adesivo",
    "numero": "um número gigante (quantidade, preço, porcentagem, tempo) e a chamada "
              "embaixo — use só se o vídeo gira em torno de um número que ele diz",
    "pergunta": "a chamada como pergunta, com um ponto de interrogação enorme — use se o "
                "vídeo responde a uma pergunta",
    "alerta": "uma faixa de aviso no topo — use para erro, cuidado, proibição ou golpe",
}
#: A paleta fechada: todas aguentam o contorno preto em qualquer foto (lição do
#: ``miniatura.CORES`` do Stickman — escolher qualquer matiz dava verde-musgo em floresta).
CORES = ("amarelo", "rosa", "ciano", "lima", "laranja", "roxo", "vermelho")
#: O que vai atrás da pessoa: um quadro do vídeo que mostre o assunto, o quadro dela
#: desfocado, a cor de destaque, uma foto do Pexels ou uma imagem gerada.
FUNDOS = ("video", "desfocado", "cor", "banco", "gerado")
LUZES = ("nenhuma", "contorno", "halo", "raios")
MAOS = ("nenhuma", "titulo", "alvo")
SEM_ICONE = "nenhum"
BUSCA_TETO = 60
CENA_TETO = 300

#: A geração de fundo: o único gasto em dinheiro do editor, e por isso com teto. Um erro
#: que chamasse isto em laço custaria umas imagens, não o saldo (a lição do Stickman).
MODELO_DE_IMAGEM = "gemini-2.5-flash-image"
TETO_DE_IMAGENS = 10
PROPORCOES = ("16:9", "9:16", "1:1")
SEM_FATURAMENTO = ("A geração de imagens do Gemini não está liberada na cota grátis. Para "
                   "usar, ative o faturamento do projeto da sua chave no Google AI Studio "
                   "(aistudio.google.com, em Billing); cada imagem custa uns US$ 0,04.")
_geradas = 0

#: Fórmulas gastas, as mesmas que o Stickman recusa nos títulos.
PROIBIDAS = (
    "tudo sobre", "tudo o que voce precisa saber", "voce nao vai acreditar",
    "voce nunca vai adivinhar", "o segredo que ninguem conta", "ninguem te contou",
    "a verdade que ninguem conta", "vai te surpreender", "isso vai mudar sua vida",
    "chocante", "inacreditavel", "vai explodir sua mente",
)

IDIOMAS = {"pt": "português do Brasil", "en": "inglês", "es": "espanhol",
           "fr": "francês", "it": "italiano", "de": "alemão"}


class ErroDaIA(RuntimeError):
    """Um problema que a página mostra como está — a mensagem já é para quem usa."""


# ── a chave ──────────────────────────────────────────────────────────────
# Guardada por ``editor.chaves``, junto com a do Pexels, nas mesmas regras.

NOME_DA_CHAVE = "gemini_api_key"


def pasta_de_config() -> Path:
    from editor import chaves

    return chaves.pasta_de_config()


def _falsa() -> bool:
    return os.environ.get(VARIAVEL_FALSA, "").strip().lower() == "falsa"


def chave() -> tuple[str, str]:
    """A chave e de onde ela veio: ``"variavel"``, ``"arquivo"`` ou ``""`` (nenhuma)."""
    from editor import chaves

    return chaves.ler(NOME_DA_CHAVE, VARIAVEL_DA_CHAVE)


def salvar_chave(valor: str) -> None:
    from editor import chaves

    chaves.salvar(NOME_DA_CHAVE, valor)


def apagar_chave() -> None:
    from editor import chaves

    chaves.apagar(NOME_DA_CHAVE)


def mascarada(valor: str) -> str:
    from editor import chaves

    return chaves.mascarada(valor)


def estado() -> dict:
    """O que a página precisa saber — nunca a chave."""
    if _falsa():
        return {"configurada": True, "origem": "falsa", "final": "…test", "falsa": True}
    from editor import chaves

    return {**chaves.estado(NOME_DA_CHAVE, VARIAVEL_DA_CHAVE), "falsa": False}


# ── a conversa com a API ─────────────────────────────────────────────────


def _cliente(transporte=None, timeout: float = 90.0):
    import httpx

    return httpx.Client(transport=transporte, timeout=timeout)


def _mensagem_do_google(resposta) -> str:
    try:
        return str(resposta.json().get("error", {}).get("message", ""))[:300]
    except ValueError:
        return resposta.text[:300]


def limpar_chave(valor: str) -> str:
    from editor import chaves

    return chaves.limpar(valor)


def validar_chave(valor: str, *, transporte=None) -> str:
    """Confere a chave listando os modelos — isso não gasta cota — e devolve ela limpa.
    Levanta :class:`ErroDaIA`.

    O formato só é olhado por alto, e de propósito: a primeira versão exigia letras,
    números, "_" e "-", e recusou uma chave de verdade — as chaves novas do AI Studio
    têm ponto ("AQ.…"). Quem decide se a chave vale é o Google.
    """
    import httpx

    from editor import chaves

    valor = limpar_chave(valor)
    if not chaves.parece_chave(valor):
        raise ErroDaIA("Isso não parece uma chave do Gemini: ela é uma sequência longa, sem "
                       f"espaços. Pegue a sua em {ONDE_PEGAR_A_CHAVE}")
    try:
        with _cliente(transporte, timeout=20) as cliente:
            r = cliente.get(f"{API}/models", params={"pageSize": 1},
                            headers={"x-goog-api-key": valor})
    except httpx.HTTPError as erro:
        raise ErroDaIA("Não consegui falar com o Google para conferir a chave. "
                       "Confira a internet e tente de novo.") from erro
    if r.status_code in (400, 401, 403):
        raise ErroDaIA(f"O Google recusou esta chave. Confira se copiou inteira, ou crie "
                       f"outra em {ONDE_PEGAR_A_CHAVE}")
    if r.status_code >= 400:
        raise ErroDaIA(f"O Google respondeu {r.status_code} ao conferir a chave: "
                       f"{_mensagem_do_google(r)}")
    return valor


def _corpo(sistema: str, pedido: str, imagens: Sequence[bytes], esquema: dict,
           temperatura: float, pensar: bool) -> dict:
    # As imagens antes da pergunta: uma pergunta feita depois das provas é uma pergunta
    # sobre as provas.
    partes: list[dict] = [{"inlineData": {"mimeType": "image/jpeg",
                                          "data": base64.b64encode(b).decode("ascii")}}
                          for b in imagens]
    partes.append({"text": pedido})
    # O esquema vai como JSON Schema ("responseJsonSchema"). O formato antigo
    # ("responseSchema", com "propertyOrdering") passou a voltar 400 "invalid argument"
    # nos modelos 3.x — visto na primeira chamada de verdade, em 03/10/2026.
    config: dict = {"temperature": temperatura,
                    "maxOutputTokens": TOKENS_DE_SAIDA * (2 if pensar else 1),
                    "responseMimeType": "application/json", "responseJsonSchema": esquema}
    if not pensar:
        config["thinkingConfig"] = {"thinkingBudget": 0}
    return {"systemInstruction": {"parts": [{"text": sistema}]},
            "contents": [{"role": "user", "parts": partes}],
            "generationConfig": config}


class _Pular(Exception):
    """Este modelo não serve agora (cota, fora do ar, não existe): tente o próximo.

    ``sem_pensar``: recusou o pedido (400) — tente o mesmo modelo deixando ele pensar,
    porque há modelo que não aceita desligar o raciocínio e diz isso de forma genérica.
    ``transitorio``: sobrecarga ou demora — tente o mesmo modelo de novo, uma vez.
    ``minuto``: a cota que acabou é a do minuto, não a do dia.
    """

    def __init__(self, motivo: str, *, cota: bool = False, sem_pensar: bool = False,
                 transitorio: bool = False, minuto: bool = False,
                 espera: float | None = None):
        super().__init__(motivo)
        self.cota = cota
        self.sem_pensar = sem_pensar
        self.transitorio = transitorio
        self.minuto = minuto
        self.espera = espera


def _espera_da_cota(resposta) -> float | None:
    """Quantos segundos o Google manda esperar (o ``RetryInfo`` do erro), se ele disser.

    A cota "por dia" do 3.8 voltava à meia-noite UTC, não à do Pacífico: o número que o
    próprio Google manda é o único que não envelhece."""
    try:
        detalhes = resposta.json().get("error", {}).get("details") or []
    except ValueError:
        return None
    for d in detalhes:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    return None


def _daqui_a(segundos: float) -> str:
    minutos = round(segundos / 60)
    if minutos <= 1:
        return "cerca de um minuto"
    if minutos < 90:
        return f"cerca de {minutos} min"
    return f"cerca de {round(minutos / 60)} h"


def _gerar(cliente, modelo: str, chave_: str, corpo: dict) -> str:
    """O texto da resposta de um modelo; :class:`_Pular` para tentar o próximo."""
    import httpx

    try:
        r = cliente.post(f"{API}/models/{modelo}:generateContent", json=corpo,
                         headers={"x-goog-api-key": chave_})
    except httpx.TimeoutException as erro:
        raise _Pular(f"{modelo}: demorou demais", transitorio=True) from erro
    except httpx.HTTPError as erro:
        raise ErroDaIA("Não consegui falar com o Gemini. Confira a internet e tente de "
                       "novo.") from erro
    if r.status_code == 429:
        por_minuto = "perminute" in r.text.lower().replace(" ", "")
        raise _Pular(f"{modelo}: sem cota", cota=True, minuto=por_minuto,
                     espera=_espera_da_cota(r))
    if r.status_code == 404:
        raise _Pular(f"{modelo}: não existe para esta chave")
    if r.status_code in (500, 502, 503, 504):
        raise _Pular(f"{modelo}: respondeu {r.status_code}", transitorio=True)
    if r.status_code in (401, 403) or (r.status_code == 400
                                       and "api key" in _mensagem_do_google(r).lower()):
        raise ErroDaIA(f"O Google recusou a chave do Gemini. Troque a chave no passo 5 (crie "
                       f"uma em {ONDE_PEGAR_A_CHAVE}).")
    if r.status_code == 400:
        raise _Pular(f"{modelo}: 400 {_mensagem_do_google(r)}", sem_pensar=True)
    if r.status_code >= 400:
        raise _Pular(f"{modelo}: {r.status_code} {_mensagem_do_google(r)}")
    dados = r.json()
    bloqueio = (dados.get("promptFeedback") or {}).get("blockReason")
    if bloqueio:
        raise ErroDaIA(f"O Gemini se recusou a sugerir thumbnails para este vídeo ({bloqueio}).")
    candidatos = dados.get("candidates") or []
    if not candidatos:
        raise _Pular(f"{modelo}: resposta vazia")
    fim = candidatos[0].get("finishReason", "")
    if fim == "MAX_TOKENS":
        raise _Pular(f"{modelo}: a resposta foi cortada por falta de espaço")
    texto = "".join(p.get("text", "") for p in (candidatos[0].get("content") or {})
                    .get("parts", []) if not p.get("thought"))
    if not texto.strip():
        raise _Pular(f"{modelo}: resposta vazia ({fim})")
    return texto


def _perguntar(chave_: str, sistema: str, pedido: str, imagens: Sequence[bytes],
               esquema: dict, *, temperatura: float, transporte=None,
               gasto: list[str] | None = None) -> tuple[dict, str]:
    """O JSON da resposta e o modelo que respondeu, descendo a escada.

    ``gasto`` recebe o modelo de cada pedido feito: a cota grátis conta pedidos, e quem
    usa merece saber quantos uma sugestão custou."""
    motivos: list[str] = []
    so_cota = True
    por_minuto = False
    esperas: list[float] = []
    with _cliente(transporte) as cliente:
        for modelo in MODELOS:
            pensar, de_novo = False, False
            while True:
                if gasto is not None:
                    gasto.append(modelo)
                comeco = time.monotonic()
                try:
                    texto = _gerar(cliente, modelo, chave_,
                                   _corpo(sistema, pedido, imagens, esquema, temperatura,
                                          pensar))
                    logger.info("gemini %s respondeu em %.1f s", modelo,
                                time.monotonic() - comeco)
                except _Pular as p:
                    logger.info("gemini: %s (%.1f s)", p, time.monotonic() - comeco)
                    if p.sem_pensar and not pensar:
                        pensar = True                 # o mesmo modelo, deixando pensar
                        continue
                    if p.transitorio and not de_novo:
                        de_novo = True                # o mesmo modelo, uma vez mais
                        time.sleep(ESPERA_S)
                        continue
                    motivos.append(str(p))
                    so_cota = so_cota and p.cota
                    por_minuto = por_minuto or p.minuto
                    if p.espera is not None:
                        esperas.append(p.espera)
                    break
                try:
                    return json.loads(texto), modelo
                except ValueError:
                    motivos.append(f"{modelo}: o JSON veio quebrado")
                    so_cota = False
                    break
    if so_cota and motivos and por_minuto:
        raise ErroDaIA("O Gemini recebeu pedidos demais em pouco tempo (o limite por minuto "
                       "da chave grátis). Espere um minuto e tente de novo.")
    if so_cota and motivos and esperas:
        raise ErroDaIA("A cota grátis do Gemini acabou em todos os modelos que o editor "
                       f"tenta. Ela volta em {_daqui_a(min(esperas))}.")
    if so_cota and motivos:
        raise ErroDaIA("A cota grátis do Gemini acabou por hoje em todos os modelos que o "
                       "editor tenta. Tente de novo amanhã.")
    logger.warning("o Gemini não respondeu: %s", "; ".join(motivos))
    raise ErroDaIA("O Gemini não conseguiu responder agora (" + "; ".join(motivos[-2:])
                   + "). Tente de novo em alguns minutos.")


# ── o pedido ─────────────────────────────────────────────────────────────


def _cru(texto: str) -> str:
    sem = unicodedata.normalize("NFD", texto or "")
    sem = "".join(c for c in sem if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%$]", " ", sem.lower())).strip()


def formula_gasta(texto: str) -> str:
    cru = _cru(texto)
    return next((p for p in PROIBIDAS if p in cru), "")


def esquema(nomes_de_icones: Sequence[str]) -> dict:
    """O formato da resposta, em JSON Schema. Os campos que têm catálogo vão como enum."""
    caixa = {"type": "array", "items": {"type": "integer"},
             "description": "[ymin, xmin, ymax, xmax] de 0 a 1000, ou [] se não houver"}
    campos = {
        "ideia": {"type": "string", "description": "a ideia em uma frase curta"},
        "modelo": {"type": "string", "enum": list(LAYOUTS)},
        "chamada": {"type": "string"},
        "destaque": {"type": "string", "description": "uma palavra da chamada"},
        "numero": {"type": "string", "description": "só no modelo numero; senão vazio"},
        "selo": {"type": "string", "description": "etiqueta curta ou vazio"},
        # Sem enum: os 3.x recusam um enum de 123 valores com um 400 genérico ("invalid
        # argument"), medido em 03/10/2026. O catálogo vai no texto do pedido, e a
        # conferência troca um nome que não existe por nenhum ícone.
        "icone": {"type": "string", "description": "um nome do catálogo de ícones"},
        "cor": {"type": "string", "enum": list(CORES)},
        "fundo": {"type": "string", "enum": list(FUNDOS)},
        "quadro_fundo": {"type": "integer",
                         "description": "o quadro do fundo video; -1 nos outros"},
        "foco": caixa,
        "busca": {"type": "string", "description": "o que buscar no banco de fotos; vazio se não"},
        "cena": {"type": "string", "description": "a cena para gerar; vazio se não"},
        "recorte": {"type": "boolean"},
        "quadro": {"type": "integer"},
        "rosto": caixa,
        "luz": {"type": "string", "enum": list(LUZES)},
        "mao": {"type": "string", "enum": list(MAOS)},
        "seta": {"type": "boolean"},
        "alvo": caixa,
    }
    return {"type": "object",
            "properties": {"variantes": {"type": "array", "items": {
                "type": "object", "properties": campos, "required": list(campos)}}},
            "required": ["variantes"]}


SISTEMA = """Você é diretor de arte de thumbnails para YouTube, Shorts, Reels e TikTok.
Você não desenha: escolhe, entre opções fechadas, o que uma composição pronta vai
desenhar, e escreve a chamada. Responda só com o JSON pedido."""


def _fala_para_o_pedido(fala: str) -> str:
    fala = re.sub(r"\s+", " ", fala or "").strip()
    if len(fala) <= TETO_DA_FALA:
        return fala
    corte = TETO_DA_FALA * 2 // 3
    return fala[:corte] + " […] " + fala[-(TETO_DA_FALA - corte):]


def _indices(origens: Sequence[str] | None, n: int, qual: str) -> list[int]:
    """Os quadros de uma origem ("pessoa" ou "fundo"); sem origens, todos."""
    if origens is None:
        return list(range(n))
    escolhidos = [i for i, o in enumerate(origens) if o == qual]
    return escolhidos or list(range(n))


def _sobre_as_camadas(origens: Sequence[str] | None) -> str:
    """O que dizer ao Gemini quando o vídeo é montado em camadas."""
    if origens is None:
        return ""
    if "pessoa" not in origens:
        return ("\nA PESSOA DO VÍDEO é um personagem animado, que não aparece nos quadros: "
                "todos são do vídeo de fundo, o que fica atrás dele. Use \"quadro\" para o "
                "quadro que vai atrás do personagem, \"rosto\" vazio ([]) e \"recorte\" "
                "true.\n")
    da_pessoa = ", ".join(str(i) for i in _indices(origens, len(origens), "pessoa"))
    do_fundo = ", ".join(str(i) for i in _indices(origens, len(origens), "fundo"))
    return (f"\nO VÍDEO É MONTADO EM CAMADAS: os quadros {da_pessoa} são da pessoa falando; "
            f"os quadros {do_fundo} são do vídeo de fundo, que aparece atrás dela (uma tela, "
            "um jogo, slides). \"quadro\" é sempre um quadro da pessoa; o fundo \"video\" "
            "usa um quadro do fundo em \"quadro_fundo\".\n")


def montar_pedido(fala: str, tempos: Sequence[float], *, idioma: str, duracao: float,
                  vertical: bool, nomes_de_icones: Sequence[str],
                  evitar: Sequence[str] = (), origens: Sequence[str] | None = None,
                  plataformas: Sequence[str] = ()) -> str:
    lingua = IDIOMAS.get(idioma, idioma or "o idioma da fala")
    nomes_da_origem = {"pessoa": " (da pessoa)", "fundo": " (do fundo)"}
    quadros = "\n".join(
        f"- quadro {i}: a {i + 1}ª imagem, em {t:.1f} s"
        + (nomes_da_origem.get(origens[i], "") if origens is not None else "")
        for i, t in enumerate(tempos))
    layouts = "\n".join(f"- {nome}: {o_que}" for nome, o_que in LAYOUTS.items())
    gastas = ", ".join(f'"{p}"' for p in PROIBIDAS)
    minimo, maximo = CHAMADA_PALAVRAS
    repetir = ("\nJá foram sugeridas estas chamadas; traga ideias diferentes delas:\n"
               + "\n".join(f"- {c}" for c in evitar)) if evitar else ""
    onde = [PLATAFORMAS[x] for x in plataformas if x in PLATAFORMAS]
    postado = ("\nONDE VAI SER POSTADO: " + "; ".join(onde) + "." if onde else "") + (
        "\nA capa em pé é cortada em cima e embaixo: a chamada precisa ser curta e funcionar "
        "no meio da imagem." if EM_PE & set(plataformas) else "")
    return f"""O VÍDEO: {duracao:.0f} segundos, {"vertical" if vertical else "horizontal"}.{postado}
As {len(tempos)} imagens acima são quadros dele, em ordem:
{quadros}
{_sobre_as_camadas(origens)}
O QUE É DITO NO VÍDEO (transcrição automática, pode ter erros):
\"\"\"{_fala_para_o_pedido(fala)}\"\"\"

SUA TAREFA: {VARIANTES} ideias de thumbnail para este vídeo, cada uma com um ângulo
diferente (por exemplo: a curiosidade, o resultado ou número, o erro a evitar). Escreva
tudo em {lingua}.

A CHAMADA ("chamada") — o texto grande:
- De {minimo} a {maximo} palavras, no máximo {CHAMADA_TETO} caracteres contando espaços.
  Ela é lida num quadro de 120 pixels de largura, ao lado de outros vídeos.
- Diga o assunto pelo nome dele. Reescreva com sinônimos em vez de cortar frases da
  fala: "por que as coisas caem no chão" vira "A gravidade explicada".
- Prometa só o que o vídeo de fato entrega. Nada de exagero que a fala não sustenta.
- Sem fórmula gasta: {gastas}.
- "destaque": a palavra mais forte da chamada (número, nome, conceito), escrita igual
  a como está na chamada. Ela vai num adesivo colorido.

O MODELO ("modelo"):
{layouts}
- "numero": o número do modelo numero (ex.: "3", "R$10", "90%", "5 min"), até
  {NUMERO_TETO} caracteres, e vazio nos outros modelos.
- "selo": uma etiqueta opcional de até {SELO_TETO} caracteres (ex.: NOVO, TESTEI,
  GRÁTIS, CUIDADO), ou vazio. Use pouco.

A IMAGEM:
- "quadro": o número do quadro de fundo. Prefira o rosto mais expressivo (emoção
  clara, olhos abertos, sem desfoque e sem boca torta no meio de uma palavra).
- "rosto": a caixa do rosto nesse quadro, [ymin, xmin, ymax, xmax] de 0 a 1000; [] se
  não houver rosto.
- "recorte": true para recortar a pessoa e pôr na frente de um fundo novo (o visual
  clássico do YouTube); false para usar o quadro inteiro.
- "fundo", o que vai atrás da pessoa recortada:
  - "video": OUTRO quadro do vídeo que mostra o assunto (uma tela, um produto, um lugar)
    — só se algum quadro mostra algo além do rosto de quem fala. Diga qual em
    "quadro_fundo" e a região que importa nele em "foco" ([] para o quadro inteiro);
  - "banco": uma foto de banco de imagens sobre o assunto, quando ele é concreto e
    fotografável (um lugar, um objeto, um animal). Diga o que buscar em "busca", em
    poucas palavras, no idioma da fala;
  - "gerado": uma imagem criada do zero, só quando nada acima serve. Descreva a cena em
    "cena" (sem texto e sem pessoas);
  - "desfocado": o próprio quadro da pessoa, desfocado;
  - "cor": um fundo liso na cor escolhida.
  Os campos que não são do fundo escolhido vão vazios (e "quadro_fundo" -1).
- "luz" na pessoa: "contorno" (uma luz colorida na borda dela), "halo" (um brilho
  suave atrás), "raios" (raios de luz saindo de trás) ou "nenhuma".
- "mao": uma mão de emoji apontando o dedo para a chamada ("titulo") ou para o "alvo",
  ou "nenhuma". Ela conta como um elemento.
- "seta" e "alvo": true e a caixa de algo do quadro que vale apontar (um objeto, um
  produto, uma tela). Se não houver nada que valha, false e [].
- "icone": um ícone que reforce a ideia, ou "{SEM_ICONE}" se nenhum ajudar. Só destes:
  {", ".join(nomes_de_icones)}.
- "cor": a cor de destaque, combinando com o tom do assunto. Varie entre as ideias.
- "ideia": uma frase curta, até {IDEIA_TETO} caracteres, dizendo a ideia para quem vai
  escolher.

No máximo três elementos chamando atenção: rosto, chamada e um terceiro (ícone, seta,
mão, número ou selo).{repetir}"""


# ── a conferência ────────────────────────────────────────────────────────


def _caixa(valor, problemas: list[str], nome: str) -> dict | None:
    """A caixa do Gemini ([ymin, xmin, ymax, xmax], 0 a 1000) em frações, ou None."""
    if not valor:
        return None
    if not (isinstance(valor, list) and len(valor) == 4
            and all(isinstance(v, int | float) for v in valor)):
        problemas.append(f"{nome} precisa ser [ymin, xmin, ymax, xmax] ou []")
        return None
    y0, x0, y1, x1 = (min(1000.0, max(0.0, float(v))) for v in valor)
    if y1 - y0 < 30 or x1 - x0 < 30:
        problemas.append(f"{nome} é pequeno demais ou está invertido")
        return None
    return {"x0": x0 / 1000, "y0": y0 / 1000, "x1": x1 / 1000, "y1": y1 / 1000}


def conferir(v: dict, *, quadros: int, nomes_de_icones: set[str],
             origens: Sequence[str] | None = None) -> tuple[dict | None, list[str]]:
    """Uma ideia pronta para a página, ou ``None`` e o que está errado nela.

    Com ``origens`` (a montagem em camadas), ``quadro`` precisa ser um quadro da pessoa e
    ``quadro_fundo`` um quadro do fundo."""
    da_pessoa = _indices(origens, quadros, "pessoa")
    do_fundo = _indices(origens, quadros, "fundo")
    problemas: list[str] = []
    modelo = str(v.get("modelo", ""))
    if modelo not in LAYOUTS:
        problemas.append(f"modelo {modelo!r} não existe")
    chamada = re.sub(r"\s+", " ", str(v.get("chamada", ""))).strip()
    palavras = chamada.split()
    minimo, maximo = CHAMADA_PALAVRAS
    if not minimo <= len(palavras) <= maximo:
        problemas.append(f'a chamada "{chamada}" tem {len(palavras)} palavras; são de '
                         f"{minimo} a {maximo}")
    if len(chamada) > CHAMADA_TETO:
        problemas.append(f'a chamada "{chamada}" tem {len(chamada)} caracteres; o teto é '
                         f"{CHAMADA_TETO}")
    if formula_gasta(chamada):
        problemas.append(f'a chamada usa a fórmula gasta "{formula_gasta(chamada)}"')
    destaque = -1
    alvo_do_destaque = _cru(str(v.get("destaque", "")))
    for i, w in enumerate(palavras):
        if _cru(w) and _cru(w) == alvo_do_destaque:
            destaque = i
            break
    if destaque < 0 and alvo_do_destaque:
        problemas.append(f'o destaque "{v.get("destaque")}" não é uma palavra da chamada')
    numero = str(v.get("numero", "")).strip()
    if modelo == "numero" and not (numero and len(numero) <= NUMERO_TETO
                                   and re.search(r"\d", numero)):
        problemas.append(f'o modelo numero precisa de um número de até {NUMERO_TETO} '
                         f'caracteres, e veio "{numero}"')
    selo = str(v.get("selo", "")).strip().upper()
    if len(selo) > SELO_TETO:
        problemas.append(f'o selo "{selo}" passa de {SELO_TETO} caracteres')
    # Um ícone que não existe não reprova a ideia: ela sai sem ícone. Um conserto custaria
    # outro pedido, e a cota grátis é de poucos pedidos por dia.
    icone = str(v.get("icone", SEM_ICONE)).strip().lower()
    if icone not in nomes_de_icones:
        icone = SEM_ICONE
    cor = str(v.get("cor", ""))
    if cor not in CORES:
        problemas.append(f"a cor {cor!r} não existe")
    fundo = str(v.get("fundo", "desfocado"))
    if fundo not in FUNDOS:
        problemas.append(f"o fundo {fundo!r} não existe")
    quadro = v.get("quadro")
    if not isinstance(quadro, int) or quadro not in da_pessoa:
        problemas.append(f"o quadro {quadro!r} não serve: use um destes: "
                         f"{', '.join(map(str, da_pessoa))}")
    rosto = _caixa(v.get("rosto"), problemas, "rosto")
    # Um rosto mais alto que isto é a pessoa inteira, não o rosto (visto num teste real).
    # Ele sai sem pedir conserto: a página mede o rosto pelo recorte.
    if rosto and max(rosto["y1"] - rosto["y0"], rosto["x1"] - rosto["x0"]) > ROSTO_MAXIMO:
        rosto = None
    alvo = _caixa(v.get("alvo"), problemas, "alvo")
    quadro_fundo, foco, busca, cena = -1, None, "", ""
    if fundo == "video":
        quadro_fundo = v.get("quadro_fundo")
        if not isinstance(quadro_fundo, int) or quadro_fundo not in do_fundo:
            problemas.append("o fundo video precisa de um quadro_fundo destes: "
                             f"{', '.join(map(str, do_fundo))}")
        foco = _caixa(v.get("foco"), problemas, "foco")
    elif fundo == "banco":
        busca = " ".join(str(v.get("busca", "")).split())
        if not busca or len(busca) > BUSCA_TETO:
            problemas.append(f"o fundo banco precisa de uma busca de até {BUSCA_TETO} "
                             "caracteres")
    elif fundo == "gerado":
        cena = " ".join(str(v.get("cena", "")).split())
        if not cena or len(cena) > CENA_TETO:
            problemas.append(f"o fundo gerado precisa de uma cena de até {CENA_TETO} "
                             "caracteres")
    luz = str(v.get("luz", "nenhuma"))
    if luz not in LUZES:
        problemas.append(f"a luz {luz!r} não existe")
    mao = str(v.get("mao", "nenhuma"))
    if mao not in MAOS:
        problemas.append(f"a mão {mao!r} não existe")
    if problemas:
        return None, problemas
    return {
        "ideia": str(v.get("ideia", "")).strip()[:IDEIA_TETO],
        "modelo": modelo,
        "chamada": chamada,
        "destaque": destaque,
        "numero": numero if modelo == "numero" else "",
        "selo": selo,
        "icone": "" if icone == SEM_ICONE else icone,
        "cor": cor,
        "fundo": fundo,
        "quadro_fundo": quadro_fundo,
        "foco": foco,
        "busca": busca,
        "cena": cena,
        "recorte": bool(v.get("recorte")),
        "quadro": quadro,
        "rosto": rosto,
        "luz": luz,
        # A mão aponta para o alvo só se houver alvo; sem ele, para o título.
        "mao": "titulo" if mao == "alvo" and alvo is None else mao,
        "seta": bool(v.get("seta")) and alvo is not None,
        "alvo": alvo if (v.get("seta") or mao == "alvo") else None,
    }, []


# ── tudo junto ───────────────────────────────────────────────────────────


def _falsas() -> list[dict]:
    base = {"numero": "", "selo": "", "seta": False, "alvo": None, "quadro_fundo": -1,
            "foco": None, "busca": "", "cena": "", "luz": "nenhuma", "mao": "nenhuma",
            "rosto": {"x0": 0.3, "y0": 0.1, "x1": 0.7, "y1": 0.35}}
    return [
        {**base, "ideia": "A promessa do vídeo, com o rosto em destaque", "modelo": "classico",
         "chamada": "Corta as pausas sozinho", "destaque": 2, "icone": "relogio",
         "cor": "amarelo", "fundo": "cor", "recorte": True, "quadro": 0, "luz": "contorno",
         "mao": "titulo"},
        {**base, "ideia": "O número que o vídeo cita", "modelo": "numero", "numero": "3",
         "chamada": "Dicas de edição", "destaque": 1, "icone": "", "cor": "lima",
         "fundo": "banco", "busca": "estúdio de vídeo", "recorte": True, "quadro": 1,
         "selo": "NOVO", "luz": "halo"},
        {**base, "ideia": "O erro que a maioria comete", "modelo": "alerta",
         "chamada": "Pare de cortar na mão", "destaque": 4, "icone": "alerta",
         "cor": "vermelho", "fundo": "gerado", "cena": "uma mesa de edição com telas",
         "recorte": True, "quadro": 2, "luz": "raios"},
    ]


def sugerir(fala: str, quadros: Sequence[tuple[float, bytes]], *, idioma: str,
            duracao: float, vertical: bool, nomes_de_icones: Sequence[str],
            evitar: Sequence[str] = (), transporte=None,
            origens: Sequence[str] | None = None, plataformas: Sequence[str] = ()) -> dict:
    """As ideias de thumbnail para um vídeo.

    ``quadros`` são ``(instante, jpeg)``. Devolve ``{"variantes": [...], "modelo": ...,
    "segundos": ...}``, cada variante já com o instante ``t`` do quadro escolhido.
    Na montagem em camadas, ``origens`` diz de onde vem cada quadro ("pessoa" ou
    "fundo"): ``t`` é do vídeo da pessoa (ou do fundo, com personagem) e ``t_fundo``,
    do fundo. Levanta :class:`ErroDaIA` com uma mensagem para quem usa.
    """
    comeco = time.monotonic()
    tempos = [t for t, _ in quadros]
    if _falsa():
        variantes = [{**v, "t": tempos[min(v["quadro"], len(tempos) - 1)], "t_fundo": None}
                     for v in _falsas()]
        return {"variantes": variantes, "modelo": "falsa", "pedidos": 0, "segundos": 0.0}
    valor, _origem = chave()
    if not valor:
        raise ErroDaIA("Falta a chave do Gemini: cole a sua no passo 5 "
                       f"(crie uma em {ONDE_PEGAR_A_CHAVE}).")
    if not quadros:
        raise ErroDaIA("Não consegui tirar quadros deste vídeo para o Gemini olhar.")
    nomes = set(nomes_de_icones)
    formato = esquema(sorted(nomes))
    pedido = montar_pedido(fala, tempos, idioma=idioma, duracao=duracao, vertical=vertical,
                           nomes_de_icones=sorted(nomes), evitar=evitar, origens=origens,
                           plataformas=plataformas)
    imagens = [b for _, b in quadros]
    gasto: list[str] = []
    resposta, modelo = _perguntar(valor, SISTEMA, pedido, imagens, formato,
                                  temperatura=1.0, transporte=transporte, gasto=gasto)
    boas, ruins = _separar(resposta, len(quadros), nomes, origens)
    if ruins and len(boas) < VARIANTES:
        logger.info("conserto de %d ideia(s): %s", len(ruins),
                    " | ".join("; ".join(p) for _, p in ruins))
        # Um conserto, com o que estava errado — o mesmo que o diretor do Stickman faz.
        # O "ideia" é lido por quem escolhe: num teste real, ele voltou dizendo
        # "corrigindo o modelo para classico".
        conserto = (pedido + "\n\nESTAS IDEIAS VIERAM COM PROBLEMAS. Mande de novo só elas, "
                    "corrigidas. O campo \"ideia\" continua dizendo a ideia para quem vai "
                    "escolher, sem falar da correção:\n" + "\n".join(
                        f"- {json.dumps(v, ensure_ascii=False)}\n  problemas: "
                        + "; ".join(p) for v, p in ruins))
        try:
            resposta2, modelo = _perguntar(valor, SISTEMA, conserto, imagens, formato,
                                           temperatura=0.4, transporte=transporte,
                                           gasto=gasto)
            mais, _ = _separar(resposta2, len(quadros), nomes, origens)
            boas.extend(mais)
        except ErroDaIA:
            logger.info("o conserto não veio; ficam as ideias que já estavam boas")
    if not boas:
        raise ErroDaIA("O Gemini respondeu, mas nenhuma ideia passou na conferência. "
                       "Tente de novo.")
    # Os instantes de verdade: o do quadro da pessoa e, no fundo "video", o do conteúdo.
    variantes = [{**v, "t": round(tempos[v["quadro"]], 2),
                  "t_fundo": round(tempos[v["quadro_fundo"]], 2) if v["quadro_fundo"] >= 0
                  else None} for v in boas[:VARIANTES]]
    return {"variantes": variantes, "modelo": modelo, "pedidos": len(gasto),
            "segundos": round(time.monotonic() - comeco, 1)}


def _separar(resposta: dict, quadros: int, nomes: set[str],
             origens: Sequence[str] | None = None
             ) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    boas, ruins = [], []
    personagem = origens is not None and "pessoa" not in origens
    for v in (resposta.get("variantes") or [])[:VARIANTES * 2]:
        if not isinstance(v, dict):
            continue
        pronta, problemas = conferir(v, quadros=quadros, nomes_de_icones=nomes,
                                     origens=origens)
        if pronta and personagem:
            # O personagem não aparece nos quadros: não há rosto para medir, e ele vai
            # sempre recortado (é um desenho com transparência).
            pronta["rosto"], pronta["recorte"] = None, True
        if pronta:
            boas.append(pronta)
        else:
            ruins.append((v, problemas))
    return boas, ruins


# ── o fundo gerado ───────────────────────────────────────────────────────


def geracoes_restantes() -> int:
    return max(0, TETO_DE_IMAGENS - _geradas)


def _pedido_de_fundo(cena: str, proporcao: str, lado_do_texto: str) -> str:
    # Em inglês: é o idioma em que o modelo de imagem segue as restrições com mais
    # firmeza. A cena vem no idioma da fala, e ele entende.
    livre = ("the top third" if proporcao != "16:9"
             else "the left third" if lado_do_texto == "esquerda" else "the right third")
    return (f"Background image for a YouTube thumbnail. Scene: {cena}. "
            "Style: vivid photograph, saturated colors, high contrast, cinematic light, "
            "shallow depth of field. Strictly no text, no letters, no numbers, no logos, "
            "no watermarks, no people, no faces, no hands. "
            f"Keep {livre} of the image calm and uncluttered: a big title goes there, and a "
            "person cut out will be placed in front of the rest.")


def _imagem_falsa(proporcao: str) -> bytes:
    import io as _io

    from PIL import Image

    tamanho = {"16:9": (1344, 768), "9:16": (768, 1344), "1:1": (1024, 1024)}[proporcao]
    img = Image.linear_gradient("L").rotate(45, expand=True).resize(tamanho).convert("RGB")
    img = Image.blend(img, Image.new("RGB", tamanho, (40, 120, 200)), 0.55)
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def pasta_de_dados() -> Path:
    from platformdirs import user_data_dir

    return Path(user_data_dir("editor-de-video", appauthor=False))


def _anotar_gasto(proporcao: str, cena: str) -> None:
    """Cada imagem paga vai para um arquivo, para o gasto ser visto sem abrir o console."""
    from datetime import datetime

    try:
        pasta = pasta_de_dados()
        pasta.mkdir(parents=True, exist_ok=True)
        with (pasta / "gastos.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"),
                                "modelo": MODELO_DE_IMAGEM, "proporcao": proporcao,
                                "cena": cena[:80]}, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("não deu para anotar o gasto", exc_info=True)


def gerar_fundo(cena: str, proporcao: str = "16:9", *, lado_do_texto: str = "esquerda",
                transporte=None) -> bytes:
    """Uma imagem de fundo gerada pelo Gemini (PNG ou JPEG). Levanta :class:`ErroDaIA`.

    **Custa dinheiro**: só roda a pedido, e no máximo :data:`TETO_DE_IMAGENS` vezes por
    sessão. A proporção vai como parâmetro, e não no texto: no Stickman, todo pedido
    que dizia "imagem larga" em palavras voltou quadrado.
    """
    import httpx

    global _geradas
    cena = " ".join((cena or "").split())[:CENA_TETO]
    if not cena:
        raise ErroDaIA("Descreva o fundo que você quer gerar.")
    if proporcao not in PROPORCOES:
        proporcao = "16:9"
    if _falsa():
        return _imagem_falsa(proporcao)
    if _geradas >= TETO_DE_IMAGENS:
        raise ErroDaIA(f"Já foram geradas {TETO_DE_IMAGENS} imagens nesta sessão. O teto "
                       "existe para um erro não gastar o seu saldo: feche e abra o editor "
                       "para gerar mais.")
    valor, _origem = chave()
    if not valor:
        raise ErroDaIA(f"Falta a chave do Gemini (crie uma em {ONDE_PEGAR_A_CHAVE}).")
    corpo = {"contents": [{"role": "user", "parts": [
                {"text": _pedido_de_fundo(cena, proporcao, lado_do_texto)}]}],
             "generationConfig": {"responseModalities": ["IMAGE"],
                                  "imageConfig": {"aspectRatio": proporcao}}}
    # Conta antes da resposta: uma tentativa recusada também é uma tentativa, e o teto
    # existe para segurar laço, não só gasto.
    _geradas += 1
    try:
        with _cliente(transporte, timeout=120) as cliente:
            r = cliente.post(f"{API}/models/{MODELO_DE_IMAGEM}:generateContent", json=corpo,
                             headers={"x-goog-api-key": valor})
    except httpx.HTTPError as erro:
        raise ErroDaIA("Não consegui falar com o Gemini. Confira a internet e tente de "
                       "novo.") from erro
    mensagem = _mensagem_do_google(r) if r.status_code >= 400 else ""
    baixa = mensagem.lower()
    if r.status_code in (402, 403, 429) and ("limit: 0" in baixa or "billing" in baixa
                                             or "free" in baixa):
        raise ErroDaIA(SEM_FATURAMENTO)
    if r.status_code == 429:
        raise ErroDaIA("A cota de imagens do Gemini acabou por agora. Tente de novo mais "
                       "tarde.")
    if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in baixa):
        raise ErroDaIA(f"O Google recusou a chave do Gemini (crie uma em "
                       f"{ONDE_PEGAR_A_CHAVE}).")
    if r.status_code >= 400:
        raise ErroDaIA(f"O Gemini não gerou a imagem ({r.status_code}: {mensagem[:160]}).")
    dados = r.json()
    for candidato in dados.get("candidates") or []:
        for parte in (candidato.get("content") or {}).get("parts", []):
            inline = parte.get("inlineData") or parte.get("inline_data") or {}
            if inline.get("data"):
                _anotar_gasto(proporcao, cena)
                return base64.b64decode(inline["data"])
    motivo = ((dados.get("promptFeedback") or {}).get("blockReason")
              or next((c.get("finishReason") for c in dados.get("candidates") or []), ""))
    raise ErroDaIA(f"O Gemini não devolveu imagem ({motivo or 'sem motivo dito'}). Tente "
                   "descrever a cena de outro jeito.")


__all__ = [
    "CORES",
    "FUNDOS",
    "LAYOUTS",
    "LUZES",
    "MAOS",
    "MODELOS",
    "ErroDaIA",
    "apagar_chave",
    "chave",
    "conferir",
    "esquema",
    "estado",
    "formula_gasta",
    "geracoes_restantes",
    "gerar_fundo",
    "limpar_chave",
    "mascarada",
    "montar_pedido",
    "salvar_chave",
    "sugerir",
    "validar_chave",
]
