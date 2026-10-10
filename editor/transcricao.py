"""
A transcrição: cada palavra dita e o instante em que ela acontece.

Usa o `faster-whisper` na própria máquina — nenhum áudio sai do computador. O
modelo é baixado na primeira vez e fica no cache do Hugging Face
(``~/.cache/huggingface`` no macOS e no Linux, ``%USERPROFILE%\\.cache\\huggingface``
no Windows); depois disso, a transcrição funciona sem internet.

**O tempo de fim de cada palavra sai cedo.** O Whisper marca o fim uns 30 a 300 ms
antes de o som acabar; por isso quem corta o áudio (:mod:`editor.cortes`) não corta
no tempo dele, e sim na pausa real perto dele.

Para testes há um transcritor falso, ligado por ``EDITOR_TRANSCRITOR=falso``: ele
devolve palavras inventadas, espalhadas pela duração do vídeo. Subir a interface num
teste sem ele rodaria o modelo de verdade — é fácil esquecer que "testar a página"
também processa o vídeo.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Os modelos oferecidos, com o tamanho do download.
MODELOS = {"tiny": "75 MB", "base": "145 MB", "small": "464 MB", "medium": "1,5 GB"}
#: ``small`` é o menor que transcreve português sem tropeçar a cada frase.
MODELO_PADRAO = "small"
#: A versão de cada modelo (o commit do repositório da Systran no Hugging Face, conferido
#: em 10/10/2026): o que se baixa é sempre o que foi testado, e não o que estiver lá no dia.
REVISOES = {"tiny": "d90ca5fe260221311c53c58e660288d3deb8d356",
            "base": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
            "small": "536b0662742c02347bc0e980a01041f333bce120",
            "medium": "08e178d48790749d25932bbc082711ddcfdfbc4f"}
IDIOMA_PADRAO = "pt"

#: A variável que liga o transcritor falso (só testes).
VARIAVEL_FALSA = "EDITOR_TRANSCRITOR"

# O cache do Hugging Face reclama de link simbólico no Windows sem modo de
# desenvolvedor; ele funciona copiando, e o aviso só assusta quem usa.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# E no primeiro download o servidor dele pede um HF_TOKEN ("unauthenticated
# requests"): não é preciso conta nenhuma para baixar o modelo, e o aviso fazia parecer
# que era. A barra de progresso do download continua aparecendo.
os.environ.setdefault("HF_HUB_VERBOSITY", "error")


@dataclass(frozen=True)
class Palavra:
    """Uma palavra como foi dita (com pontuação e maiúsculas) e quando, em segundos."""

    texto: str
    inicio: float
    fim: float
    prob: float = 1.0


Progresso = Callable[[float], None]


def modelo_baixado(modelo: str = MODELO_PADRAO) -> bool:
    """Se o modelo já está no cache — para avisar do download antes de começar."""
    try:
        from faster_whisper.utils import download_model

        download_model(modelo, local_files_only=True, revision=REVISOES.get(modelo))
        return True
    except Exception:
        return False


def _falso(duracao: float) -> list[Palavra]:
    """Palavras inventadas, uma a cada 0,4 s, com uma pausa longa a cada frase."""
    frases = [
        "Hoje eu vou mostrar como funciona o editor.",
        "Ele corta as pausas e coloca a legenda sozinho.",
        "Custa 3 reais e cabe no celular.",
    ]
    saida, t, i = [], 0.3, 0
    while t < duracao - 0.5:
        for w in frases[i % len(frases)].split():
            if t >= duracao - 0.5:
                break
            saida.append(Palavra(w, round(t, 3), round(t + 0.32, 3)))
            t += 0.4
        t += 0.9                       # a pausa entre frases, que o corte encurta
        i += 1
    return saida


def transcrever(caminho: Path, *, idioma: str = IDIOMA_PADRAO, modelo: str = MODELO_PADRAO,
                duracao: float | None = None, progresso: Progresso | None = None,
                dica: str = "") -> list[Palavra]:
    """As palavras do áudio de ``caminho`` (vídeo ou áudio), em ordem.

    ``dica`` são palavras que o Whisper deve esperar ouvir (as do bipe, por exemplo).
    """
    if os.environ.get(VARIAVEL_FALSA, "").strip().lower() == "falso":
        if progresso:
            progresso(1.0)
        return _falso(duracao or 10.0)

    from faster_whisper import WhisperModel

    from editor.video import ler_audio_mono

    # O áudio é lido aqui, e não pelo faster-whisper: a leitura dele passa ao PyAV
    # um parâmetro que o PyAV 19 removeu (metadata_errors), e o editor já lê áudio
    # de qualquer vídeo pelo próprio PyAV.
    audio = ler_audio_mono(Path(caminho), 16_000)
    if audio.size == 0:
        return []
    nucleos = max(1, (os.cpu_count() or 2) - 1)
    logger.info("carregando o Whisper %s (%d núcleos)", modelo, nucleos)
    # Com o modelo já baixado, ele é lido direto do cache: sem isso o faster-whisper
    # pergunta ao Hugging Face por uma versão nova a cada vídeo (e espera a rede cair
    # para desistir, quando não há internet).
    whisper = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=nucleos,
                           local_files_only=modelo_baixado(modelo),
                           revision=REVISOES.get(modelo))
    # O VAD descarta trechos sem fala antes de transcrever: sem ele, música e
    # silêncio viram frases inventadas ("Obrigado por assistir!").
    # A dica vai para o começo de cada janela de 30 s ("hotwords"), e não só da
    # primeira ("initial_prompt"): num vídeo longo, ela valeria só para os primeiros
    # minutos. Medido em 05/10 com 5 áudios de notícia: sem a dica, o modelo small
    # ouvia "coca ainda" e "de captação entre membramentos"; com ela, "cocaína" e
    # "decapitação e desmembramento", e o resto do texto não mudou. O ponto no fim
    # conta: sem ele, a fala vira continuação da lista e perde os pontos finais.
    segmentos, _info = whisper.transcribe(audio, language=idioma or None,
                                          word_timestamps=True, vad_filter=True,
                                          hotwords=dica or None)
    total = audio.size / 16_000
    palavras: list[Palavra] = []
    for seg in segmentos:
        for w in seg.words or []:
            texto = (w.word or "").strip()
            if texto:
                palavras.append(Palavra(texto, round(float(w.start), 3),
                                        round(float(w.end), 3),
                                        round(float(w.probability), 3)))
        if progresso and total > 0:
            progresso(min(1.0, float(seg.end) / total))
    if progresso:
        progresso(1.0)
    return palavras


def salvar(palavras: list[Palavra], caminho: Path, *, origem: dict) -> None:
    """Guarda a transcrição com a identidade do vídeo, para não transcrever de novo."""
    dados = {"origem": origem, "palavras": [asdict(p) for p in palavras]}
    Path(caminho).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def carregar(caminho: Path, *, origem: dict) -> list[Palavra] | None:
    """A transcrição guardada, se for do mesmo vídeo e com as mesmas escolhas."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if dados.get("origem") != origem:
        return None
    return [Palavra(**p) for p in dados.get("palavras", [])]


