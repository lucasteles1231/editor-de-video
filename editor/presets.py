"""
Os presets: um ponto de partida para cada tipo de vídeo. Cada um decide o ritmo e as
edições, os sons, a legenda, a saída e o modelo e a cor da thumbnail; escolher um
preenche tudo isso, e cada valor continua editável depois.

O formato (em pé ou deitado) não é do preset: vem da plataforma onde o vídeo vai ser
postado, escolhida no passo 1 da página.

A página e o terminal leem daqui (a página pela ``/api/estado``). A thumbnail só existe
na página, então no terminal a parte dela não vale.

**Os presets de quem usa** ficam no ``presets.json`` da pasta de dados do usuário (ao lado
do ``config.json``): não vão para o repositório, e outra conta do computador não os vê.
Cada um guarda o mesmo que os prontos e passa pelas mesmas conferências da edição antes
de entrar, inclusive quando vem de um arquivo importado. Um nome de preset pronto não
pode ser usado.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from editor.opcoes import OpcoesDeEdicao

logger = logging.getLogger(__name__)

#: O que um preset decide nas edições. O idioma, o modelo do Whisper e o centro do zoom
#: são de quem edita, não do tipo de vídeo.
EDICAO = ("cortes", "zoom", "adesivos", "icones", "sons", "mover", "pausa_maxima",
          "nivel_zoom", "ritmo", "empurrao", "respiro", "tema_dos_sons", "som_nos_cortes",
          "sons_por_palavra", "volume_dos_sons", "tamanho_legenda", "caracteres_por_linha",
          "janela", "animacoes", "bipe", "voz", "estilo_da_legenda")
#: As palavras do bipe do vídeo de referência (o ponto de partida do preset de notícia;
#: cada vídeo tem as suas).
BIPE_DA_NOTICIA = "cocaína, sexo, sexual, decapitação, desmembramento"
SAIDA = ("resolucao", "fps", "qualidade")
THUMB = ("modelo", "cor")


@dataclass(frozen=True)
class Preset:
    nome: str
    titulo: str
    frase: str
    edicao: dict
    saida: dict
    thumb: dict
    #: Criado por quem usa (e não um dos prontos).
    meu: bool = False

    def opcoes(self, **por_cima) -> OpcoesDeEdicao:
        """As opções de edição deste preset, com o que vier em ``por_cima`` valendo mais."""
        return OpcoesDeEdicao(**{**self.edicao, **por_cima})

    def para_json(self) -> dict:
        return asdict(self)


def _preset(nome: str, titulo: str, frase: str, *, thumb: tuple[str, str],
            saida: dict | None = None, **edicao) -> Preset:
    desconhecidas = set(edicao) - set(EDICAO)
    assert not desconhecidas, desconhecidas
    padrao = OpcoesDeEdicao().para_dict()
    modelo, cor = thumb
    return Preset(nome, titulo, frase, {k: edicao.get(k, padrao[k]) for k in EDICAO},
                  {"resolucao": "original", "fps": "original", "qualidade": "alta",
                   **(saida or {})},
                  {"modelo": modelo, "cor": cor})


PRESETS: dict[str, Preset] = {p.nome: p for p in (
    _preset("padrao", "Padrão", "O equilíbrio de sempre: cortes, zoom, adesivos e ícones.",
            thumb=("classico", "amarelo")),
    _preset("gameplay", "Short de gameplay",
            "Rápido e barulhento: corte seco, zoom forte e um som em cada corte.",
            pausa_maxima=0.30, nivel_zoom=1.15, ritmo=1.5, empurrao=0.08,
            tema_dos_sons="gameplay", volume_dos_sons=1.2, som_nos_cortes=True,
            tamanho_legenda=1.15, caracteres_por_linha=14, saida={"fps": "60"},
            janela=True, animacoes=True, voz="limpa",
            thumb=("alerta", "lima")),
    _preset("vlog", "Short de vlog", "Conversa leve: deixa respirar, zoom discreto e sons suaves.",
            pausa_maxima=0.60, nivel_zoom=1.08, ritmo=0.8, empurrao=0.05,
            tema_dos_sons="suave", volume_dos_sons=0.8, janela=True, voz="limpa",
            thumb=("classico", "rosa")),
    _preset("review", "Short de review",
            "Opinião sobre um produto: o ritmo do padrão com sons de vitrine.",
            tema_dos_sons="review", tamanho_legenda=1.05, janela=True, animacoes=True, voz="limpa",
            thumb=("numero", "amarelo")),
    _preset("tecnico", "Explicação técnica",
            "Explica com calma: menos efeitos, frases mais longas na legenda.",
            pausa_maxima=0.50, nivel_zoom=1.06, ritmo=0.7, empurrao=0.04,
            tema_dos_sons="tecnico", volume_dos_sons=0.7, tamanho_legenda=0.95,
            caracteres_por_linha=20, janela=True, animacoes=True, voz="limpa",
            thumb=("pergunta", "ciano")),
    _preset("humor", "Humor", "Tempo de piada: corte seco, zoom exagerado e sons engraçados.",
            pausa_maxima=0.25, nivel_zoom=1.18, ritmo=1.6, empurrao=0.09,
            tema_dos_sons="humor", volume_dos_sons=1.2, som_nos_cortes=True,
            tamanho_legenda=1.2, caracteres_por_linha=14, janela=True, animacoes=True, voz="limpa",
            thumb=("alerta", "laranja")),
    _preset("motivacional", "Motivacional",
            "Frases de impacto: legenda grande, poucas palavras por vez e sons épicos.",
            pausa_maxima=0.40, nivel_zoom=1.14, ritmo=1.1, empurrao=0.07,
            tema_dos_sons="epico", volume_dos_sons=1.1, tamanho_legenda=1.25,
            caracteres_por_linha=14, janela=True, animacoes=True, voz="limpa",
            thumb=("classico", "vermelho")),
    _preset("podcast", "Corte de podcast",
            "A conversa respira: pausas maiores, quase nenhum efeito e a pessoa parada.",
            pausa_maxima=0.80, nivel_zoom=1.06, ritmo=0.6, empurrao=0.04, respiro=0.25,
            tema_dos_sons="suave", volume_dos_sons=0.6, sons_por_palavra=False, mover=False,
            janela=True, voz="limpa",
            thumb=("pergunta", "roxo")),
    _preset("noticia", "Notícia com cenas",
            "Narração com muitas imagens: cenas pela fala, janela com câmera, cartões, bipe e "
            "voz de estúdio.",
            pausa_maxima=0.35, nivel_zoom=1.12, ritmo=1.2, empurrao=0.06, adesivos=False,
            icones=False, tema_dos_sons="noticia", sons_por_palavra=False,
            volume_dos_sons=1.0, caracteres_por_linha=16,
            janela=True, animacoes=True, voz="estudio", bipe=BIPE_DA_NOTICIA,
            estilo_da_legenda="destaques", thumb=("alerta", "rosa")),
    _preset("aula", "Aula ou tutorial longo",
            "Vídeo longo: legenda larga, poucos efeitos e a pessoa parada.",
            pausa_maxima=0.60, nivel_zoom=1.05, ritmo=0.5, empurrao=0.04,
            tema_dos_sons="tecnico", volume_dos_sons=0.6, tamanho_legenda=0.9,
            caracteres_por_linha=36, mover=False, janela=True, animacoes=True, voz="limpa",
            thumb=("classico", "ciano")),
)}


# ── os presets de quem usa ───────────────────────────────────────────────

ARQUIVO = "presets.json"
TETO = 50
TITULO_MAXIMO = 40
FRASE_MAXIMA = 160


class PresetInvalido(ValueError):
    """O preset não serve (a mensagem diz por quê)."""


class PresetJaExiste(PresetInvalido):
    """Já há um preset seu com esse nome (salvar de novo substitui, se pedido)."""


def arquivo_dos_meus() -> Path:
    from editor.ia import pasta_de_dados

    return pasta_de_dados() / ARQUIVO


def apelido(titulo: str) -> str:
    """O nome do preset (para o ``--preset``): "Meu Vlog!" vira "meu-vlog"."""
    t = "".join(c for c in unicodedata.normalize("NFKD", str(titulo).lower())
                if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:TITULO_MAXIMO]


def _tipo_certo(valor, padrao) -> bool:
    numero = isinstance(valor, int | float) and not isinstance(valor, bool)
    if isinstance(padrao, bool):
        return isinstance(valor, bool)
    if isinstance(padrao, float):
        return numero
    if isinstance(padrao, int):
        return isinstance(valor, int) and not isinstance(valor, bool)
    if isinstance(padrao, str):
        return isinstance(valor, str)
    return valor is None or (isinstance(valor, int) and not isinstance(valor, bool))


def conferir(dados) -> Preset:
    """Um preset de quem usa, conferido como uma edição: o nome, cada valor e o tipo dele,
    a saída e a thumbnail. Os valores que faltarem ficam como os do padrão."""
    from editor import ia
    from editor import saida as saida_mod

    if not isinstance(dados, dict):
        raise PresetInvalido("Isso não é um preset.")
    titulo = re.sub(r"\s+", " ", str(dados.get("titulo") or "")).strip()
    if not titulo:
        raise PresetInvalido("Dê um nome ao preset.")
    if len(titulo) > TITULO_MAXIMO:
        raise PresetInvalido(f"O nome passa de {TITULO_MAXIMO} letras.")
    nome = apelido(titulo)
    if not nome:
        raise PresetInvalido("O nome precisa de pelo menos uma letra ou um número.")
    if nome in PRESETS or nome in {apelido(p.titulo) for p in PRESETS.values()}:
        raise PresetInvalido(f"“{titulo}” é o nome de um preset pronto: escolha outro.")
    frase = re.sub(r"\s+", " ", str(dados.get("frase") or "")).strip()[:FRASE_MAXIMA]
    padrao = OpcoesDeEdicao().para_dict()
    edicao = dados.get("edicao") or {}
    if not isinstance(edicao, dict):
        raise PresetInvalido("As edições do preset vieram num formato estranho.")
    final = {}
    for k in EDICAO:
        valor = edicao.get(k, padrao[k])
        if not _tipo_certo(valor, padrao[k]):
            raise PresetInvalido(f"O valor de “{k}” não serve.")
        final[k] = float(valor) if isinstance(padrao[k], float) else valor
    erros = OpcoesDeEdicao(**{**padrao, **final}).problemas()
    if erros:
        raise PresetInvalido("; ".join(erros))
    saida = dados.get("saida") or {}
    saida = {"resolucao": str(saida.get("resolucao", "original")),
             "fps": str(saida.get("fps", "original")),
             "qualidade": str(saida.get("qualidade", "alta"))} if isinstance(saida, dict) else {}
    if (saida.get("resolucao") not in saida_mod.RESOLUCOES or saida.get("fps") not in saida_mod.FPS
            or saida.get("qualidade") not in saida_mod.QUALIDADES):
        raise PresetInvalido("A saída do preset (resolução, quadros ou qualidade) não serve.")
    thumb = dados.get("thumb") or {}
    thumb = {"modelo": str(thumb.get("modelo", "classico")),
             "cor": str(thumb.get("cor", "amarelo"))} if isinstance(thumb, dict) else {}
    if thumb.get("modelo") not in ia.LAYOUTS or thumb.get("cor") not in ia.CORES:
        raise PresetInvalido("O modelo ou a cor da thumbnail do preset não serve.")
    return Preset(nome, titulo, frase or "Um preset seu.", final, saida, thumb, meu=True)


def meus() -> list[Preset]:
    """Os presets de quem usa, na ordem em que foram criados. Um arquivo estragado (ou um
    preset que não passa mais nas conferências) é deixado de lado, com um aviso."""
    try:
        dados = json.loads(arquivo_dos_meus().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as erro:
        logger.warning("os seus presets não puderam ser lidos (%s)", erro)
        return []
    lista = []
    for item in dados.get("presets", []) if isinstance(dados, dict) else []:
        try:
            lista.append(conferir(item))
        except PresetInvalido as erro:
            logger.warning("um preset seu foi deixado de lado: %s", erro)
    return lista


def todos() -> dict[str, Preset]:
    """Os prontos e, depois, os de quem usa."""
    return {**PRESETS, **{p.nome: p for p in meus()}}


def _gravar(lista: list[Preset]) -> None:
    destino = arquivo_dos_meus()
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".parcial")
    parcial.write_text(json.dumps(exportar(lista), ensure_ascii=False, indent=1),
                       encoding="utf-8")
    parcial.replace(destino)


def salvar(dados, *, substituir: bool = False) -> Preset:
    p = conferir(dados)
    atuais = meus()
    existe = any(x.nome == p.nome for x in atuais)
    if existe and not substituir:
        raise PresetJaExiste(f"Já existe um preset seu chamado “{p.titulo}”.")
    if not existe and len(atuais) >= TETO:
        raise PresetInvalido(f"Cabem até {TETO} presets seus: apague um antes.")
    if existe:
        atuais = [p if x.nome == p.nome else x for x in atuais]
    else:
        atuais.append(p)
    _gravar(atuais)
    return p


def apagar(nome: str) -> None:
    atuais = meus()
    if not any(x.nome == nome for x in atuais):
        raise PresetInvalido("Esse preset não existe (ou não é seu).")
    _gravar([x for x in atuais if x.nome != nome])


def exportar(lista: list[Preset] | None = None) -> dict:
    """O arquivo dos presets de quem usa: o mesmo que fica no disco e que a importação lê."""
    return {"editor-de-video": "presets", "versao": 1,
            "presets": [{k: v for k, v in asdict(p).items() if k not in ("nome", "meu")}
                        for p in (meus() if lista is None else lista)]}


def importar(dados) -> tuple[list[str], list[str]]:
    """Junta os presets de um arquivo exportado aos de quem usa (o mesmo nome substitui).
    Devolve os que entraram e os recusados, com o motivo."""
    lista = dados.get("presets") if isinstance(dados, dict) else dados
    if not isinstance(lista, list):
        raise PresetInvalido("Esse arquivo não tem presets do editor.")
    atuais = {p.nome: p for p in meus()}
    entraram, recusados = [], []
    for item in lista[: TETO * 2]:
        titulo = str(item.get("titulo") or "?")[:TITULO_MAXIMO] if isinstance(item, dict) else "?"
        try:
            p = conferir(item)
        except PresetInvalido as erro:
            recusados.append(f"{titulo}: {erro}")
            continue
        if p.nome not in atuais and len(atuais) >= TETO:
            recusados.append(f"{titulo}: não cabe (até {TETO} presets seus)")
            continue
        atuais[p.nome] = p
        entraram.append(p.titulo)
    if entraram:
        _gravar(list(atuais.values()))
    return entraram, recusados


def para_json() -> list[dict]:
    return [p.para_json() for p in todos().values()]


__all__ = ["EDICAO", "PRESETS", "SAIDA", "TETO", "THUMB", "Preset", "PresetInvalido",
           "PresetJaExiste", "apagar", "apelido", "arquivo_dos_meus", "conferir", "exportar",
           "importar", "meus", "para_json", "salvar", "todos"]
