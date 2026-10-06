"""
A censura das palavras proibidas: uma sílaba some, com asteriscos na legenda e nos
cartões e com bipe na voz. É a mesma regra nos três lugares, então eles nunca
divergem: "SEXO" vira "SE**", "cocaína" vira "coca**na", "decapitação" vira
"deca**tação".

Portado do separador de sílabas do vídeo de referência: uma divisão simples do
português, suficiente para palavras de narração, e não um dicionário. As letras
originais (maiúsculas, acentos) ficam.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_VOGAIS = set("aeiouáéíóúâêôãõàü")
_ACENTUADA_FRACA = set("íú")
_FRACA = set("iu")
_NASAL = set("ãõ")
#: Pares de consoantes que começam sílaba juntos (pra, bla, cha...).
_GRUPOS = {"pr", "br", "tr", "dr", "cr", "gr", "fr", "vr", "pl", "bl", "cl", "gl", "fl", "ch",
           "lh", "nh"}


def silabas(palavra: str) -> list[str]:
    """As sílabas da palavra, com as letras como vieram."""
    letras = list(palavra)
    baixas = [c.lower() for c in letras]

    def eh_vogal(i: int) -> bool:
        if not 0 <= i < len(letras) or baixas[i] not in _VOGAIS:
            return False
        # O "u" de qu/gu antes de e/i é parte da consoante.
        antes = baixas[i - 1] if i > 0 else ""
        depois = baixas[i + 1] if i + 1 < len(letras) else ""
        return not (baixas[i] == "u" and antes in ("q", "g") and depois in "eiéíê" and depois)

    # Os núcleos: a vogal e, depois dela, um i/u átono (ditongo decrescente: ai, ei, ou)
    # ou o o/e de ão/õe; o resto é hiato.
    nucleos: list[tuple[int, int]] = []
    i = 0
    while i < len(letras):
        if not eh_vogal(i):
            i += 1
            continue
        fim = i
        prox = baixas[i + 1] if i + 1 < len(letras) else ""
        ditongo = (baixas[i] not in _FRACA and prox in _FRACA and prox not in _ACENTUADA_FRACA
                   and not eh_vogal(i + 2))
        nasal = baixas[i] in _NASAL and prox in "oe"
        if eh_vogal(i + 1) and (ditongo or nasal):
            fim = i + 1
        nucleos.append((i, fim))
        i = fim + 1
    if len(nucleos) <= 1:
        return [palavra]

    # As consoantes entre dois núcleos.
    cortes = []
    for k in range(len(nucleos) - 1):
        de, ate = nucleos[k][1] + 1, nucleos[k + 1][0]
        meio = "".join(baixas[de:ate])
        if len(meio) <= 1:
            cortes.append(de)
        elif meio[-2:] in _GRUPOS:
            cortes.append(ate - 2)
        else:
            cortes.append(ate - 1)
    partes, inicio = [], 0
    for c in cortes:
        partes.append("".join(letras[inicio:c]))
        inicio = c
    partes.append("".join(letras[inicio:]))
    return partes


def silaba_escondida(total: int) -> int:
    """A sílaba que some: a do meio, nunca a primeira."""
    return 0 if total <= 1 else max(1, total // 2)


def censurar(palavra: str) -> str:
    """A palavra com a sílaba escondida em asteriscos (pelo menos dois)."""
    partes = silabas(palavra)
    k = silaba_escondida(len(partes))
    return "".join("*" * max(2, len(p)) if i == k else p for i, p in enumerate(partes))


def _nua(palavra: str) -> str:
    base = unicodedata.normalize("NFKD", palavra.lower())
    sem_acento = "".join(c for c in base if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]", "", sem_acento)


def _formas(n: str) -> set[str]:
    formas = {n}
    for fim, troca in (("oes", "ao"), ("aes", "ao"), ("ns", "m"), ("is", "l"), ("es", ""),
                       ("s", "")):
        if n.endswith(fim) and len(n) > len(fim) + 2:
            formas.add(n[: -len(fim)] + troca)
    return formas


def lista(texto: str | Iterable[str]) -> list[str]:
    """As palavras proibidas de um texto ("cocaína, sexo; decapitação") ou de uma lista."""
    partes = re.split(r"[,;\n]+", texto) if isinstance(texto, str) else list(texto)
    return [p.strip() for p in partes if p and p.strip()]


def proibida(palavra: str, palavras: Iterable[str]) -> bool:
    """Se a palavra (com pontuação, acento ou no plural) é uma das proibidas."""
    n = _nua(palavra)
    if len(n) < 2:
        return False
    alvos = {_nua(p) for p in palavras}
    return bool(_formas(n) & alvos) or n in alvos


def censurar_texto(texto: str, palavras: Iterable[str]) -> str:
    """O texto com cada palavra proibida censurada, e o resto como veio."""
    alvos = list(palavras)
    if not alvos:
        return texto

    def troca(m: re.Match) -> str:
        w = m.group(0)
        return censurar(w) if proibida(w, alvos) else w

    return re.sub(r"[^\W\d_]+", troca, texto)


__all__ = ["censurar", "censurar_texto", "lista", "proibida", "silaba_escondida", "silabas"]