def identidade(video: Path, *, idioma: str, modelo: str, dica: str = "") -> dict:
    """O que faz duas transcrições serem a mesma: o arquivo (tamanho e data) e as escolhas."""
    st = Path(video).stat()
    origem = {"arquivo": Path(video).name, "tamanho": st.st_size,
              "modificado": int(st.st_mtime), "idioma": idioma, "modelo": modelo}
    # só entra quando existe: as transcrições guardadas sem dica continuam valendo
    if dica:
        origem["dica"] = dica
    return origem


def dica_das_palavras(palavras: list[str]) -> str:
    """A dica para o Whisper: a lista em uma frase, com o ponto final."""
    return ", ".join(palavras) + "." if palavras else ""


# ── o texto conhecido ────────────────────────────────────────────────────
# Quando o texto falado é conhecido (a leitura da "Minha voz", ou o roteiro que a voz
# sintetizada narrou), o Whisper só dá os tempos: a comparação é palavra a palavra, e a
# legenda volta para a grafia do texto.

_UNIDADES = ("zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
             "dez", "onze", "doze", "treze", "catorze", "quinze", "dezesseis", "dezessete",
             "dezoito", "dezenove")
_DEZENAS = ("", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",
            "oitenta", "noventa")
_CENTENAS = ("", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos",
             "setecentos", "oitocentos", "novecentos")
_GRANDES = ((10**9, "um bilhão", "bilhões"), (10**6, "um milhão", "milhões"), (1000, "mil", "mil"))


def por_extenso(n: int) -> str:
    """O número inteiro por extenso, como se fala: 3500 é "três mil e quinhentos"."""
    if n < 20:
        return _UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _DEZENAS[d] + (f" e {_UNIDADES[u]}" if u else "")
    if n == 100:
        return "cem"
    if n < 1000:
        c, r = divmod(n, 100)
        return _CENTENAS[c] + (f" e {por_extenso(r)}" if r else "")
    for valor, um, varios in _GRANDES:
        if n >= valor:
            q, r = divmod(n, valor)
            cabeca = um if q == 1 else f"{por_extenso(q)} {varios}"
            if not r:
                return cabeca
            # "mil e quinhentos", "mil e vinte", mas "mil duzentos e trinta"
            return cabeca + (" e " if r < 100 or r % 100 == 0 else " ") + por_extenso(r)
    return str(n)


