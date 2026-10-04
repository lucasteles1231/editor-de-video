"""
Os efeitos sonoros: dois sintetizados em código (o pop e o whoosh de sempre) e os da
Kenney, em domínio público (CC0), que vão junto em ``recursos/sons/``.

O catálogo, ``recursos/sons.json``, diz:

- **os temas:** para cada um, os sons de cada evento — a aparição (adesivo e ícone), a
  transição (zoom e pessoa andando) e o corte. Cada evento tem algumas variações, que se
  revezam pela ordem: o mesmo vídeo soa sempre igual;
- **as famílias por palavra:** "dinheiro" chama moedas, "errado" uma buzina;
- **as sequências:** sons montados de outros (as teclas, o tique-taque).

Todo som sai nivelado (os de arquivo são lidos uma vez só): os da Kenney vêm de pacotes
diferentes, com volumes que iam de um clique quase mudo a um impacto estourando, e o pop
sintetizado soava de 4 a 6 dB acima dos tons deles.
"""
from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from importlib.resources import files

import numpy as np

#: A voz manda: os efeitos, já nivelados, entram neste volume por baixo dela. Com ele, o
#: pop sai no mesmo volume de antes do nivelamento (35% do pico), e o resto, junto dele.
GANHO = 0.70
#: Nenhum efeito passa de meio segundo — mais que isso já é trilha, não pontuação. Os
#: "longos" do catálogo (os jingles e as sequências) vão até 1,2 s.
TETO_S = 0.5
TETO_LONGO_S = 1.2
#: Um som é nivelado pelos 50 ms mais fortes dele (o que o ouvido sente num som curto),
#: pesados como o ouvido pesa (:func:`_ponderar`). Pelo arquivo inteiro, uma moeda esparsa
#: ficava 20 dB abaixo do pop.
JANELA_S = 0.05
RMS_ALVO = 0.35
#: Os jingles ficam 3 dB abaixo: duram mais, e o ouvido soma. (As sequências, como as
#: teclas, são cliques espaçados: ficam no volume das partes.)
ALVO_DO_LONGO = 0.7
PICO_MAXIMO = 0.95
#: O som de pico alto e corpo baixo (o clique, a moeda, o pluck) só chegaria ao alvo
#: estourando. Um limitador abaixa os picos dele, e o corpo sobe até 6 dB além do que o
#: pico deixaria. Medido em 04/10/2026: as moedas e o pluck soavam de 10 a 12 dB abaixo
#: do pop, sumidos sob a voz; com o limitador e o peso do ouvido, ficam 3 dB abaixo.
REFORCO_MAXIMO = 2.0
#: O limitador olha 2 ms em volta de cada amostra: o ganho muda devagar, sem distorcer.
OLHAR_S = 0.002
#: A borda que some no fim de um som cortado pelo teto.
SOME_S = 0.03


def _envelope(n: int, ataque: float, queda: float) -> np.ndarray:
    """Sobe e desce nas bordas, para o som não estalar."""
    env = np.ones(n, dtype=np.float32)
    subida, descida = max(1, int(n * ataque)), max(1, int(n * queda))
    env[:subida] = np.linspace(0.0, 1.0, subida, endpoint=False)
    env[n - descida:] = np.linspace(1.0, 0.0, descida)
    return env


def _ruido(n: int, semente: int) -> np.ndarray:
    return np.random.default_rng(semente).uniform(-1.0, 1.0, n).astype(np.float32)


def whoosh(taxa: int, semente: int = 1, dur: float = 0.34) -> np.ndarray:
    """A transição: ruído num passa-baixa que vai abrindo — algo passando, não chiado."""
    n = int(min(dur, TETO_S) * taxa)
    r = _ruido(n, semente)
    corte = 0.02 + 0.33 * np.arange(n) / max(1, n - 1)
    saida = np.empty(n, dtype=np.float32)
    anterior = 0.0
    for i in range(n):
        anterior += corte[i] * (r[i] - anterior)
        saida[i] = anterior
    return saida * _envelope(n, 0.30, 0.55) * 2.2


def pop(taxa: int, semente: int = 1, dur: float = 0.12) -> np.ndarray:
    """A aparição: um seno curto que cai de tom depressa."""
    n = int(min(dur, TETO_S) * taxa)
    base = 620 + (semente % 5) * 40
    f = base * (1.0 - 0.45 * np.arange(n) / max(1, n - 1))
    fase = np.cumsum(2 * np.pi * f / taxa)
    return (np.sin(fase) * _envelope(n, 0.02, 0.85)).astype(np.float32)


