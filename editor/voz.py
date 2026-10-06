"""
A voz: juntar as partes, limpar, nivelar, a cadeia de estúdio e o bipe.

Portado dos scripts de voz do vídeo de referência, onde cada etapa foi ajustada ouvindo
e medindo as gravações dele:

- **original:** a voz como veio. Com várias partes, elas só são aparadas e juntadas.
- **limpa:** cada parte perde o grave de fundo, o eco do cômodo (as caudas das frases
  levavam de 400 a 860 ms para sumir) e o chiado, e vai a −20 LUFS antes de juntar (o
  parágrafo 2 vinha 5 dB acima dos outros). Depois, a voz "nítida": o "embolado" de
  250 Hz sai, a presença de 3 kHz sobe, o "sss" é segurado e uma compressão leve põe
  tudo no mesmo plano.
- **estúdio:** a "pop-limpo", a escolhida pelo dono: a limpa, mais o redutor de ruído
  antes de tudo (a compressão levantava o chiado 12 dB nas pausas), o exciter e o
  brilho, a compressão em duas etapas, o expansor nas pausas e a dobra em estéreo.

O fim é sempre −15 LUFS com o pico abaixo de −1,5 dB, o volume dos Shorts.

Os filtros vêm do FFmpeg que já está dentro do PyAV (``av.filter.Graph``); o eco, o
ruído e o expansor são numpy. Nada a instalar.
"""
from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from editor import censura
from editor import video as video_mod
from editor.transcricao import Palavra

TAXA = video_mod.TAXA
NIVEIS = ("original", "limpa", "estudio")

#: Cada parte vai a este volume antes de juntar; o resultado, ao final.
PARTE_LUFS = -20.0
FINAL_LUFS = -15.0
PICO_DB = -1.5
#: A pausa entre duas partes.
PAUSA_S = 0.3
#: O silêncio das pontas: o que fica abaixo disto sai, guardando esta margem.
SILENCIO_DB = -50.0
MARGEM_S = 0.1
#: O eco do cômodo (medido nas gravações do chat: 0,8 s deixou as caudas em 80–330 ms).
T60 = 0.8

#: A voz "nítida" do chat, depois da limpeza.
NITIDA = ",".join([
    "highpass=f=90",
    "equalizer=f=250:t=q:w=1.0:g=-3",
    "equalizer=f=3000:t=q:w=1.0:g=2",
    "deesser=i=0.4:m=0.5:f=0.5",
    "agate=threshold=0.015:ratio=2:range=0.25:attack=5:release=150",
    "acompressor=threshold=-24dB:ratio=2.5:attack=8:release=150:knee=4:makeup=1",
])
#: A cadeia de estúdio ("pop-limpo"): equalizador, exciter, brilho, "sss" e as duas
#: compressões.
ESTUDIO = ",".join([
    "highpass=f=100",
    "equalizer=f=250:t=q:w=1.0:g=-3",
    "equalizer=f=500:t=q:w=1.4:g=-1.5",
    "equalizer=f=3000:t=q:w=1.0:g=2",
    "aexciter=amount=1.5:drive=6:freq=6000:ceil=16000",
    "treble=g=2.5:f=10000",
    "deesser=i=0.5:m=0.5:f=0.5",
    "acompressor=threshold=-20dB:ratio=4:attack=3:release=60:knee=3:makeup=2",
    "acompressor=threshold=-26dB:ratio=2:attack=30:release=250:knee=6:makeup=2",
])
#: A dobra: duas cópias moduladas, uma de cada lado.
DOBRA = 0.30
CORO_ESQUERDA = "chorus=0:1:21:1:0.35:1.6"
CORO_DIREITA = "chorus=0:1:29:1:0.27:1.9"

#: O bipe: 1 kHz, rampas de 6 ms, no mínimo 0,1 s.
BIPE_HZ = 1000
# O chat usava 0,1 s, com a sílaba medida por um alinhador de 2 GB. Aqui ela é estimada
# pelas letras, e 0,1 s deixou passar "decapitação" (transcrita de novo em 05/10, a sílaba
# "pi" tinha caído em 100 ms): a folga de cada lado e o mínimo maior cobrem o erro.
BIPE_MINIMO_S = 0.16
FOLGA_DO_BIPE_S = 0.03
RAMPA_S = 0.006


# ── os filtros do FFmpeg ─────────────────────────────────────────────────


