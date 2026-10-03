"""
Os cortes de silêncio: quais trechos do vídeo ficam.

Uma pausa maior que :data:`PAUSA_MAXIMA_S` vira um respiro curto
(:data:`RESPIRO_S`), e o começo e o fim do vídeo são aparados.

**A pausa é medida no áudio, não no tempo do Whisper.** Ele erra os dois lados da
palavra, cada um de um jeito:

- o **fim** sai cedo, de 30 a 300 ms. Cortar ali come a última sílaba, então o fim
  procura a pausa real numa janela em volta do tempo dele (:func:`pausa_perto`);
- o **começo** da palavra que vem depois de uma pausa sai *muito* cedo: o Whisper dá
  a ela o silêncio que vem antes (medido com fala real: até 0,9 s). Cortar ali deixa a
  pausa quase inteira, então o começo procura do tempo dele até o fim da palavra;
- às vezes o silêncio inteiro vai para dentro da palavra, e as duas palavras parecem
  coladas: por isso também se procura, entre duas palavras "coladas", um silêncio
  engolido maior que a pausa máxima.
"""
from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from editor.transcricao import Palavra

#: Uma pausa maior que isto entre duas palavras vira corte.
PAUSA_MAXIMA_S = 0.45
#: Quanto do silêncio fica entre duas falas depois do corte (meio de cada lado).
RESPIRO_S = 0.15
#: Onde procurar a pausa real em volta da borda do Whisper: um pouco antes, bem
#: mais depois — é depois que a pausa costuma estar.
ANTES_DA_BORDA_S = 0.10
DEPOIS_DA_BORDA_S = 0.40
#: O silêncio no começo de uma fala só conta se tiver pelo menos isto: sem pausa
#: antes (vídeo que já abre falando), a mais longa da janela seria o fechamento de
#: uma consoante dentro da primeira palavra, de 50 a 100 ms.
PAUSA_NO_COMECO_S = 0.15
#: Folga quando não há pausa clara (fala colada em música, por exemplo).
FOLGA_SEM_PAUSA_S = 0.06
#: O que conta como pausa: até 6 dB acima do ponto mais baixo da janela, com pelo
#: menos 20 dB de contraste entre o mais alto e o mais baixo, e 30 ms de duração.
PAUSA_RELATIVA_DB = 6.0
CONTRASTE_MINIMO_DB = 20.0
PAUSA_MINIMA_S = 0.03
#: E também conta como pausa o que fica 30 dB abaixo do pico da janela. Só com a
#: régua do fundo, um silêncio digital (zeros) depois da palavra puxava o fundo para
#: −140 dB: a pausa natural (−44 dB) deixava de contar e o corte caía no meio da
#: cauda da última sílaba — visto com fala real.
SILENCIO_ABAIXO_DO_PICO_DB = 30.0
#: Dois trechos mais próximos que isto viram um só.
JUNTAR_ABAIXO_DE_S = 0.05


@dataclass(frozen=True)
class Trecho:
    """Um pedaço do vídeo original que fica, em segundos."""

    ini: float
    fim: float

    @property
    def duracao(self) -> float:
        return self.fim - self.ini