VOZES = {"whoosh": whoosh, "pop": pop}


# ── o catálogo ────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def catalogo() -> dict:
    return json.loads((files("editor") / "recursos" / "sons.json").read_text("utf-8"))


def temas() -> dict[str, str]:
    """Os temas e o nome de cada um para quem usa."""
    return {nome: t["titulo"] for nome, t in catalogo()["temas"].items()}


def do_tema(tema: str, evento: str) -> list[str]:
    """As variações de um evento ("aparicao", "transicao", "corte") num tema."""
    t = catalogo()["temas"].get(tema) or catalogo()["temas"]["padrao"]
    return list(t[evento])


def ganho_do_evento(evento: str) -> float:
    return float(catalogo()["ganhos"].get(evento, 1.0))


def _arquivo(nome: str):
    return files("editor") / "recursos" / "sons" / f"{nome}.ogg"


def existe(nome: str) -> bool:
    c = catalogo()
    return nome in VOZES or nome in c["sequencias"] or _arquivo(nome).is_file()


@functools.lru_cache(maxsize=256)
def _amostras(nome: str, taxa: int) -> np.ndarray:
    """O som em mono, na taxa pedida, nivelado e cortado no teto (lido uma vez só). A
    sequência é montada das partes, que já vêm niveladas."""
    c = catalogo()
    longo = nome in c["longos"]
    if nome in c["sequencias"]:
        seq = c["sequencias"][nome]
        partes = [amostras(n, taxa) for n in seq["sons"]]
        passo = round(float(seq["passo"]) * taxa)
        saida = np.zeros(passo * (len(partes) - 1) + max(len(p) for p in partes), np.float32)
        for k, p in enumerate(partes):
            saida[k * passo:k * passo + len(p)] += p
        som = saida
    else:
        from editor import video as video_mod

        estereo = video_mod.ler_audio(_arquivo(nome))
        som = estereo.mean(axis=1).astype(np.float32) if len(estereo) else np.zeros(1, np.float32)
        if taxa != video_mod.TAXA:
            pontos = np.linspace(0, len(som) - 1, round(len(som) * taxa / video_mod.TAXA))
            som = np.interp(pontos, np.arange(len(som)), som).astype(np.float32)
        som = _nivelar(som, taxa, RMS_ALVO * (ALVO_DO_LONGO if longo else 1.0))
    n = int((TETO_LONGO_S if longo else TETO_S) * taxa)
    if len(som) > n:
        som = som[:n].copy()
        borda = max(1, int(SOME_S * taxa))
        som[-borda:] *= np.linspace(1.0, 0.0, borda, dtype=np.float32)
    return np.ascontiguousarray(som, dtype=np.float32)


def _rms_mais_forte(som: np.ndarray, janela: int) -> float:
    """O RMS da janela mais forte do som."""
    if len(som) <= janela:
        return float(np.sqrt(np.mean(som ** 2))) if len(som) else 0.0
    acumulado = np.concatenate([[0.0], np.cumsum(som.astype(np.float64) ** 2)])
    return float(np.sqrt(np.max(acumulado[janela:] - acumulado[:-janela]) / janela))


def _ponderar(som: np.ndarray, taxa: int) -> np.ndarray:
    """O som como o ouvido pesa, numa aproximação da curva K (ITU-R BS.1770): o agudo acima
    de 1,5 kHz conta 4 dB a mais, e o grave abaixo de 60 Hz quase nada. Sem isso, a moeda
    (aguda) parecia mais baixa do que soa, e o pop (médio) mais alto."""
    if len(som) < 2:
        return som
    f = np.fft.rfftfreq(len(som), 1 / taxa)
    prateleira = np.sqrt((1 + (f / 1500) ** 2 * 10 ** (4 / 10)) / (1 + (f / 1500) ** 2))
    passa_alta = f ** 2 / (f ** 2 + 60 ** 2)
    return np.fft.irfft(np.fft.rfft(som.astype(np.float64)) * prateleira * passa_alta,
                        len(som))


def volume_percebido(som: np.ndarray, taxa: int) -> float:
    """O RMS dos 50 ms mais fortes, pesado pelo ouvido: a medida do nivelamento."""
    return _rms_mais_forte(_ponderar(som, taxa), max(1, int(JANELA_S * taxa)))


def _vizinhanca(x: np.ndarray, h: int) -> np.ndarray:
    """Cada amostra com as ``h`` de cada lado (as bordas repetem a ponta)."""
    return np.lib.stride_tricks.sliding_window_view(np.pad(x, h, mode="edge"), 2 * h + 1)