def filtrar(x: np.ndarray, cadeia: str) -> np.ndarray:
    """O áudio mono (``float32``, ``TAXA``) passado por uma cadeia de filtros do FFmpeg,
    no mesmo comprimento."""
    import av

    grafo = av.filter.Graph()
    anterior = grafo.add_abuffer(sample_rate=TAXA, format="flt", layout="mono",
                                 time_base=Fraction(1, TAXA))
    for parte in cadeia.split(","):
        nome, _, args = parte.partition("=")
        filtro = grafo.add(nome, args or None)
        anterior.link_to(filtro)
        anterior = filtro
    formato = grafo.add("aformat", "sample_fmts=flt:channel_layouts=mono")
    anterior.link_to(formato)
    saida = grafo.add("abuffersink")
    formato.link_to(saida)
    grafo.configure()

    pedacos: list[np.ndarray] = []

    def colher() -> None:
        while True:
            try:
                quadro = grafo.pull()
            except (av.BlockingIOError, BlockingIOError, EOFError):
                return
            pedacos.append(quadro.to_ndarray().reshape(-1))

    x = np.ascontiguousarray(x, dtype=np.float32)
    for i in range(0, len(x), 4096):
        quadro = av.AudioFrame.from_ndarray(x[i:i + 4096].reshape(1, -1), format="flt",
                                            layout="mono")
        quadro.sample_rate = TAXA
        quadro.pts = i
        quadro.time_base = Fraction(1, TAXA)
        grafo.push(quadro)
        colher()
    grafo.push(None)
    colher()
    y = np.concatenate(pedacos) if pedacos else np.zeros(0, np.float32)
    if len(y) < len(x):
        y = np.pad(y, (0, len(x) - len(y)))
    return np.ascontiguousarray(y[: len(x)], dtype=np.float32)


# ── o eco, o ruído e o expansor (numpy) ──────────────────────────────────


def _stft(x: np.ndarray, n: int, hop: int) -> tuple[np.ndarray, np.ndarray]:
    janela = np.hanning(n).astype(np.float32)
    com_bordas = np.concatenate([np.zeros(n, np.float32), x, np.zeros(n, np.float32)])
    quadros = np.lib.stride_tricks.sliding_window_view(com_bordas, n)[::hop]
    return np.fft.rfft(quadros * janela, axis=1), janela


def _istft(espectro: np.ndarray, janela: np.ndarray, n: int, hop: int, comprimento: int
           ) -> np.ndarray:
    quadros = np.fft.irfft(espectro, n=n, axis=1).astype(np.float32) * janela
    saida = np.zeros(hop * (len(quadros) - 1) + n, np.float32)
    norma = np.zeros_like(saida)
    quadrado = janela ** 2
    for i, q in enumerate(quadros):
        saida[i * hop:i * hop + n] += q
        norma[i * hop:i * hop + n] += quadrado
    saida /= np.maximum(norma, 1e-6)
    return saida[n:n + comprimento]


def tirar_eco(x: np.ndarray, t60: float = T60, atraso: float = 0.05,
              piso_db: float = -14.0) -> np.ndarray:
    """Tira a reverberação tardia do cômodo (Lebart e outros): a cauda em ``t`` é prevista
    pelo sinal de ``atraso`` antes, decaindo pelo T60 da sala, e subtraída no espectro.
    A voz direta fica."""
    if len(x) < 2048:
        return x
    n, hop = 1024, 256
    espectro, janela = _stft(x.astype(np.float32), n, hop)
    potencia = np.abs(espectro) ** 2
    lisa = potencia.copy()
    for i in range(1, len(lisa)):
        lisa[i] = 0.6 * lisa[i - 1] + 0.4 * potencia[i]
    passo = max(1, round(atraso * TAXA / hop))
    queda = np.exp(-2 * (3 * np.log(10) / t60) * atraso)
    tarde = np.zeros_like(potencia)
    tarde[passo:] = queda * lisa[:-passo]
    ganho = np.maximum(1 - tarde / np.maximum(potencia, 1e-12), 10 ** (piso_db / 20))
    for i in range(1, len(ganho)):
        ganho[i] = np.maximum(ganho[i], 0.5 * ganho[i - 1])
    return _istft(espectro * ganho, janela, n, hop, len(x))


