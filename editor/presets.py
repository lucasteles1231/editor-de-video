"""
Os presets: um ponto de partida para cada tipo de vídeo. Cada um decide o ritmo e as
edições, os sons, a legenda, a saída e a thumbnail; escolher um preenche tudo isso, e
cada valor continua editável depois.

A página e o terminal leem daqui (a página pela ``/api/estado``). A thumbnail só existe
na página, então no terminal a parte dela não vale.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from editor.opcoes import OpcoesDeEdicao

#: O que um preset decide nas edições. O idioma, o modelo do Whisper e o centro do zoom
#: são de quem edita, não do tipo de vídeo.
EDICAO = ("cortes", "zoom", "adesivos", "icones", "sons", "mover", "pausa_maxima",
          "nivel_zoom", "ritmo", "empurrao", "respiro", "tema_dos_sons", "som_nos_cortes",
          "sons_por_palavra", "volume_dos_sons", "tamanho_legenda", "caracteres_por_linha")
SAIDA = ("resolucao", "fps", "qualidade")
THUMB = ("modelo", "cor", "tamanhos")

EM_PE = ["1080x1920"]
DEITADO = ["1280x720"]


@dataclass(frozen=True)
class Preset:
    nome: str
    titulo: str
    frase: str
    edicao: dict
    saida: dict
    #: O formato do vídeo na montagem em camadas ("fundo" é o do vídeo de fundo).
    quadro: str
    thumb: dict

    def opcoes(self, **por_cima) -> OpcoesDeEdicao:
        """As opções de edição deste preset, com o que vier em ``por_cima`` valendo mais."""
        return OpcoesDeEdicao(**{**self.edicao, **por_cima})

    def para_json(self) -> dict:
        return asdict(self)


def _preset(nome: str, titulo: str, frase: str, *, thumb: tuple[str, str, list[str]],
            quadro: str = "vertical", saida: dict | None = None, **edicao) -> Preset:
    desconhecidas = set(edicao) - set(EDICAO)
    assert not desconhecidas, desconhecidas
    padrao = OpcoesDeEdicao().para_dict()
    modelo, cor, tamanhos = thumb
    return Preset(nome, titulo, frase, {k: edicao.get(k, padrao[k]) for k in EDICAO},
                  {"resolucao": "original", "fps": "original", "qualidade": "alta",
                   **(saida or {})},
                  quadro, {"modelo": modelo, "cor": cor, "tamanhos": list(tamanhos)})


PRESETS: dict[str, Preset] = {p.nome: p for p in (
    _preset("padrao", "Padrão", "O equilíbrio de sempre: cortes, zoom, adesivos e ícones.",
            quadro="fundo", thumb=("classico", "amarelo", DEITADO)),
    _preset("gameplay", "Short de gameplay",
            "Rápido e barulhento: corte seco, zoom forte e um som em cada corte.",
            pausa_maxima=0.30, nivel_zoom=1.15, ritmo=1.5, empurrao=0.08,
            tema_dos_sons="gameplay", volume_dos_sons=1.2, som_nos_cortes=True,
            tamanho_legenda=1.15, caracteres_por_linha=14, saida={"fps": "60"},
            thumb=("alerta", "lima", EM_PE)),
    _preset("vlog", "Short de vlog", "Conversa leve: deixa respirar, zoom discreto e sons suaves.",
            pausa_maxima=0.60, nivel_zoom=1.08, ritmo=0.8, empurrao=0.05,
            tema_dos_sons="suave", volume_dos_sons=0.8, thumb=("classico", "rosa", EM_PE)),
    _preset("review", "Short de review",
            "Opinião sobre um produto: o ritmo do padrão com sons de vitrine.",
            tema_dos_sons="review", tamanho_legenda=1.05, thumb=("numero", "amarelo", EM_PE)),
    _preset("tecnico", "Explicação técnica",
            "Explica com calma: menos efeitos, frases mais longas na legenda.",
            pausa_maxima=0.50, nivel_zoom=1.06, ritmo=0.7, empurrao=0.04,
            tema_dos_sons="tecnico", volume_dos_sons=0.7, tamanho_legenda=0.95,
            caracteres_por_linha=20, thumb=("pergunta", "ciano", EM_PE)),
    _preset("humor", "Humor", "Tempo de piada: corte seco, zoom exagerado e sons engraçados.",
            pausa_maxima=0.25, nivel_zoom=1.18, ritmo=1.6, empurrao=0.09,
            tema_dos_sons="humor", volume_dos_sons=1.2, som_nos_cortes=True,
            tamanho_legenda=1.2, caracteres_por_linha=14, thumb=("alerta", "laranja", EM_PE)),
    _preset("motivacional", "Motivacional",
            "Frases de impacto: legenda grande, poucas palavras por vez e sons épicos.",
            pausa_maxima=0.40, nivel_zoom=1.14, ritmo=1.1, empurrao=0.07,
            tema_dos_sons="epico", volume_dos_sons=1.1, tamanho_legenda=1.25,
            caracteres_por_linha=14, thumb=("classico", "vermelho", EM_PE)),
    _preset("podcast", "Corte de podcast",
            "A conversa respira: pausas maiores, quase nenhum efeito e a pessoa parada.",
            pausa_maxima=0.80, nivel_zoom=1.06, ritmo=0.6, empurrao=0.04, respiro=0.25,
            tema_dos_sons="suave", volume_dos_sons=0.6, sons_por_palavra=False, mover=False,
            thumb=("pergunta", "roxo", EM_PE)),
    _preset("aula", "Aula ou tutorial longo",
            "Vídeo deitado e longo: legenda larga, poucos efeitos e a pessoa parada.",
            quadro="horizontal", pausa_maxima=0.60, nivel_zoom=1.05, ritmo=0.5, empurrao=0.04,
            tema_dos_sons="tecnico", volume_dos_sons=0.6, tamanho_legenda=0.9,
            caracteres_por_linha=36, mover=False, thumb=("classico", "ciano", DEITADO)),
)}


def para_json() -> list[dict]:
    return [p.para_json() for p in PRESETS.values()]


__all__ = ["EDICAO", "PRESETS", "SAIDA", "THUMB", "Preset", "para_json"]
