"""
O motor da voz sintetizada (Qwen3-TTS 0.6B Base, Apache 2.0), num ambiente só dele.

**Por que à parte.** O motor precisa do PyTorch (~1,2 GB) e do modelo (2,3 GB). Assim o
editor continua pequeno para quem não usa a voz, o PyTorch não briga com as versões do
editor, e desinstalar é apagar uma pasta (``<dados>/motor-de-voz``, com o modelo dentro).

**A instalação** (o botão da página, ou ``editar --instalar-voz``):

1. o ``uv`` cria o ambiente com o Python 3.12 (ele baixa o Python, se faltar);
2. instala o ``qwen-tts`` na versão testada, e o ``--torch-backend auto`` do uv escolhe o
   PyTorch com CUDA quando há placa NVIDIA (sem o uv, valem o ``venv`` e o ``pip`` do
   Python do editor);
3. o modelo vem do Hugging Face para dentro da pasta (copiado do cache, se já estiver lá);
4. o motor carrega o modelo uma vez, para conferir, e diz qual placa vai usar.

**A conversa:** o editor escreve um pedido em JSON (a referência, o texto dela e as
frases, cada uma com o WAV de saída) e roda ``recursos/motor_de_voz.py`` com o Python do
ambiente; o script responde uma linha JSON por frase pronta. Um processo por narração: o
modelo carrega em ~7 s, e entre um vídeo e outro a memória volta toda.

**A placa:** a do Mac (MPS), depois a NVIDIA (CUDA), depois o processador. Medido no M5
(09/10): na placa, gerar leva de 1,4 a 1,6 vez a duração do áudio.

Para testes há o motor falso (``EDITOR_VOZ=falsa``): sem subprocesso, cada frase vira um
tom da duração que a fala teria.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

#: O modelo e a versão do pacote que foram medidos (prova de conceito de 09/10).
MODELO = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
PACOTE = "qwen-tts==0.1.1"
PYTHON = "3.12"
#: O que a página mostra antes de instalar.
ESPACO = "uns 3,5 GB (até 6 GB com placa NVIDIA)"
TEMPO = "de 5 a 20 minutos, conforme a internet"

#: A variável que liga o motor falso (só testes).
VARIAVEL_FALSA = "EDITOR_VOZ"
#: A taxa do motor falso (a do modelo é 24 kHz).
TAXA_FALSA = 24_000
#: Quanto dura cada letra no motor falso (~14 letras por segundo, a fala de um vídeo).
SEGUNDOS_POR_LETRA = 0.07

Progresso = Callable[[int, int], None]

ETAPAS = {"ambiente": ("Criando o ambiente", 0.0, 0.05),
          "pacotes": ("Instalando o PyTorch e o Qwen3-TTS", 0.05, 0.5),
          "modelo": ("Baixando o modelo (2,3 GB)", 0.5, 0.92),
          "teste": ("Testando o motor", 0.92, 1.0)}


class ErroDoMotor(RuntimeError):
    """A instalação ou a síntese falharam (a mensagem já diz o que fazer)."""


def falso() -> bool:
    return os.environ.get(VARIAVEL_FALSA, "").strip().lower() == "falsa"


def pasta() -> Path:
    from editor.ia import pasta_de_dados

    return pasta_de_dados() / "motor-de-voz"


def pasta_do_modelo() -> Path:
    return pasta() / "modelo"


def python_do_motor() -> Path:
    venv = pasta() / ".venv"
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def script() -> Path:
    return Path(str(files("editor").joinpath("recursos", "motor_de_voz.py")))


def _marca() -> Path:
    return pasta() / "instalado.json"


def info() -> dict:
    """O que a instalação registrou: as versões e a placa."""
    if falso():
        return {"aparelho": "falso", "torch": "", "qwen_tts": ""}
    try:
        return json.loads(_marca().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def instalado() -> bool:
    return falso() or (_marca().is_file() and python_do_motor().is_file())


# ── a instalação ─────────────────────────────────────────────────────────


@dataclass
class Instalacao:
    rodando: bool = False
    etapa: str = ""
    fracao: float = 0.0
    erro: str = ""
    linhas: deque = field(default_factory=lambda: deque(maxlen=12))
    parar: threading.Event = field(default_factory=threading.Event)


_instalacao = Instalacao()
_trava = threading.Lock()


def estado() -> dict:
    i = _instalacao
    return {"instalado": instalado(), "falso": falso(), "instalando": i.rodando,
            "etapa": ETAPAS.get(i.etapa, (i.etapa,))[0] if i.etapa else "",
            "fracao": round(i.fracao, 3), "ultima": i.linhas[-1] if i.linhas else "",
            "erro": i.erro, "espaco": ESPACO, "tempo": TEMPO,
            "aparelho": info().get("aparelho", ""), "pasta": str(pasta())}


def achar_uv() -> str | None:
    """O ``uv`` do PATH, ou o do lugar onde o instalador dele põe."""
    achado = shutil.which("uv")
    if achado:
        return achado
    nome = "uv.exe" if sys.platform == "win32" else "uv"
    for lugar in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        if (lugar / nome).is_file():
            return str(lugar / nome)
    return None


def _uv_escolhe_o_torch(uv: str) -> bool:
    """Se este uv tem o ``--torch-backend`` (o 0.6.9 em diante)."""
    try:
        ajuda = subprocess.run([uv, "pip", "install", "--help"], capture_output=True,
                               text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "--torch-backend" in ajuda


def comandos() -> list[tuple[str, list[str]]]:
    """Os passos da instalação, na ordem: (etapa, comando)."""
    venv, py, s = pasta() / ".venv", str(python_do_motor()), str(script())
    uv = achar_uv()
    if uv:
        pacotes = [uv, "pip", "install", "--python", py]
        if _uv_escolhe_o_torch(uv):
            pacotes += ["--torch-backend", "auto"]
        passos = [("ambiente", [uv, "venv", "--python", PYTHON, "--allow-existing", str(venv)]),
                  ("pacotes", [*pacotes, PACOTE])]
    else:
        passos = [("ambiente", [sys.executable, "-m", "venv", str(venv)]),
                  ("pacotes", [py, "-m", "pip", "install", PACOTE])]
    return [*passos, ("modelo", [py, "-I", s, "--baixar", MODELO, str(pasta_do_modelo())]),
            ("teste", [py, "-I", s, "--conferir", str(pasta_do_modelo())])]


def _ambiente() -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTORCH_ENABLE_MPS_FALLBACK": "1",
           "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "HF_HUB_VERBOSITY": "error"}
    # o ambiente do editor não pode vazar para o do motor
    for nome in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(nome, None)
    return env


def _rodar(comando: list[str], ao_ler: Callable[[str], None], parar: threading.Event) -> int:
    """Roda um comando, passando cada linha da saída (stdout e stderr juntos)."""
    proc = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=_ambiente(), cwd=str(pasta()))
    assert proc.stdout is not None
    for bruta in iter(proc.stdout.readline, b""):
        for linha in bruta.decode("utf-8", "replace").replace("\r", "\n").split("\n"):
            if linha.strip():
                ao_ler(linha.strip())
        if parar.is_set():
            proc.terminate()
            break
    return proc.wait()


def _comecar() -> None:
    i = _instalacao
    with _trava:
        if i.rodando:
            raise ErroDoMotor("A instalação já está rodando.")
        i.rodando, i.erro, i.etapa, i.fracao = True, "", "", 0.0
        i.linhas.clear()
        i.parar.clear()


def instalar(progresso: Callable[[str, float, str], None] | None = None) -> dict:
    """Instala o motor (bloqueia até o fim). Devolve o que foi registrado."""
    _comecar()
    return _executar(progresso)


def _executar(progresso: Callable[[str, float, str], None] | None) -> dict:
    i = _instalacao
    try:
        if falso():
            for etapa, (_nome, _a, b) in ETAPAS.items():
                i.etapa, i.fracao = etapa, b
            return info()
        pasta().mkdir(parents=True, exist_ok=True)
        resposta: dict = {}

        def leu(linha: str) -> None:
            i.linhas.append(linha[:300])
            if linha.startswith("{"):
                with contextlib.suppress(ValueError):
                    resposta.update(json.loads(linha))
            if progresso:
                progresso(ETAPAS[i.etapa][0], i.fracao, linha[:200])

        for etapa, comando in comandos():
            nome, a, b = ETAPAS[etapa]
            i.etapa, i.fracao = etapa, a
            if progresso:
                progresso(nome, a, "")
            codigo = _rodar(comando, leu, i.parar)
            if i.parar.is_set():
                raise ErroDoMotor("A instalação foi cancelada.")
            if codigo != 0:
                ultimas = " | ".join(list(i.linhas)[-3:])
                raise ErroDoMotor(f"{nome} falhou (código {codigo}): {ultimas}")
            i.fracao = b
        registro = {"modelo": MODELO, "pacote": PACOTE, "quando": time.strftime("%Y-%m-%d"),
                    "aparelho": resposta.get("aparelho", ""), "torch": resposta.get("torch", ""),
                    "qwen_tts": resposta.get("qwen_tts", "")}
        _marca().write_text(json.dumps(registro, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        return registro
    except ErroDoMotor as erro:
        i.erro = str(erro)
        raise
    except Exception as erro:
        i.erro = f"A instalação falhou: {type(erro).__name__}: {erro}"
        raise ErroDoMotor(i.erro) from erro
    finally:
        i.rodando = False


def instalar_em_segundo_plano() -> dict:
    """Começa a instalação numa thread; o andamento sai em :func:`estado`."""
    _comecar()

    def rodar() -> None:
        try:
            _executar(None)
        except ErroDoMotor:
            logger.exception("a voz sintetizada não instalou")

    threading.Thread(target=rodar, daemon=True, name="instalar-a-voz").start()
    return estado()


def cancelar_instalacao() -> None:
    _instalacao.parar.set()


def desinstalar() -> None:
    if _instalacao.rodando:
        raise ErroDoMotor("Espere a instalação terminar (ou cancele) para desinstalar.")
    shutil.rmtree(pasta(), ignore_errors=True)


# ── a síntese ────────────────────────────────────────────────────────────


def _tom(texto: str, saida: Path) -> None:
    """O motor falso: um tom de 220 Hz da duração que a fala teria."""
    n = max(1, round(len(texto) * SEGUNDOS_POR_LETRA * TAXA_FALSA))
    t = np.arange(n) / TAXA_FALSA
    x = 0.3 * np.sin(2 * np.pi * 220 * t) * np.minimum(1, np.minimum(t, t[-1] - t) / 0.02)
    with wave.open(str(saida), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA_FALSA)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def sintetizar(referencia: Path, texto_da_referencia: str, frases: list[tuple[str, Path]], *,
               progresso: Progresso | None = None,
               parar: Callable[[], bool] | None = None) -> str:
    """Gera cada frase com a voz da referência, no WAV indicado. Devolve a placa usada."""
    if falso():
        for k, (texto, saida) in enumerate(frases):
            _tom(texto, saida)
            if progresso:
                progresso(k + 1, len(frases))
        return "falso"
    if not instalado():
        raise ErroDoMotor("A voz sintetizada não está instalada: instale pelo botão da página "
                          "ou com editar --instalar-voz.")
    pedido = {"modelo": str(pasta_do_modelo()), "idioma": "Portuguese",
              "referencia": {"wav": str(referencia), "texto": texto_da_referencia},
              "frases": [{"texto": t, "saida": str(s)} for t, s in frases]}
    with tempfile.TemporaryDirectory(prefix="pedido-") as tmp:
        arquivo = Path(tmp) / f"{uuid.uuid4().hex[:8]}.json"
        arquivo.write_text(json.dumps(pedido, ensure_ascii=False), encoding="utf-8")
        erros = Path(tmp) / "erros.txt"
        env = {**_ambiente(), "HF_HUB_OFFLINE": "1"}
        with erros.open("wb") as saida_de_erro:
            proc = subprocess.Popen([str(python_do_motor()), "-I", str(script()), str(arquivo)],
                                    stdout=subprocess.PIPE, stderr=saida_de_erro, env=env)
            assert proc.stdout is not None
            aparelho = ""
            for bruta in iter(proc.stdout.readline, b""):
                try:
                    msg = json.loads(bruta.decode("utf-8", "replace"))
                except ValueError:
                    continue
                aparelho = msg.get("aparelho", aparelho)
                if "feitas" in msg and progresso:
                    progresso(int(msg["feitas"]), len(frases))
                if parar and parar():
                    proc.terminate()
                    proc.wait()
                    raise ErroDoMotor("A narração foi cancelada.")
            codigo = proc.wait()
        if codigo != 0:
            final = erros.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            raise ErroDoMotor(f"O motor da voz falhou (código {codigo}): "
                              f"{' | '.join(final[-3:]) or 'sem mensagem'}")
    faltando = [str(s) for _t, s in frases if not Path(s).is_file()]
    if faltando:
        raise ErroDoMotor(f"O motor não gerou {len(faltando)} frase(s).")
    return aparelho


__all__ = ["ESPACO", "ETAPAS", "MODELO", "PACOTE", "TEMPO", "VARIAVEL_FALSA", "ErroDoMotor",
           "achar_uv", "cancelar_instalacao", "comandos", "desinstalar", "estado", "falso",
           "info", "instalado", "instalar", "instalar_em_segundo_plano", "pasta",
           "pasta_do_modelo", "python_do_motor", "script", "sintetizar"]