def tirar_ruido(x: np.ndarray, desvios: float = 1.5, reducao_db: float = -20.0
                ) -> np.ndarray:
    """Um portão espectral: aprende o ruído nos 10% de quadros mais quietos e baixa, faixa
    por faixa, o que fica abaixo dele. A máscara é suavizada no tempo e na frequência,
    para não "borbulhar"."""
    if len(x) < 2048:
        return x
    n, hop = 1024, 256
    espectro, janela = _stft(x.astype(np.float32), n, hop)
    db = 20 * np.log10(np.abs(espectro) + 1e-10)
    energia = db.mean(axis=1)
    quietos = db[energia <= np.percentile(energia, 10)]
    limiar = quietos.mean(axis=0) + desvios * quietos.std(axis=0)
    mascara = (db > limiar).astype(np.float32)
    mascara = _media_movel(mascara, 5, 1)
    mascara = _media_movel(mascara, 7, 0)
    piso = 10 ** (reducao_db / 20)
    ganho = piso + (1 - piso) * np.clip(mascara, 0, 1)
    return _istft(espectro * ganho, janela, n, hop, len(x))


def _media_movel(m: np.ndarray, largura: int, eixo: int) -> np.ndarray:
    """A média de ``largura`` vizinhos ao longo de um eixo (o ``np.convolve(..., "same")``
    do chat, de uma vez para a matriz inteira)."""
    m = np.moveaxis(m, eixo, 0)
    soma = np.concatenate([np.zeros((1, *m.shape[1:])), np.cumsum(m, axis=0, dtype=np.float64)])
    meio, n = largura // 2, m.shape[0]
    idx = np.arange(n)
    a, b = np.clip(idx - meio, 0, n), np.clip(idx + meio + 1, 0, n)
    return np.moveaxis((soma[b] - soma[a]) / largura, 0, eixo).astype(np.float32)


