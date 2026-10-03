"""Legendas em arquivo (.srt e .vtt), com os tempos do vídeo já editado."""
from __future__ import annotations

from pathlib import Path

from editor.plano import Plano


def _carimbo(segundos: float, *, virgula: bool) -> str:
    # Em milésimos inteiros, e só depois repartido: arredondar a fração separada
    # dava "00:00:06.1000", quatro dígitos num campo de três.
    ms = round(max(0.0, segundos) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if virgula else '.'}{ms:03d}"


def srt(plano: Plano) -> str:
    linhas = []
    for i, b in enumerate(plano.blocos, 1):
        linhas += [str(i), f"{_carimbo(b.inicio, virgula=True)} --> "
                           f"{_carimbo(b.fim, virgula=True)}", b.texto, ""]
    return "\n".join(linhas)


def vtt(plano: Plano) -> str:
    linhas = ["WEBVTT", ""]
    for b in plano.blocos:
        linhas += [f"{_carimbo(b.inicio, virgula=False)} --> {_carimbo(b.fim, virgula=False)}",
                   b.texto, ""]
    return "\n".join(linhas)


def gravar(plano: Plano, base: Path, *, com_srt: bool, com_vtt: bool) -> list[Path]:
    feitos = []
    if com_srt:
        feitos.append(base.with_suffix(".srt"))
        feitos[-1].write_text(srt(plano), encoding="utf-8")
    if com_vtt:
        feitos.append(base.with_suffix(".vtt"))
        feitos[-1].write_text(vtt(plano), encoding="utf-8")
    return feitos


__all__ = ["gravar", "srt", "vtt"]
