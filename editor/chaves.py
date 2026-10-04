"""
As chaves das APIs opcionais (Gemini e Pexels), guardadas num arquivo que só o usuário lê.

**A chave entra pela página e nunca volta para ela.** O estado só diz se há chave, de onde
ela vem e o fim dela ("…abcd"); quem usa a chave é o servidor.

**A variável de ambiente ganha do arquivo:** quem a definiu sabe o que está fazendo.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def pasta_de_config() -> Path:
    from platformdirs import user_config_dir

    return Path(user_config_dir("editor-de-video", appauthor=False))


def _arquivo() -> Path:
    return pasta_de_config() / "config.json"


def _ler_tudo() -> dict:
    try:
        dados = json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_tudo(dados: dict) -> None:
    arquivo = _arquivo()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if not dados:
        arquivo.unlink(missing_ok=True)
        return
    texto = json.dumps(dados, ensure_ascii=False, indent=1)
    # Criado já com 0600: escrever e só depois restringir deixaria um instante em que
    # qualquer um lê. No Windows o modo é ignorado; a pasta do perfil já é só do usuário.
    descritor = os.open(arquivo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descritor, "w", encoding="utf-8") as f:
        f.write(texto)
    if os.name == "posix":
        os.chmod(arquivo, 0o600)


def ler(nome: str, variavel: str) -> tuple[str, str]:
    """A chave e de onde ela veio: ``"variavel"``, ``"arquivo"`` ou ``""`` (nenhuma)."""
    valor = os.environ.get(variavel, "").strip()
    if valor:
        return valor, "variavel"
    valor = str(_ler_tudo().get(nome) or "").strip()
    return (valor, "arquivo") if valor else ("", "")


def salvar(nome: str, valor: str) -> None:
    dados = _ler_tudo()
    dados[nome] = valor.strip()
    _gravar_tudo(dados)


def apagar(nome: str) -> None:
    dados = _ler_tudo()
    if dados.pop(nome, None) is not None:
        _gravar_tudo(dados)


def mascarada(valor: str) -> str:
    """Só o fim da chave, para a pessoa reconhecer qual é."""
    return f"…{valor[-4:]}" if len(valor) >= 8 else "…"


def limpar(valor: str) -> str:
    """A chave como colada, sem o que vem junto por engano: espaços, aspas e um
    ``ALGUMA_API_KEY=`` copiado do arquivo de outro projeto."""
    valor = (valor or "").strip().strip("\"'").strip()
    nome, igual, resto = valor.partition("=")
    if igual and re.fullmatch(r"[A-Za-z_]*KEY", nome.strip(), re.IGNORECASE):
        valor = resto.strip().strip("\"'").strip()
    return valor


def parece_chave(valor: str) -> bool:
    """Só por alto: uma sequência longa sem espaço. Quem decide é o dono da API — a
    primeira versão exigia letras, números, "_" e "-", e recusou uma chave de verdade
    do Gemini, que tinha ponto."""
    return bool(re.fullmatch(r"[\x21-\x7e]{20,300}", valor))


def estado(nome: str, variavel: str) -> dict:
    valor, origem = ler(nome, variavel)
    return {"configurada": bool(valor), "origem": origem,
            "final": mascarada(valor) if valor else ""}


__all__ = ["apagar", "estado", "ler", "limpar", "mascarada", "parece_chave",
           "pasta_de_config", "salvar"]