def expansor(x: np.ndarray, abaixo_db: float = 28.0, faixa_db: float = -30.0,
             razao: float = 3.0, ataque: float = 0.003, solta: float = 0.15,
             segura: float = 0.06) -> np.ndarray:
    """Um expansor para baixo: o que fica mais baixo que (a fala − ``abaixo_db``) desce
    mais, e as pausas ficam quietas sem cortar palavra."""
    passo = TAXA // 1000
    if len(x) < passo * 20:
        return x
    janelas = np.lib.stride_tricks.sliding_window_view(np.pad(x, (0, passo * 10)),
                                                       passo * 10)[::passo]
    janelas = janelas[: len(x) // passo + 1]
    nivel = 20 * np.log10(np.sqrt((janelas.astype(np.float64) ** 2).mean(axis=1)) + 1e-10)
    limiar = np.percentile(nivel, 90) - abaixo_db
    alvo = np.where(nivel >= limiar, 0.0, np.maximum(faixa_db, (nivel - limiar) * (razao - 1)))
    ganho = np.empty_like(alvo)
    atual, retido = alvo[0], 0
    a = 1 - np.exp(-1 / (ataque * 1000))
    r = 1 - np.exp(-1 / (solta * 1000))
    for i, t in enumerate(alvo):
        if t >= atual:
            atual += (t - atual) * a
            retido = int(segura * 1000)
        elif retido > 0:
            retido -= 1
        else:
            atual += (t - atual) * r
        ganho[i] = atual
    por_amostra = np.interp(np.arange(len(x)), np.arange(len(ganho)) * passo, ganho)
    return (x * 10 ** (por_amostra / 20)).astype(np.float32)


# ── o volume (ITU-R BS.1770) ─────────────────────────────────────────────


@functools.lru_cache(maxsize=8)
def _curva_k(n: int) -> np.ndarray:
    """A resposta da curva K (as duas biquadradas da BS.1770, em 48 kHz) nas faixas de
    uma FFT de ``n`` pontos."""
    z = np.exp(-1j * np.linspace(0, np.pi, n // 2 + 1))

    def biquad(b: Sequence[float], a: Sequence[float]) -> np.ndarray:
        return (b[0] + b[1] * z + b[2] * z ** 2) / (a[0] + a[1] * z + a[2] * z ** 2)

    prateleira = biquad([1.53512485958697, -2.69169618940638, 1.19839281085285],
                        [1.0, -1.69065929318241, 0.73248077421585])
    passa_alta = biquad([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])
    return np.abs(prateleira * passa_alta)


def lufs(x: np.ndarray) -> float:
    """O volume integrado (LUFS) de um áudio mono ou estéreo, com os dois portões da
    BS.1770 (o absoluto em −70 e o relativo em −10). A curva K é aplicada pela FFT, em
    pedaços."""
    canais = x[:, None] if x.ndim == 1 else x
    if len(canais) < TAXA * 0.4:
        return -70.0
    pedaco = 1 << 19
    pesados = []
    for c in range(canais.shape[1]):
        partes = []
        for i in range(0, len(canais), pedaco):
            s = canais[i:i + pedaco, c].astype(np.float64)
            n = 1 << int(np.ceil(np.log2(max(2, len(s)))))
            partes.append(np.fft.irfft(np.fft.rfft(s, n) * _curva_k(n), n)[: len(s)])
        pesados.append(np.concatenate(partes) ** 2)
    bloco, passo = int(0.4 * TAXA), int(0.1 * TAXA)
    acumulado = [np.concatenate([[0.0], np.cumsum(p)]) for p in pesados]
    inicios = np.arange(0, len(canais) - bloco + 1, passo)
    energia = sum((a[inicios + bloco] - a[inicios]) / bloco for a in acumulado)
    volume = -0.691 + 10 * np.log10(np.maximum(energia, 1e-12))
    validos = energia[volume > -70]
    if not len(validos):
        return -70.0
    relativo = -0.691 + 10 * np.log10(validos.mean()) - 10
    finais = validos[(-0.691 + 10 * np.log10(validos)) > relativo]
    return float(-0.691 + 10 * np.log10(finais.mean())) if len(finais) else -70.0


def nivelar(x: np.ndarray, alvo: float) -> np.ndarray:
    atual = lufs(x)
    if atual <= -69.9:
        return x
    return (x * 10 ** ((alvo - atual) / 20)).astype(np.float32)


def limitar(x: np.ndarray, pico_db: float = PICO_DB) -> np.ndarray:
    """Abaixa só os picos acima do teto, com o ganho mudando em 2 ms."""
    teto = 10 ** (pico_db / 20)
    picos = np.abs(x) if x.ndim == 1 else np.abs(x).max(axis=1)
    if not len(picos) or picos.max() <= teto:
        return x
    h = max(1, int(0.002 * TAXA))
    vizinhanca = np.lib.stride_tricks.sliding_window_view(np.pad(picos, h, mode="edge"),
                                                          2 * h + 1)
    ganho = np.minimum(1.0, teto / np.maximum(vizinhanca.max(axis=1), 1e-9))
    ganho = np.lib.stride_tricks.sliding_window_view(np.pad(ganho, h, mode="edge"),
                                                     2 * h + 1).min(axis=1)
    ganho = np.convolve(np.pad(ganho, h, mode="edge"), np.ones(2 * h + 1) / (2 * h + 1),
                        mode="valid")
    y = x * (ganho if x.ndim == 1 else ganho[:, None])
    return np.clip(y, -teto, teto).astype(np.float32)


# ── as partes ────────────────────────────────────────────────────────────


def aparar(x: np.ndarray) -> tuple[np.ndarray, float]:
    """O áudio sem o silêncio das pontas (guardando uma margem), e quanto saiu do
    começo, em segundos."""
    passo = int(0.01 * TAXA)
    if len(x) < passo * 3:
        return x, 0.0
    janelas = x[: len(x) // passo * passo].reshape(-1, passo)
    db = 20 * np.log10(np.sqrt((janelas.astype(np.float64) ** 2).mean(axis=1)) + 1e-10)
    som = np.flatnonzero(db > SILENCIO_DB)
    if not len(som):
        return x, 0.0
    margem = int(MARGEM_S * TAXA)
    ini = max(0, som[0] * passo - margem)
    fim = min(len(x), (som[-1] + 1) * passo + margem)
    return x[ini:fim], float(ini) / TAXA


@dataclass
class Parte:
    """Onde cada arquivo ficou no áudio junto."""

    inicio: float
    #: Quanto saiu do começo do arquivo (o silêncio aparado).
    corte: float
    duracao: float


def juntar(partes: Sequence[np.ndarray], nivel: str = "original"
           ) -> tuple[np.ndarray, list[Parte]]:
    """As partes (mono) em ordem, com 0,3 s entre elas. Com mais de uma, as pontas de cada
    uma são aparadas. Fora do "original", cada uma perde o grave e o eco do cômodo e vai a
    −20 LUFS antes de juntar; na "limpa", também o chiado (no "estúdio", ele sai depois,
    no começo da cadeia, como no chat)."""
    pausa = np.zeros(int(PAUSA_S * TAXA), np.float32)
    juntas, onde, t = [], [], 0.0
    for k, x in enumerate(partes):
        corte = 0.0
        if len(partes) > 1:
            x, corte = aparar(x)
        if nivel != "original":
            x = tirar_eco(filtrar(x, "highpass=f=80"))
            if nivel == "limpa":
                x = tirar_ruido(x)
            x = nivelar(x, PARTE_LUFS)
        if k:
            juntas.append(pausa)
            t += PAUSA_S
        juntas.append(x.astype(np.float32))
        onde.append(Parte(round(float(t), 4), round(float(corte), 4),
                          round(len(x) / TAXA, 4)))
        t += len(x) / TAXA
    audio = np.concatenate(juntas) if juntas else np.zeros(0, np.float32)
    return audio, onde


def palavras_nas_partes(por_parte: Sequence[Sequence[Palavra]], partes: Sequence[Parte]
                        ) -> list[Palavra]:
    """As palavras de cada parte no tempo do áudio junto. Transcrever parte por parte é
    bem mais preciso que o arquivo inteiro: no chat, o Whisper adiantou até 1 s as
    palavras dos parágrafos do meio."""
    saida = []
    for palavras, p in zip(por_parte, partes, strict=True):
        for w in palavras:
            ini, fim = w.inicio - p.corte, w.fim - p.corte
            if fim <= 0 or ini >= p.duracao:
                continue
            saida.append(Palavra(w.texto, round(float(p.inicio + max(0.0, ini)), 3),
                                 round(float(p.inicio + min(p.duracao, fim)), 3)))
    return saida


# ── o estilo ─────────────────────────────────────────────────────────────


def tratar(x: np.ndarray, nivel: str) -> np.ndarray:
    """A voz mono (já juntada e, se for o caso, limpa) no estilo pedido, em estéreo
    (amostras × 2), a −15 LUFS. Em "original", só vira estéreo."""
    if nivel == "original":
        return np.ascontiguousarray(np.stack([x, x], axis=1).astype(np.float32))
    voz = filtrar(x, NITIDA)
    if nivel == "limpa":
        estereo = np.stack([voz, voz], axis=1)
    else:
        # A ordem do chat: a nítida, nivelada; depois o redutor de ruído (o equalizador e
        # a compressão levantariam o chiado), a cadeia e o expansor, que fecha as pausas
        # antes da dobra, para ela não copiar ruído.
        voz = expansor(filtrar(tirar_ruido(nivelar(voz, FINAL_LUFS)), ESTUDIO))
        esquerda = filtrar(voz, CORO_ESQUERDA)
        direita = filtrar(voz, CORO_DIREITA)
        rms = float(np.sqrt(np.mean(voz.astype(np.float64) ** 2)) + 1e-12)
        ajuste_e = rms / (float(np.sqrt(np.mean(esquerda.astype(np.float64) ** 2))) + 1e-12)
        ajuste_d = rms / (float(np.sqrt(np.mean(direita.astype(np.float64) ** 2))) + 1e-12)
        estereo = np.stack([voz + DOBRA * esquerda * ajuste_e,
                            voz + DOBRA * direita * ajuste_d], axis=1)
    return limitar(nivelar(estereo.astype(np.float32), FINAL_LUFS))


# ── o bipe ───────────────────────────────────────────────────────────────


def _envelope(x: np.ndarray, passo: int) -> np.ndarray:
    n = len(x) // passo
    if n == 0:
        return np.zeros(0)
    return np.sqrt((x[: n * passo].astype(np.float64).reshape(n, passo) ** 2).mean(axis=1))


def trecho_da_palavra(x: np.ndarray, w: Palavra) -> tuple[float, float]:
    """Onde a palavra está de verdade, medido no áudio em volta do tempo do Whisper: o
    começo é o primeiro trecho com voz depois do vale de antes dela, e o fim, o último
    antes do vale de depois. Sem vale claro, valem os tempos do Whisper."""
    passo = int(0.01 * TAXA)
    a = max(0, int((w.inicio - 0.25) * TAXA))
    b = min(len(x), int((w.fim + 0.25) * TAXA))
    env = _envelope(x[a:b], passo)
    if len(env) < 5:
        return w.inicio, w.fim
    db = 20 * np.log10(env + 1e-10)
    limiar = db.max() - 22
    ativo = np.flatnonzero(db > limiar)
    if not len(ativo):
        return w.inicio, w.fim
    centro = int(((w.inicio + w.fim) / 2 * TAXA - a) / passo)
    centro = int(np.clip(centro, ativo[0], ativo[-1]))
    # o trecho contínuo de voz que contém o meio da palavra (vãos de até 60 ms contam)
    ini = fim = centro
    while ini > 0 and (db[ini - 1] > limiar or (ini > 6 and db[ini - 6:ini].max() > limiar)):
        ini -= 1
    while fim < len(db) - 1 and (db[fim + 1] > limiar
                                 or (fim < len(db) - 7 and db[fim + 1:fim + 7].max() > limiar)):
        fim += 1
    medido_ini, medido_fim = (a + ini * passo) / TAXA, (a + (fim + 1) * passo) / TAXA
    # o trecho medido não pode engolir as vizinhas: fica preso perto do Whisper
    ini_final = min(max(medido_ini, w.inicio - 0.2), w.inicio + 0.2)
    fim_final = max(min(medido_fim, w.fim + 0.2), w.fim - 0.2)
    if fim_final - ini_final < 0.08:
        return w.inicio, w.fim
    return ini_final, fim_final


def trechos_do_bipe(palavras: Sequence[Palavra], x: np.ndarray, proibidas: Sequence[str]
                    ) -> list[tuple[float, float]]:
    """Os trechos que levam bipe: a sílaba escondida de cada palavra proibida (a mesma
    dos asteriscos), com as sílabas divididas pelo número de letras."""
    saida = []
    for w in palavras:
        if not censura.proibida(w.texto, proibidas):
            continue
        nucleo = "".join(c for c in w.texto if c.isalpha())
        partes = censura.silabas(nucleo)
        k = censura.silaba_escondida(len(partes))
        ini, fim = trecho_da_palavra(x, w)
        letras = max(1, sum(len(p) for p in partes))
        antes = sum(len(p) for p in partes[:k]) / letras
        depois = sum(len(p) for p in partes[: k + 1]) / letras
        a = ini + (fim - ini) * antes
        b = ini + (fim - ini) * depois
        if len(partes) == 1:
            a, b = ini + (fim - ini) * 0.3, fim
        a, b = max(ini, a - FOLGA_DO_BIPE_S), min(fim, b + FOLGA_DO_BIPE_S)
        if b - a < BIPE_MINIMO_S:
            meio = (a + b) / 2
            a, b = meio - BIPE_MINIMO_S / 2, meio + BIPE_MINIMO_S / 2
        saida.append((round(float(a), 3), round(float(b), 3)))
    return saida


def bipar(voz: np.ndarray, trechos: Sequence[tuple[float, float]]) -> np.ndarray:
    """O bipe por cima de cada trecho, com a voz zerada por baixo (``voz-bipe.py``)."""
    if not trechos:
        return voz
    voz = np.array(voz, dtype=np.float32, copy=True)
    canais = voz[:, None] if voz.ndim == 1 else voz
    rampa = max(1, int(RAMPA_S * TAXA))
    for a, b in trechos:
        i0, i1 = max(0, int(a * TAXA)), min(len(canais), int(b * TAXA))
        if i1 - i0 < 2 * rampa:
            continue
        vizinho = canais[max(0, i0 - int(0.3 * TAXA)):min(len(canais), i1 + int(0.3 * TAXA))]
        nivel = float(np.sqrt(np.mean(vizinho.astype(np.float64) ** 2)) + 1e-9)
        amplitude = min(0.6, nivel * np.sqrt(2) * 1.1)
        n = i1 - i0
        forma = np.ones(n, np.float32)
        subida = 0.5 - 0.5 * np.cos(np.pi * np.arange(rampa) / rampa)
        forma[:rampa] = subida
        forma[-rampa:] = subida[::-1]
        t = np.arange(i0, i1) / TAXA
        bipe = (amplitude * forma * np.sin(2 * np.pi * BIPE_HZ * t)).astype(np.float32)
        canais[i0:i1] *= (1 - forma)[:, None]
        canais[i0:i1] += bipe[:, None]
    return np.clip(canais if voz.ndim > 1 else canais[:, 0], -1, 1).astype(np.float32)


__all__ = [
    "NIVEIS",
    "Parte",
    "bipar",
    "expansor",
    "filtrar",
    "juntar",
    "limitar",
    "lufs",
    "nivelar",
    "palavras_nas_partes",
    "tirar_eco",
    "tirar_ruido",
    "tratar",
    "trecho_da_palavra",
    "trechos_do_bipe",
]
