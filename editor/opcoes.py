"""As escolhas de edição — as mesmas na linha de comando e na interface."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

from editor.transcricao import IDIOMA_PADRAO, MODELO_PADRAO, MODELOS


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
    #: Na montagem em camadas, a pessoa (ou o personagem) muda de lugar em alguns cortes.
    mover: bool = True
    #: De 0,5 a 2: mais alto, mais adesivos, ícones, zooms e sons, mais próximos.
    ritmo: float = 1.0
    #: O zoom que o adesivo dá (0,06 = 6%).
    empurrao: float = 0.06
    #: O silêncio que fica no lugar de uma pausa cortada, em segundos.
    respiro: float = 0.15
    #: O tema dos efeitos (ver ``recursos/sons.json``).
    tema_dos_sons: str = "padrao"
    #: Um som curto e baixo em cada corte.
    som_nos_cortes: bool = False
    #: "dinheiro" chama moedas, "errado" uma buzina...
    sons_por_palavra: bool = True
    #: O volume dos efeitos (1,0 = o de sempre).
    volume_dos_sons: float = 1.0
    #: A largura da legenda; vazio, 18 em pé e 32 deitado.
    caracteres_por_linha: int | None = None

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
        if not 0.5 <= self.ritmo <= 2.0:
            erros.append("o ritmo vai de 0,5 a 2")
        if not 0.0 <= self.empurrao <= 0.15:
            erros.append("o empurrão do adesivo vai de 0 a 0,15")
        if not 0.05 <= self.respiro <= 0.4:
            erros.append("o respiro vai de 0,05 a 0,4 segundo")
        if not 0.3 <= self.volume_dos_sons <= 1.5:
            erros.append("o volume dos sons vai de 0,3 a 1,5")
        if self.caracteres_por_linha is not None and not 10 <= self.caracteres_por_linha <= 42:
            erros.append("a legenda vai de 10 a 42 caracteres por linha")
        from editor import sons

        if self.tema_dos_sons not in sons.temas():
            erros.append(f"tema de sons desconhecido: {self.tema_dos_sons} "
                         f"(use {', '.join(sons.temas())})")
        return erros

    @classmethod
    def de_dict(cls, dados: dict) -> OpcoesDeEdicao:
        conhecidos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (dados or {}).items() if k in conhecidos})

    def para_dict(self) -> dict:
        return asdict(self)


__all__ = ["OpcoesDeEdicao"]
