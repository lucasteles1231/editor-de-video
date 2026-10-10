"""
"Minha voz": a pessoa lê um texto uma vez, e o editor narra qualquer roteiro com a voz dela.

1. **A leitura** (``recursos/leitura-da-voz.txt``): a primeira frase é a autorização, com o
   nome; depois, parágrafos curtos que passam pelos sons do português (as nasais, o lh e o
   nh, os dois erres, s, z, x e ch), números, uma data, uma sigla, perguntas, exclamações e
   uma enumeração. Lida devagar, dá uns 2 minutos.
2. **A conferência:** cada parágrafo é transcrito pelo Whisper e comparado ao texto palavra
   a palavra, com os números por extenso dos dois lados (``transcricao.chaves``). O texto
   não vai de dica: com ele, o Whisper "ouviria" o texto mesmo com a leitura errada. Também
   são medidos o volume, o som estourado e o ruído de fundo. Os limites saíram das
   gravações reais do dono (09/10): a −31 a −36 LUFS, com a fala 26 a 30 dB acima do
   ruído, o clone saiu bom; por isso o volume só reprova abaixo de −45 LUFS.
3. **A referência:** o modelo não aprende com a gravação, ele a usa de exemplo. Medido em
   09/10, com 3 sementes e o ECAPA de juiz: de 8 para 26 s de referência, a semelhança
   com a voz real subiu 0,05 num texto novo; de 26 para 38 s, nada, e a geração ficou 6%
   mais lenta. Por isso a referência tem uns 25 s: os parágrafos mais limpos, com uma
   pergunta entre eles, nivelados a −20 LUFS (o modelo copia o volume da referência).
4. **A narração:** o roteiro vai ao motor (:mod:`editor.motor_de_voz`) em pedaços de
   frases inteiras, de até ~220 letras; os pedaços ficam guardados pela voz e pelo texto.
   Eles são juntados com 0,3 s entre as frases e 0,6 s entre os parágrafos, no volume dos
   Shorts. O roteiro vai junto num arquivo ao lado (``.roteiro.txt``): a legenda sai com a
   grafia dele, e não com a do Whisper.

A lista de pronúncia ("PEGI = pégui") muda só o que o motor lê: a legenda continua com a
grafia do roteiro.

Tudo fica no computador: a gravação, a voz e o modelo. E só existe este caminho: ler o
texto com a autorização. Não há "clonar de um áudio qualquer".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import unicodedata
import wave
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from importlib.resources import files
from pathlib import Path

import numpy as np

from editor import motor_de_voz, transcricao, voz
from editor import video as video_mod
from editor.transcricao import Palavra

TAXA = voz.TAXA
LEITURA = "leitura-da-voz.txt"
NOME_MAXIMO = 40

#: A conferência de cada parágrafo.
COBERTURA_MINIMA = 0.9
LUFS_MINIMO = -45.0
SNR_MINIMO_DB = 18.0
#: A fração de amostras no teto (o som estourado).
ESTOURO_MAXIMO = 0.001
#: O silêncio digital de um áudio de 16 bits: o ruído não é medido abaixo disto.
PISO_DB = -90.0
#: Menos que isto não é o parágrafo lido.
SEGUNDOS_MINIMOS = 1.5
#: O modelo do Whisper que confere a leitura.
MODELO_DA_CONFERENCIA = "small"

#: A referência: juntar parágrafos até passar do alvo, sem passar do teto.
REFERENCIA_ALVO_S = 22.0
REFERENCIA_TETO_S = 35.0
REFERENCIA_LUFS = -20.0

#: A narração.
PEDACO_MAXIMO = 220
ENTRE_FRASES_S = voz.PAUSA_S
ENTRE_PARAGRAFOS_S = 0.6
ROTEIRO_MAXIMO = 20_000


class VozInvalida(ValueError):
    """O nome, a gravação ou a voz pedida não servem (a mensagem diz por quê)."""


# ── o texto ──────────────────────────────────────────────────────────────


def nome_valido(nome: str) -> str:
    """O nome como vai na autorização: letras, espaços, hífen e apóstrofo."""
    limpo = re.sub(r"\s+", " ", str(nome or "")).strip()
    if not limpo:
        raise VozInvalida("Diga o seu nome: ele vai na frase de autorização.")
    if len(limpo) > NOME_MAXIMO:
        raise VozInvalida(f"O nome passa de {NOME_MAXIMO} letras.")
    if not re.fullmatch(r"[^\W\d_]+(?:[ '’-][^\W\d_]+)*", limpo):
        raise VozInvalida("O nome leva só letras, espaços, hífen e apóstrofo.")
    return limpo


def apelido(nome: str) -> str:
    """O nome da pasta da voz: "Lucas Teles" vira "lucas-teles"."""
    t = "".join(c for c in unicodedata.normalize("NFKD", nome.lower())
                if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "voz"


def texto_de_leitura(nome: str) -> list[str]:
    """Os parágrafos a ler, com o nome na autorização."""
    bruto = files("editor").joinpath("recursos", LEITURA).read_text(encoding="utf-8")
    paragrafos = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", bruto)]
    return [p.replace("{nome}", nome) for p in paragrafos if p]


def cobertura(esperado: str, ouvido: str) -> tuple[float, list[str]]:
    """Quanto do texto foi ouvido, na ordem, e as palavras que faltaram."""
    a, b = transcricao.chaves(esperado), transcricao.chaves(ouvido)
    if not a:
        return 1.0, []
    casadas = [False] * len(a)
    for i, _j, n in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for d in range(n):
            casadas[i + d] = True
    faltaram = [w for w, ok in zip(a, casadas, strict=True) if not ok]
    return sum(casadas) / len(a), faltaram


# ── as medidas ───────────────────────────────────────────────────────────


@dataclass
class Medidas:
    segundos: float
    lufs: float
    #: A fala (os 10% mais fortes) acima do ruído (os 10% mais fracos), em dB.
    snr_db: float
    estouro: float

    @classmethod
    def de(cls, x: np.ndarray) -> Medidas:
        passo = int(0.03 * TAXA)
        if len(x) < passo * 4:
            return cls(round(len(x) / TAXA, 2), -70.0, 0.0, 0.0)
        janelas = x[: len(x) // passo * passo].reshape(-1, passo).astype(np.float64)
        # o piso é o de um áudio de 16 bits: abaixo disso, é silêncio digital, não ruído
        db = np.maximum(20 * np.log10(np.sqrt((janelas ** 2).mean(axis=1)) + 1e-10), PISO_DB)
        snr = float(np.percentile(db, 90) - np.percentile(db, 10))
        return cls(round(len(x) / TAXA, 2), round(voz.lufs(x), 1), round(snr, 1),
                   round(float((np.abs(x) >= 0.999).mean()), 5))

    def problemas(self) -> list[str]:
        erros = []
        if self.segundos < SEGUNDOS_MINIMOS:
            erros.append("A gravação ficou curta demais: leia o parágrafo inteiro.")
        elif self.lufs < LUFS_MINIMO:
            erros.append("O som ficou baixo demais: aproxime o microfone (ou fale mais perto "
                         "do celular).")
        if self.estouro > ESTOURO_MAXIMO:
            erros.append("O som estourou: afaste um pouco o microfone ou baixe o volume dele.")
        if self.segundos >= SEGUNDOS_MINIMOS and self.snr_db < SNR_MINIMO_DB:
            erros.append("Tem muito ruído de fundo: procure um lugar mais silencioso (ventilador "
                         "e ar-condicionado desligados).")
        return erros


# ── a conferência ────────────────────────────────────────────────────────


@dataclass
class Paragrafo:
    indice: int
    texto: str
    #: "pendente", "ok" ou "refazer".
    estado: str = "pendente"
    motivos: list[str] = field(default_factory=list)
    cobertura: float = 0.0
    ouvido: str = ""
    faltaram: list[str] = field(default_factory=list)
    medidas: Medidas | None = None

    def para_dict(self) -> dict:
        d = asdict(self)
        d["cobertura"] = round(self.cobertura, 3)
        return d


def conferir_paragrafo(indice: int, texto: str, x: np.ndarray, ouvido: str) -> Paragrafo:
    """A nota de um parágrafo: a leitura (pelo que o Whisper ouviu) e o som."""
    medidas = Medidas.de(x)
    fracao, faltaram = cobertura(texto, ouvido)
    motivos = medidas.problemas()
    if medidas.segundos >= SEGUNDOS_MINIMOS and fracao < COBERTURA_MINIMA:
        motivos.append(f"Não ouvi o texto inteiro ({fracao:.0%} das palavras): leia de novo, "
                       "com calma, do jeito que está escrito.")
    if indice == 0 and "autorizo" not in transcricao.chaves(ouvido):
        motivos.append("A frase de autorização precisa ser lida como está, com o seu nome.")
    return Paragrafo(indice, texto, "refazer" if motivos else "ok", motivos, fracao, ouvido,
                     faltaram[:12], medidas)


def _transcritor_falso() -> bool:
    return os.environ.get(transcricao.VARIAVEL_FALSA, "").strip().lower() == "falso"


def ouvir(caminho: Path, esperado: str) -> list[Palavra]:
    """O que o Whisper ouviu, palavra por palavra. Com o transcritor falso (os testes), a
    leitura perfeita: o texto esperado, espalhado pela duração."""
    if _transcritor_falso():
        x = video_mod.ler_audio_mono(caminho, TAXA)
        palavras = esperado.split()
        passo = (len(x) / TAXA) / max(1, len(palavras))
        return [Palavra(w, round(k * passo, 3), round((k + 0.8) * passo, 3))
                for k, w in enumerate(palavras)]
    return transcricao.transcrever(caminho, idioma="pt", modelo=MODELO_DA_CONFERENCIA)


def _gravar(caminho: Path, x: np.ndarray, taxa: int = TAXA) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def dividir(x: np.ndarray, palavras: Sequence[Palavra], paragrafos: Sequence[str]
            ) -> list[tuple[np.ndarray, str]]:
    """A leitura inteira (um arquivo só) em parágrafos: cada palavra ouvida vai para o
    parágrafo do texto com que casou, e o corte cai no meio da pausa entre eles. Devolve,
    por parágrafo, o áudio e o que foi ouvido nele (vazio, se ele não foi achado)."""
    esperadas, de_qual = [], []
    for i, p in enumerate(paragrafos):
        for k in transcricao.chaves(p):
            esperadas.append(k)
            de_qual.append(i)
    ouvidas, de_quem = [], []
    for j, w in enumerate(palavras):
        for k in transcricao.chaves(w.texto):
            ouvidas.append(k)
            de_quem.append(j)
    dono: list[int | None] = [None] * len(palavras)
    for a, b, n in SequenceMatcher(None, esperadas, ouvidas, autojunk=False
                                   ).get_matching_blocks():
        for d in range(n):
            dono[de_quem[b + d]] = de_qual[a + d]
    # as que não casaram ficam com o parágrafo da anterior (ou da seguinte, no começo)
    ultimo = next((d for d in dono if d is not None), None)
    for j in range(len(dono)):
        if dono[j] is None:
            dono[j] = ultimo
        ultimo = dono[j]
    total = len(x) / TAXA
    limites: list[tuple[float, float] | None] = []
    for i in range(len(paragrafos)):
        js = [j for j, d in enumerate(dono) if d == i]
        limites.append((palavras[js[0]].inicio, palavras[js[-1]].fim) if js else None)
    saida = []
    for i, lim in enumerate(limites):
        if lim is None:
            saida.append((np.zeros(0, np.float32), ""))
            continue
        antes = next((limites[k] for k in range(i - 1, -1, -1) if limites[k]), None)
        depois = next((limites[k] for k in range(i + 1, len(limites)) if limites[k]), None)
        ini = (antes[1] + lim[0]) / 2 if antes else max(0.0, lim[0] - 0.3)
        fim = (lim[1] + depois[0]) / 2 if depois else min(total, lim[1] + 0.5)
        trecho, _ = voz.aparar(x[int(ini * TAXA): int(fim * TAXA)])
        ouvido = " ".join(w.texto for w, d in zip(palavras, dono, strict=True) if d == i)
        saida.append((trecho.astype(np.float32), ouvido))
    return saida


class Gravacao:
    """Uma leitura em andamento: os parágrafos chegam um a um (pelo microfone da página),
    ou todos num arquivo só, e cada um recebe a sua nota."""

    def __init__(self, nome: str, pasta: Path) -> None:
        self.nome = nome_valido(nome)
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.textos = texto_de_leitura(self.nome)
        self.paragrafos = [Paragrafo(i, t) for i, t in enumerate(self.textos)]

    def wav(self, i: int) -> Path:
        return self.pasta / f"p{i + 1:02d}.wav"

    def receber_paragrafo(self, i: int, arquivo: Path) -> Paragrafo:
        if not 0 <= i < len(self.textos):
            raise VozInvalida("Esse parágrafo não existe.")
        try:
            x = video_mod.ler_audio_mono(Path(arquivo), TAXA)
        except Exception as erro:
            raise VozInvalida("Não achei áudio nesta gravação.") from erro
        x, _ = voz.aparar(x)
        self._gravar_e_conferir(i, x, None)
        return self.paragrafos[i]

    def receber_leitura(self, arquivo: Path) -> list[Paragrafo]:
        """A leitura inteira num arquivo: ela é dividida em parágrafos pelo que foi ouvido."""
        try:
            x = video_mod.ler_audio_mono(Path(arquivo), TAXA)
        except Exception as erro:
            raise VozInvalida("Não achei áudio neste arquivo. Use MP3, WAV ou M4A.") from erro
        inteiro = self.pasta / "leitura.wav"
        _gravar(inteiro, x)
        palavras = ouvir(inteiro, " ".join(self.textos))
        for i, (trecho, ouvido) in enumerate(dividir(x, palavras, self.textos)):
            self._gravar_e_conferir(i, trecho, ouvido)
        return self.paragrafos

    def _gravar_e_conferir(self, i: int, x: np.ndarray, ouvido: str | None) -> None:
        _gravar(self.wav(i), x)
        if ouvido is None:
            ouvido = " ".join(w.texto for w in ouvir(self.wav(i), self.textos[i])) if len(x) else ""
        p = conferir_paragrafo(i, self.textos[i], x, ouvido)
        if not len(x):
            p.motivos = ["Não achei este parágrafo na gravação: grave só ele."]
            p.estado = "refazer"
        self.paragrafos[i] = p

    def pronta(self) -> bool:
        return all(p.estado == "ok" for p in self.paragrafos)

    def para_dict(self) -> dict:
        return {"nome": self.nome, "pronta": self.pronta(),
                "paragrafos": [p.para_dict() for p in self.paragrafos]}


# ── as vozes salvas ──────────────────────────────────────────────────────


def pasta_das_vozes() -> Path:
    from editor.ia import pasta_de_dados

    return pasta_de_dados() / "vozes"


def escolher_referencia(paragrafos: Sequence[Paragrafo]) -> list[int]:
    """Os parágrafos da referência, na ordem da leitura: os de melhor nota até passar do
    alvo (sem passar do teto), com pelo menos uma pergunta entre eles. A autorização fica
    de fora: é a frase menos natural da leitura."""
    candidatos = [p for p in paragrafos if p.indice > 0 and p.estado == "ok" and p.medidas]
    nota = {p.indice: p.cobertura * 100 + min(p.medidas.snr_db, 40.0) for p in candidatos}
    candidatos.sort(key=lambda p: -nota[p.indice])
    escolhidos: list[Paragrafo] = []
    total = 0.0
    for p in candidatos:
        if total >= REFERENCIA_ALVO_S:
            break
        if total + p.medidas.segundos <= REFERENCIA_TETO_S or not escolhidos:
            escolhidos.append(p)
            total += p.medidas.segundos
    pergunta = [p for p in candidatos if "?" in p.texto]
    if pergunta and not any("?" in p.texto for p in escolhidos):
        if escolhidos:
            escolhidos.pop()                     # sai o de nota mais baixa
        escolhidos.append(pergunta[0])
    return sorted(p.indice for p in escolhidos)


def salvar(g: Gravacao) -> dict:
    """A voz da gravação aprovada, na pasta das vozes (o mesmo nome substitui a anterior)."""
    if not g.pronta():
        faltam = [p.indice + 1 for p in g.paragrafos if p.estado != "ok"]
        raise VozInvalida(f"Ainda falta regravar: parágrafo {', '.join(map(str, faltam))}.")
    escolhidos = escolher_referencia(g.paragrafos)
    if not escolhidos:
        raise VozInvalida("Nenhum parágrafo serve de referência.")
    slug = apelido(g.nome)
    final = pasta_das_vozes() / slug
    nova = pasta_das_vozes() / f".{slug}-nova"
    shutil.rmtree(nova, ignore_errors=True)
    (nova / "leitura").mkdir(parents=True)
    for i in range(len(g.textos)):
        shutil.copy2(g.wav(i), nova / "leitura" / g.wav(i).name)
    partes = [video_mod.ler_audio_mono(g.wav(i), TAXA) for i in escolhidos]
    junta, _ = voz.juntar(partes)
    junta = voz.limitar(voz.nivelar(junta, REFERENCIA_LUFS))
    _gravar(nova / "referencia.wav", junta)
    dados = {
        "nome": g.nome, "apelido": slug, "criada": time.strftime("%Y-%m-%d %H:%M"),
        "modelo": motor_de_voz.MODELO,
        "referencia": {"texto": " ".join(g.textos[i] for i in escolhidos),
                       "paragrafos": [i + 1 for i in escolhidos],
                       "segundos": round(len(junta) / TAXA, 1)},
        "autorizacao": {"texto": g.textos[0], "ouvido": g.paragrafos[0].ouvido,
                        "cobertura": round(g.paragrafos[0].cobertura, 3)},
        "medidas": [asdict(p.medidas) if p.medidas else None for p in g.paragrafos],
        "pronuncia": (ler_voz(slug).get("pronuncia", {}) if (final / "voz.json").is_file()
                      else {}),
    }
    (nova / "voz.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    nova.rename(final)
    return resumo(dados)


def resumo(dados: dict) -> dict:
    """O que a página mostra de uma voz."""
    return {"nome": dados["nome"], "apelido": dados["apelido"], "criada": dados["criada"],
            "segundos": dados["referencia"]["segundos"],
            "pronuncia": dados.get("pronuncia", {})}


def vozes() -> list[dict]:
    pasta = pasta_das_vozes()
    if not pasta.is_dir():
        return []
    saida = []
    for d in sorted(pasta.iterdir()):
        if d.name.startswith(".") or not (d / "voz.json").is_file():
            continue
        try:
            saida.append(resumo(json.loads((d / "voz.json").read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError):
            continue
    return saida


def _pasta_da_voz(slug: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,60}", slug or ""):
        raise VozInvalida("Voz desconhecida.")
    pasta = pasta_das_vozes() / slug
    if not (pasta / "voz.json").is_file():
        raise VozInvalida("Essa voz não existe (ou foi apagada).")
    return pasta


def ler_voz(slug: str) -> dict:
    return json.loads((_pasta_da_voz(slug) / "voz.json").read_text(encoding="utf-8"))


def referencia(slug: str) -> Path:
    return _pasta_da_voz(slug) / "referencia.wav"


def apagar(slug: str) -> None:
    shutil.rmtree(_pasta_da_voz(slug))


def ler_pronuncia(texto: str) -> dict[str, str]:
    """ "PEGI = pégui", uma por linha (também com "→" ou ":")."""
    lista = {}
    for linha in str(texto or "").splitlines():
        partes = re.split(r"\s*(?:=|→|->|:)\s*", linha.strip(), maxsplit=1)
        if len(partes) == 2 and partes[0] and partes[1]:
            lista[partes[0][:60]] = partes[1][:120]
    return dict(list(lista.items())[:200])


def salvar_pronuncia(slug: str, pronuncia: dict[str, str]) -> dict:
    pasta = _pasta_da_voz(slug)
    dados = ler_voz(slug)
    dados["pronuncia"] = dict(pronuncia)
    (pasta / "voz.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return resumo(dados)


# ── a narração ───────────────────────────────────────────────────────────


def pedacos(roteiro: str) -> list[list[str]]:
    """O roteiro em parágrafos, e cada parágrafo em pedaços de frases inteiras até
    ``PEDACO_MAXIMO`` letras (uma frase mais longa que isso é partida nas vírgulas)."""
    saida = []
    for paragrafo in re.split(r"\n\s*\n", str(roteiro or "").strip()):
        texto = re.sub(r"\s+", " ", paragrafo).strip()
        if not texto:
            continue
        frases = [f for f in re.split(r"(?<=[.!?…])\s+", texto) if f]
        curtas = []
        for f in frases:
            while len(f) > PEDACO_MAXIMO:
                corte = f.rfind(", ", 0, PEDACO_MAXIMO)
                corte = corte + 1 if corte > PEDACO_MAXIMO // 3 else f.rfind(" ", 0, PEDACO_MAXIMO)
                if corte <= 0:
                    break
                curtas.append(f[:corte].strip())
                f = f[corte:].strip()
            curtas.append(f)
        grupos: list[str] = []
        for f in curtas:
            if grupos and len(grupos[-1]) + 1 + len(f) <= PEDACO_MAXIMO:
                grupos[-1] += f" {f}"
            else:
                grupos.append(f)
        saida.append(grupos)
    return saida


def aplicar_pronuncia(texto: str, pronuncia: dict[str, str]) -> str:
    """Troca cada palavra da lista (inteira, sem diferença de maiúsculas) pela pronúncia."""
    for de in sorted(pronuncia, key=len, reverse=True):
        texto = re.sub(rf"(?<!\w){re.escape(de)}(?!\w)", lambda _m, de=de: pronuncia[de],
                       texto, flags=re.IGNORECASE)
    return texto


def pasta_das_narracoes() -> Path:
    from platformdirs import user_cache_dir

    pasta = Path(user_cache_dir("editor-de-video", appauthor=False)) / "narracoes"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


@dataclass
class Narracao:
    caminho: Path
    segundos: float
    pedacos: int
    reaproveitados: int
    aparelho: str


def narrar(slug: str, roteiro: str, destino: Path, *, pronuncia: dict[str, str] | None = None,
           progresso: Callable[[int, int], None] | None = None,
           parar: Callable[[], bool] | None = None) -> Narracao:
    """O roteiro narrado com a voz salva, em ``destino`` (WAV), com o roteiro ao lado."""
    roteiro = str(roteiro or "").strip()
    if not roteiro:
        raise VozInvalida("O roteiro está vazio.")
    if len(roteiro) > ROTEIRO_MAXIMO:
        raise VozInvalida(f"O roteiro passa de {ROTEIRO_MAXIMO} letras: divida em vídeos menores.")
    dados = ler_voz(slug)
    lista = dados.get("pronuncia", {}) if pronuncia is None else pronuncia
    blocos = pedacos(roteiro)
    identidade = f"{slug}|{dados['criada']}|{dados['modelo']}"
    cache = pasta_das_narracoes()
    planos: list[list[Path]] = []
    faltam: list[tuple[str, Path]] = []
    for bloco in blocos:
        caminhos = []
        for pedaco in bloco:
            lido = aplicar_pronuncia(pedaco, lista)
            chave = hashlib.sha1(f"{identidade}|{lido}".encode()).hexdigest()[:20]
            arquivo = cache / f"{chave}.wav"
            if not arquivo.is_file() and all(arquivo != s for _t, s in faltam):
                faltam.append((lido, arquivo))
            caminhos.append(arquivo)
        planos.append(caminhos)
    total = sum(len(c) for c in planos)
    if progresso:
        progresso(total - len(faltam), total)       # o modelo leva uns 7 s para carregar
    aparelho = "guardado"
    if faltam:
        temporarios = [(t, s.with_suffix(".parcial.wav")) for t, s in faltam]
        feitas_antes = total - len(faltam)

        def andou(feitas: int, _n: int) -> None:
            if progresso:
                progresso(feitas_antes + feitas, total)

        aparelho = motor_de_voz.sintetizar(referencia(slug), dados["referencia"]["texto"],
                                           temporarios, progresso=andou, parar=parar)
        for (_t, parcial), (_t2, final) in zip(temporarios, faltam, strict=True):
            parcial.replace(final)
    partes: list[np.ndarray] = []
    for k, caminhos in enumerate(planos):
        if k:
            partes.append(np.zeros(int(ENTRE_PARAGRAFOS_S * TAXA), np.float32))
        for m, c in enumerate(caminhos):
            if m:
                partes.append(np.zeros(int(ENTRE_FRASES_S * TAXA), np.float32))
            x, _ = voz.aparar(video_mod.ler_audio_mono(c, TAXA))
            partes.append(x)
    audio = voz.limitar(voz.nivelar(np.concatenate(partes), voz.FINAL_LUFS))
    destino = Path(destino)
    _gravar(destino, audio)
    destino.with_suffix(".roteiro.txt").write_text(roteiro, encoding="utf-8")
    return Narracao(destino, round(len(audio) / TAXA, 2), total, total - len(faltam), aparelho)


__all__ = [
    "COBERTURA_MINIMA",
    "LUFS_MINIMO",
    "SNR_MINIMO_DB",
    "Gravacao",
    "Medidas",
    "Narracao",
    "Paragrafo",
    "VozInvalida",
    "apagar",
    "apelido",
    "aplicar_pronuncia",
    "cobertura",
    "conferir_paragrafo",
    "dividir",
    "escolher_referencia",
    "ler_pronuncia",
    "ler_voz",
    "narrar",
    "nome_valido",
    "ouvir",
    "pasta_das_vozes",
    "pedacos",
    "referencia",
    "resumo",
    "salvar",
    "salvar_pronuncia",
    "texto_de_leitura",
    "vozes",
]