def _limitar(som: np.ndarray, teto: float, taxa: int) -> np.ndarray:
    """Abaixa só o que passa do teto. O ganho de cada amostra é o menor que os picos em
    volta pedem, e a média dele em volta: nunca deixa um pico passar, e muda devagar."""
    if len(som) == 0 or float(np.max(np.abs(som))) <= teto:
        return som
    h = max(1, int(OLHAR_S * taxa))
    envelope = _vizinhanca(np.abs(som), h).max(axis=1)
    ganho = _vizinhanca(np.minimum(1.0, teto / np.maximum(envelope, 1e-9)), h).min(axis=1)
    ganho = _vizinhanca(ganho, h).mean(axis=1)
    return np.clip(som * ganho, -teto, teto).astype(np.float32)


def _nivelar(som: np.ndarray, taxa: int, alvo: float = RMS_ALVO) -> np.ndarray:
    """Os 50 ms mais fortes no ``alvo``, com o pico abaixo de :data:`PICO_MAXIMO`. O
    limitador come um pouco do RMS que o ganho deu, então há uma segunda passada."""
    pico = float(np.max(np.abs(som))) if len(som) else 0.0
    if pico < 1e-6:
        return som
    teto_do_ganho = PICO_MAXIMO / pico * REFORCO_MAXIMO
    ganho = min(alvo / max(volume_percebido(som, taxa), 1e-9), teto_do_ganho)
    saida = _limitar(som * ganho, PICO_MAXIMO, taxa)
    rms = volume_percebido(saida, taxa)
    if rms < alvo * 0.98 and ganho < teto_do_ganho:
        ganho = min(ganho * alvo / max(rms, 1e-9), teto_do_ganho)
        saida = _limitar(som * ganho, PICO_MAXIMO, taxa)
    return saida.astype(np.float32)


def amostras(nome: str, taxa: int, semente: int = 1) -> np.ndarray:
    """O som pelo nome, nivelado: sintetizado, de arquivo ou uma sequência."""
    if nome in VOZES:
        return _nivelar(VOZES[nome](taxa, semente=semente), taxa)
    return _amostras(nome, taxa)


# ── a trilha ──────────────────────────────────────────────────────────────


def trilha(sons: Sequence, duracao: float, taxa: int, volume: float = 1.0) -> np.ndarray:
    """Uma trilha mono com todos os efeitos nos seus instantes (``som.nome``, ``som.t`` e,
    se houver, ``som.ganho``)."""
    n = max(1, round(duracao * taxa))
    saida = np.zeros(n, dtype=np.float32)
    for k, som in enumerate(sons):
        if not existe(som.nome):
            continue
        dados = amostras(som.nome, taxa, semente=k + 1) * float(getattr(som, "ganho", 1.0))
        i0 = round(som.t * taxa)
        if i0 >= n:
            continue
        pedaco = dados[: n - i0]
        saida[i0:i0 + len(pedaco)] += pedaco
    return saida * GANHO * volume


def misturar(voz: np.ndarray, efeitos: np.ndarray) -> np.ndarray:
    """A voz (amostras × canais) com os efeitos por baixo, sem passar de ±1."""
    n = voz.shape[0]
    e = np.zeros(n, dtype=np.float32)
    e[: min(n, len(efeitos))] = efeitos[:n]
    saida = voz + e[:, None]
    pico = float(np.max(np.abs(saida))) if saida.size else 0.0
    return saida / pico * 0.98 if pico > 1.0 else saida


def demonstracao(tema: str, taxa: int, volume: float = 1.0) -> np.ndarray:
    """Os sons de um tema em fila, para ouvir na página: duas aparições, uma transição e
    dois cortes, com um respiro entre eles."""
    from types import SimpleNamespace

    fila = [("aparicao", 0), ("aparicao", 1), ("transicao", 0), ("corte", 0), ("corte", 1)]
    sons, t = [], 0.1
    for evento, k in fila:
        variacoes = do_tema(tema, evento)
        sons.append(SimpleNamespace(nome=variacoes[k % len(variacoes)], t=t,
                                    ganho=ganho_do_evento(evento)))
        t += 0.6
    return trilha(sons, t + 0.4, taxa, volume)


__all__ = ["GANHO", "VOZES", "amostras", "catalogo", "demonstracao", "do_tema", "existe",
           "ganho_do_evento", "misturar", "pop", "temas", "trilha", "volume_percebido",
           "whoosh"]
