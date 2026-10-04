"""
O bloqueio do Windows 11 às bibliotecas do editor.

O Controle Inteligente de Aplicativos (Smart App Control) barra os arquivos nativos sem
assinatura que a Microsoft ainda não conhece. O PyAV, que lê e grava o vídeo, cai nele, e
o editor nem abre. O erro do Python ("DLL load failed while importing logging: Uma
política de Controle de Aplicativo bloqueou este arquivo") não diz o que fazer, e ainda
parece o da falta do Visual C++, que tem outra solução. Aqui ele vira uma explicação.

Visto num Windows 11 em 04/10/2026: o NumPy e o Pillow passaram (são muito usados), e o
PyAV foi barrado.
"""
from __future__ import annotations

import sys

#: ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION, o código do Windows para esse bloqueio.
CODIGO = 4551
#: A mensagem do Windows em inglês e em português. A deste Windows, em qualquer idioma,
#: vem de :func:`_mensagem_do_sistema`.
MENSAGENS = ("Application Control policy has blocked this file",
             "política de Controle de Aplicativo bloqueou este arquivo")

EXPLICACAO = """\
O Windows bloqueou uma biblioteca do editor, e sem ela ele não funciona.

Quem bloqueia é o Controle Inteligente de Aplicativos (Smart App Control) do Windows 11.
Ele barra arquivos sem assinatura que a Microsoft ainda não conhece, como os do PyAV, a
biblioteca que lê e grava o vídeo. Instalar o Visual C++ ou liberar no antivírus não
resolve.

Para usar o editor, desligue o Controle Inteligente de Aplicativos:

  Segurança do Windows > Controle de aplicativos e do navegador >
  Configurações do Controle Inteligente de Aplicativos > Desligado

Num Windows 11 atualizado (da atualização de abril de 2026 em diante), dá para ligar de
novo depois. Antes dela, desligar só volta reinstalando o Windows.

Num computador de empresa, o bloqueio pode vir da TI: fale com ela.

O erro do Windows: {erro}"""


def _mensagem_do_sistema() -> str:
    """A mensagem do bloqueio no idioma deste Windows; fora dele, ""."""
    if sys.platform != "win32":
        return ""
    import ctypes

    return ctypes.FormatError(CODIGO).strip().rstrip(".")


def bloqueado(erro: BaseException) -> bool:
    """Se o erro é o do Controle Inteligente de Aplicativos."""
    if getattr(erro, "winerror", None) == CODIGO:
        return True
    texto = str(erro)
    deste_windows = _mensagem_do_sistema()
    return any(m in texto for m in MENSAGENS) or bool(deste_windows and deste_windows in texto)


def explicar(erro: BaseException) -> str:
    return EXPLICACAO.format(erro=erro)


def _carregar() -> None:
    import av  # noqa: F401


def conferir() -> str:
    """A explicação, se o Windows bloqueou o PyAV; "" se ele carrega. Outro erro de
    importação sobe como veio."""
    try:
        _carregar()
    except ImportError as erro:
        if bloqueado(erro):
            return explicar(erro)
        raise
    return ""


__all__ = ["CODIGO", "bloqueado", "conferir", "explicar"]