def pausa_perto(amostras: np.ndarray, taxa: int, de: float, ate: float
                ) -> tuple[float, float] | None:
    """A pausa mais longa entre ``de`` e ``ate`` (segundos), ou ``None``.

    **A mais longa, e não a primeira.** Dentro de uma palavra também há silêncio —
    o fechamento do "t" dura uns 50 ms — e cortar ali tira a sílaba do mesmo jeito.
    A pausa entre duas frases é mais longa que qualquer uma delas.
    """
    passo = max(1, int(0.01 * taxa))
    i0, i1 = max(0, int(de * taxa)), min(len(amostras), int(ate * taxa))
    quadros = (i1 - i0) // passo
    if quadros < 3:
        return None
    trecho = np.asarray(amostras[i0:i0 + quadros * passo], dtype=np.float32)
    rms = np.sqrt(np.mean(trecho.reshape(quadros, passo) ** 2, axis=1))
    rms = np.convolve(rms, np.ones(3) / 3, mode="same")
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    if db.max() - db.min() < CONTRASTE_MINIMO_DB:
        return None
    limiar = max(db.min() + PAUSA_RELATIVA_DB, db.max() - SILENCIO_ABAIXO_DO_PICO_DB)
    corridas, comeco = [], None
    for k, v in enumerate(db):
        if v <= limiar and comeco is None:
            comeco = k
        elif v > limiar and comeco is not None:
            corridas.append((comeco, k))
            comeco = None
    if comeco is not None:
        corridas.append((comeco, quadros))
    corridas = [c for c in corridas if (c[1] - c[0]) * passo / taxa >= PAUSA_MINIMA_S]
    if not corridas:
        return None
    a, b = max(corridas, key=lambda c: (c[1] - c[0], -c[0]))
    base = i0 / taxa
    return base + a * passo / taxa, base + b * passo / taxa


def calcular(palavras: Sequence[Palavra], amostras: np.ndarray | None, taxa: int,
             duracao: float, *, pausa_maxima: float = PAUSA_MAXIMA_S,
             respiro: float = RESPIRO_S) -> list[Trecho]:
    """Os trechos a manter. Sem palavras, o vídeo fica inteiro."""
    ws = sorted(palavras, key=lambda p: p.inicio)
    if not ws or duracao <= 0:
        return [Trecho(0.0, max(0.0, duracao))]
    # O que sai: o silêncio antes da primeira palavra, as pausas longas e o silêncio
    # depois da última. O que fica é o que sobra entre eles.
    fora = [(0.0, max(0.0, _comeco_real(ws[0], 0.0, amostras, taxa)))]
    for a, b in pairwise(ws):
        pausa = _pausa_entre(a, b, pausa_maxima, amostras, taxa)
        if pausa:
            fora.append(pausa)
    fora.append((min(duracao, _fim_real(ws[-1].fim, duracao, amostras, taxa)), duracao))
    meio = respiro / 2
    fora = _unir(fora)
    trechos = [Trecho(max(0.0, ini - meio), min(duracao, fim + meio))
               for (_, ini), (fim, _) in pairwise(fora)]
    return _juntar(trechos)


def _pausa_entre(a: Palavra, b: Palavra, pausa_maxima: float, amostras, taxa: int
                 ) -> tuple[float, float] | None:
    """O silêncio a cortar entre duas palavras seguidas, ou ``None``."""
    vao = b.inicio - a.fim
    if amostras is None:
        if vao > pausa_maxima:
            return a.fim + FOLGA_SEM_PAUSA_S, b.inicio - FOLGA_SEM_PAUSA_S
        return None
    if vao > pausa_maxima:
        fim = _fim_real(a.fim, b.inicio, amostras, taxa)
        return fim, _comeco_real(b, fim, amostras, taxa)
    # O Whisper diz que estão coladas, mas pode ter posto a pausa dentro de uma delas.
    # A janela vai do meio da primeira ao fim da segunda; o fechamento de uma
    # consoante não passa de 100 ms, então nada dentro da palavra chega à pausa máxima.
    achada = pausa_perto(amostras, taxa, (a.inicio + a.fim) / 2, b.fim)
    if achada and achada[1] - achada[0] > pausa_maxima:
        return achada
    return None


def _comeco_real(palavra: Palavra, limite: float, amostras, taxa: int) -> float:
    """Onde o som da palavra começa: o fim da pausa entre o tempo do Whisper (que sai
    cedo) e o fim da palavra."""
    if amostras is None:
        return palavra.inicio - FOLGA_SEM_PAUSA_S
    de = max(limite + 0.02, palavra.inicio - DEPOIS_DA_BORDA_S)
    ate = max(palavra.fim, palavra.inicio + ANTES_DA_BORDA_S)
    achada = pausa_perto(amostras, taxa, de, ate)
    if achada and achada[1] - achada[0] >= PAUSA_NO_COMECO_S:
        return achada[1]
    return palavra.inicio - FOLGA_SEM_PAUSA_S


