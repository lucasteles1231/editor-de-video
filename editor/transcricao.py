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

        download_model(modelo, local_files_only=True)
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
                           local_files_only=modelo_baixado(modelo))
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


__all__ = ["IDIOMA_PADRAO", "MODELOS", "MODELO_PADRAO", "VARIAVEL_FALSA", "Palavra",
           "carregar", "dica_das_palavras", "identidade", "modelo_baixado", "salvar",
           "transcrever"]
