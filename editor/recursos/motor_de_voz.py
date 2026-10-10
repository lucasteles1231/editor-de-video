"""
O motor da voz sintetizada. Roda no ambiente do motor (``<dados>/motor-de-voz/.venv``), e
não no do editor: só precisa do qwen-tts (que traz o PyTorch) e do numpy.

    python -I motor_de_voz.py --baixar REPO PASTA     o modelo do Hugging Face na PASTA
    python -I motor_de_voz.py --conferir PASTA        carrega o modelo e diz a placa
    python -I motor_de_voz.py PEDIDO.json             gera as frases do pedido

Cada linha do stdout é um JSON: ``{"aparelho": "mps"}`` quando o modelo carrega, e
``{"feitas": 3, "total": 9}`` a cada frase pronta. Os erros vão para o stderr.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import wave
from pathlib import Path


def avisar(**dados) -> None:
    # Só ASCII: com o -I, o PYTHONIOENCODING é ignorado, e o stdout do Windows é cp1252.
    print(json.dumps(dados), flush=True)


def aparelho() -> str:
    """A placa do Mac, depois a NVIDIA, depois o processador. ``EDITOR_VOZ_APARELHO=cpu``
    força o processador (quando a placa dá problema, ou para medir)."""
    import torch

    forcado = os.environ.get("EDITOR_VOZ_APARELHO", "").strip()
    if forcado:
        return forcado
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda:0"
    return "cpu"


def carregar(pasta: str, onde: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    # bf16 na placa (o que foi medido); no processador, float32, que ele faz direito
    tipo = torch.float32 if onde == "cpu" else torch.bfloat16
    return Qwen3TTSModel.from_pretrained(pasta, device_map=onde, dtype=tipo,
                                         attn_implementation="sdpa")


def gravar(caminho: str, amostras, taxa: int) -> None:
    import numpy as np

    x = np.clip(np.asarray(amostras, dtype=np.float32).reshape(-1), -1.0, 1.0)
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(taxa))
        w.writeframes((x * 32767).astype("<i2").tobytes())


def baixar(repo: str, destino: str) -> None:
    """O modelo na pasta do motor. Se ele já está no cache do Hugging Face (de um teste
    anterior), é copiado de lá, sem baixar de novo."""
    from huggingface_hub import snapshot_download

    alvo = Path(destino)
    try:
        no_cache = Path(snapshot_download(repo, local_files_only=True))
    except Exception:
        no_cache = None
    if no_cache is not None:
        if alvo.exists():
            shutil.rmtree(alvo)
        shutil.copytree(no_cache, alvo)              # segue os links do cache
        avisar(modelo=str(alvo), copiado=True)
        return
    snapshot_download(repo, local_dir=str(alvo))
    avisar(modelo=str(alvo), copiado=False)


def conferir(pasta: str) -> None:
    from importlib.metadata import version

    import torch

    onde = aparelho()
    carregar(pasta, onde)
    avisar(aparelho=onde, torch=torch.__version__, qwen_tts=version("qwen-tts"))


def gerar(arquivo: str) -> None:
    pedido = json.loads(Path(arquivo).read_text(encoding="utf-8"))
    onde = aparelho()
    modelo = carregar(pedido["modelo"], onde)
    avisar(aparelho=onde)
    ref = pedido["referencia"]
    prompt = modelo.create_voice_clone_prompt(ref_audio=ref["wav"], ref_text=ref["texto"],
                                              x_vector_only_mode=False)
    frases = pedido["frases"]
    for k, frase in enumerate(frases):
        wavs, taxa = modelo.generate_voice_clone(text=frase["texto"],
                                                 language=pedido.get("idioma", "Portuguese"),
                                                 voice_clone_prompt=prompt)
        gravar(frase["saida"], wavs[0], taxa)
        avisar(feitas=k + 1, total=len(frases))


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--baixar":
        baixar(argv[1], argv[2])
    elif len(argv) == 2 and argv[0] == "--conferir":
        conferir(argv[1])
    elif len(argv) == 1:
        gerar(argv[0])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
