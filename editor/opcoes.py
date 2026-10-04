"""As escolhas de edição — as mesmas na linha de comando e na interface."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from editor.transcricao import IDIOMA_PADRAO, MODELO_PADRAO, MODELOS

#: O que fica atrás da pessoa quando ela muda de lugar.
FUNDOS_DA_PESSOA = ("video", "cor")
#: As cores do fundo liso, as mesmas da thumbnail.
CORES = ("amarelo", "rosa", "ciano", "lima", "laranja", "roxo", "vermelho")


@dataclass
class OpcoesDeEdicao:
    cortes: bool = True
    zoom: bool = True
    adesivos: bool = True
    icones: bool = True
    sons: bool = True
    #: Pausas maiores que isto (segundos) viram corte.
    pausa_maxima: float = 0.45
    #: O nível do zoom de ênfase (1.12 = 12% mais perto).
    nivel_zoom: float = 1.12
    #: O centro do zoom, em fração do quadro (x, y).
    ancora_x: float = 0.5
    ancora_y: float = 0.40
    #: 1.0 é o tamanho padrão da legenda; 0.8 menor, 1.25 maior.
    tamanho_legenda: float = 1.0
    idioma: str = IDIOMA_PADRAO
    modelo: str = MODELO_PADRAO
    #: Em alguns cortes, a pessoa recortada vai para um lado, para cima, para baixo, para
    #: perto ou para longe. Desligado por padrão: o recorte quadro a quadro custa tempo.
    mover_pessoa: bool = False
    #: Atrás dela: "video" (o próprio vídeo desfocado, sem ela) ou "cor".
    fundo_da_pessoa: str = "video"
    cor_do_fundo: str = "roxo"

    def problemas(self) -> list[str]:
        erros = []
        if not 0.2 <= self.pausa_maxima <= 3.0:
            erros.append("a pausa máxima vai de 0,2 a 3 segundos")
        if not 1.0 <= self.nivel_zoom <= 1.5:
            erros.append("o zoom vai de 1,0 a 1,5")
        if not (0.0 <= self.ancora_x <= 1.0 and 0.0 <= self.ancora_y <= 1.0):
            erros.append("a âncora do zoom vai de 0 a 1 em cada eixo")
        if not 0.5 <= self.tamanho_legenda <= 2.0:
            erros.append("o tamanho da legenda vai de 0,5 a 2")
        if self.modelo not in MODELOS:
            erros.append(f"modelo desconhecido: {self.modelo} (use {', '.join(MODELOS)})")
        if self.fundo_da_pessoa not in FUNDOS_DA_PESSOA:
            erros.append(f"o fundo da pessoa é {' ou '.join(FUNDOS_DA_PESSOA)}")
        if self.cor_do_fundo not in CORES:
            erros.append(f"cor desconhecida: {self.cor_do_fundo} (use {', '.join(CORES)})")
        return erros

    @classmethod
    def de_dict(cls, dados: dict) -> OpcoesDeEdicao:
        conhecidos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (dados or {}).items() if k in conhecidos})

    def para_dict(self) -> dict:
        return asdict(self)


__all__ = ["CORES", "FUNDOS_DA_PESSOA", "OpcoesDeEdicao"]