def _fim_real(fim: float, limite: float, amostras, taxa: int) -> float:
    if amostras is None:
        return fim + FOLGA_SEM_PAUSA_S
    ate = min(limite - 0.02, fim + DEPOIS_DA_BORDA_S)
    achada = pausa_perto(amostras, taxa, fim - ANTES_DA_BORDA_S, ate)
    return achada[0] if achada else fim + FOLGA_SEM_PAUSA_S


def _unir(fora: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Os silêncios em ordem e sem sobreposição: o mesmo silêncio engolido pode ser
    achado pelos dois pares de palavras em volta dele."""
    saida: list[tuple[float, float]] = []
    for ini, fim in sorted(fora):
        if saida and ini <= saida[-1][1]:
            saida[-1] = (saida[-1][0], max(saida[-1][1], fim))
        else:
            saida.append((ini, max(ini, fim)))
    return saida


def _juntar(trechos: list[Trecho]) -> list[Trecho]:
    saida: list[Trecho] = []
    for t in sorted(trechos, key=lambda t: t.ini):
        if t.duracao <= 0:
            continue
        if saida and t.ini - saida[-1].fim < JUNTAR_ABAIXO_DE_S:
            saida[-1] = Trecho(saida[-1].ini, max(saida[-1].fim, t.fim))
        else:
            saida.append(t)
    return saida


class Linha:
    """O mapa do tempo original para o tempo do vídeo editado."""

    def __init__(self, trechos: Sequence[Trecho]):
        self.trechos = list(trechos)
        self._inicios = [t.ini for t in self.trechos]
        self._na_saida, acumulado = [], 0.0
        for t in self.trechos:
            self._na_saida.append(acumulado)
            acumulado += t.duracao
        self.duracao = acumulado

    def _trecho_de(self, t: float) -> int | None:
        i = bisect_right(self._inicios, t) - 1
        if i < 0 or t > self.trechos[i].fim:
            return None
        return i

    def para_saida(self, t: float) -> float | None:
        """O instante de saída de ``t``, ou ``None`` se ``t`` foi cortado."""
        i = self._trecho_de(t)
        return None if i is None else self._na_saida[i] + (t - self.trechos[i].ini)

    def prender(self, t: float) -> float:
        """Como :meth:`para_saida`, mas um instante cortado vai para a borda mais próxima."""
        dentro = self.para_saida(t)
        if dentro is not None:
            return dentro
        i = bisect_right(self._inicios, t) - 1
        if i < 0:
            return 0.0
        if i + 1 < len(self.trechos) and (self.trechos[i + 1].ini - t) < (t - self.trechos[i].fim):
            return self._na_saida[i + 1]
        return self._na_saida[i] + self.trechos[i].duracao

    @property
    def cortes(self) -> list[float]:
        """Os instantes de saída em que houve corte (onde dois trechos se encontram)."""
        return self._na_saida[1:]

    def palavras(self, palavras: Sequence[Palavra]) -> list[Palavra]:
        """As palavras no tempo de saída; as que caíram inteiras num corte somem.

        Uma palavra que atravessa um corte é a que ganhou do Whisper o silêncio de
        antes: o som dela está onde ela termina, e é lá que ela começa na saída — senão
        a legenda acenderia a palavra ainda na frase anterior.
        """
        saida = []
        for p in palavras:
            i, j = self._trecho_de(p.inicio), self._trecho_de(p.fim)
            if i is None and j is None:
                i = j = self._trecho_de((p.inicio + p.fim) / 2)
                if i is None:
                    continue
            if j is None:
                j = i
            if i is None or i != j:
                i = j
            a = self.para_saida(max(p.inicio, self.trechos[i].ini))
            b = self.para_saida(min(p.fim, self.trechos[j].fim))
            if b <= a:
                b = a + 0.05
            saida.append(Palavra(p.texto, round(a, 3), round(b, 3), p.prob))
        return saida


__all__ = ["PAUSA_MAXIMA_S", "RESPIRO_S", "Linha", "Trecho", "calcular", "pausa_perto"]