def chaves(texto: str) -> list[str]:
    """As palavras de um texto do jeito que se comparam: minúsculas, sem acento, sem
    pontuação e com os números por extenso (o Whisper escreve "3.500" o que foi lido
    "três mil e quinhentos", e "15%" o que foi lido "quinze por cento")."""
    import re
    import unicodedata

    t = texto.lower().replace("%", " por cento ")
    t = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", t)                 # 3.500 → 3500
    t = re.sub(r"\d{1,12}", lambda m: f" {por_extenso(int(m.group()))} ", t)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", t)


def texto_ao_lado(audio: Path) -> str | None:
    """O texto que se sabe que foi falado neste áudio (``narracao.roteiro.txt`` ao lado de
    ``narracao.wav``), ou ``None``."""
    ao_lado = Path(audio).with_suffix(".roteiro.txt")
    try:
        return ao_lado.read_text(encoding="utf-8") if ao_lado.is_file() else None
    except OSError:
        return None


#: Abaixo disto, o texto não é o deste áudio, e as palavras do Whisper ficam como estão.
CASAMENTO_MINIMO = 0.5


def ajustar_ao_texto(palavras: list[Palavra], texto: str) -> list[Palavra]:
    """As palavras escritas como no texto, nos tempos que o Whisper ouviu.

    Cada palavra do texto pega o tempo das palavras ouvidas que casaram com ela. As que
    não casaram (a sigla que o Whisper escreveu de outro jeito, "Peggy" no lugar de
    "PEGI") dividem o intervalo entre as vizinhas que casaram, pelo número de letras."""
    from difflib import SequenceMatcher

    tokens: list[str] = []
    for t in texto.split():
        if chaves(t) or not tokens:
            tokens.append(t)
        else:                                  # um travessão solto vai junto da anterior
            tokens[-1] += f" {t}"
    esperadas, de_qual = [], []
    for i, t in enumerate(tokens):
        for k in chaves(t):
            esperadas.append(k)
            de_qual.append(i)
    ouvidas, de_quem = [], []
    for j, w in enumerate(palavras):
        for k in chaves(w.texto):
            ouvidas.append(k)
            de_quem.append(j)
    if not esperadas or not ouvidas:
        return palavras
    blocos = SequenceMatcher(None, esperadas, ouvidas, autojunk=False).get_matching_blocks()
    casadas: dict[int, set[int]] = {}
    for a, b, n in blocos:
        for d in range(n):
            casadas.setdefault(de_qual[a + d], set()).add(de_quem[b + d])
    if sum(n for _a, _b, n in blocos) < CASAMENTO_MINIMO * len(esperadas):
        logger.warning("o texto ao lado não é o deste áudio: a legenda fica com o Whisper")
        return palavras

    tempos: list[tuple[float, float, float] | None] = []
    for i in range(len(tokens)):
        js = casadas.get(i)
        tempos.append(None if not js else (min(palavras[j].inicio for j in js),
                                           max(palavras[j].fim for j in js),
                                           sum(palavras[j].prob for j in js) / len(js)))
    # "3.500" ouvido casa com as quatro palavras de "três mil e quinhentos": elas dividem
    # o tempo dele, em vez de aparecerem todas juntas.
    i = 0
    while i < len(tokens):
        k = i + 1
        while k < len(tokens) and tempos[i] is not None and tempos[k] == tempos[i]:
            k += 1
        if k - i > 1:
            a, b, prob = tempos[i]
            letras = [max(1, len(tokens[m])) for m in range(i, k)]
            t = a
            for m, n in zip(range(i, k), letras, strict=True):
                fim = t + (b - a) * n / sum(letras)
                tempos[m] = (t, fim, prob)
                t = fim
        i = k
    i = 0
    while i < len(tokens):
        if tempos[i] is not None:
            i += 1
            continue
        k = i
        while k < len(tokens) and tempos[k] is None:
            k += 1
        antes, depois = (tempos[i - 1] if i else None), (tempos[k] if k < len(tokens) else None)
        a = antes[1] if antes else palavras[0].inicio
        b = depois[0] if depois else max(palavras[-1].fim, a + 0.3 * (k - i))
        b = max(b, a + 0.02 * (k - i))
        letras = [max(1, len(tokens[m])) for m in range(i, k)]
        t = a
        for m, n in zip(range(i, k), letras, strict=True):
            fim = t + (b - a) * n / sum(letras)
            tempos[m] = (t, fim, 0.5)
            t = fim
        i = k
    return [Palavra(tok, round(t[0], 3), round(max(t[1], t[0] + 0.02), 3), round(t[2], 3))
            for tok, t in zip(tokens, tempos, strict=True) if t is not None]


__all__ = ["CASAMENTO_MINIMO", "IDIOMA_PADRAO", "MODELOS", "MODELO_PADRAO", "REVISOES",
           "VARIAVEL_FALSA",
           "Palavra", "ajustar_ao_texto", "carregar", "chaves", "dica_das_palavras",
           "identidade", "modelo_baixado", "por_extenso", "salvar", "texto_ao_lado",
           "transcrever"]
