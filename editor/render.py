"""
O editor inteiro, do vídeo de entrada ao editado: transcrever → cortar → planejar →
desenhar e gravar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from editor import cortes, exportar, icones, plano, recorte, sons, transcricao
from editor import saida as saida_mod
from editor import video as video_mod
from editor.legenda import Legenda
from editor.montagem import Montador, Montagem, tamanho_do_quadro
from editor.opcoes import OpcoesDeEdicao

logger = logging.getLogger(__name__)

#: O fade nas bordas de cada corte, para o áudio não estalar.
FADE_S = 0.008
#: O empurrão de zoom no adesivo: 6% em 150 ms, e volta em 300 ms.
EMPURRAO = 0.06
EMPURRAO_ENTRA_S = 0.15
EMPURRAO_SAI_S = 0.30

#: (etapa, fração de 0 a 1 dela, detalhe)
Progresso = Callable[[str, float, str], None]


class Cancelado(Exception):
    """A edição foi cancelada por quem pediu."""


@dataclass
class Resultado:
    video: Path
    plano: Path
    legendas: list[Path] = field(default_factory=list)
    palavras: int = 0
    duracao_original: float = 0.0
    duracao_final: float = 0.0
    segundos: float = 0.0
    largura: int = 0
    altura: int = 0

    def para_dict(self) -> dict:
        return {"video": str(self.video), "plano": str(self.plano),
                "legendas": [str(p) for p in self.legendas], "palavras": self.palavras,
                "duracao_original": round(self.duracao_original, 2),
                "duracao_final": round(self.duracao_final, 2),
                "segundos": round(self.segundos, 1), "largura": self.largura,
                "altura": self.altura}


def pasta_de_cache() -> Path:
    from platformdirs import user_cache_dir

    pasta = Path(user_cache_dir("editor-de-video", appauthor=False)) / "transcricoes"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def obter_palavras(entrada: Path, duracao: float, edicao: OpcoesDeEdicao,
                   progresso: Progresso) -> list[transcricao.Palavra]:
    """A transcrição guardada deste arquivo (vídeo ou áudio), ou uma nova."""
    origem = transcricao.identidade(entrada, idioma=edicao.idioma, modelo=edicao.modelo)
    chave = hashlib.sha1(json.dumps(origem, sort_keys=True).encode()).hexdigest()[:16]
    guardada = pasta_de_cache() / f"{chave}.json"
    palavras = transcricao.carregar(guardada, origem=origem)
    if palavras is not None:
        progresso("transcrevendo", 1.0, "transcrição reaproveitada")
        return palavras
    if not transcricao.modelo_baixado(edicao.modelo):
        progresso("transcrevendo", 0.0,
                  f"baixando o modelo {edicao.modelo} ({transcricao.MODELOS[edicao.modelo]}),"
                  " só na primeira vez")
    palavras = transcricao.transcrever(
        entrada, idioma=edicao.idioma, modelo=edicao.modelo, duracao=duracao,
        progresso=lambda f: progresso("transcrevendo", f, ""))
    transcricao.salvar(palavras, guardada, origem=origem)
    return palavras


def empurrao(p: plano.Plano, t: float) -> float:
    """O quanto a mais de zoom o adesivo dá em ``t`` (0 sem empurrão)."""
    extra = 0.0
    for a, b in p.empurroes:
        if a <= t < b:
            extra = max(extra, EMPURRAO * min(1.0, (t - a) / EMPURRAO_ENTRA_S))
        elif b <= t < b + EMPURRAO_SAI_S:
            extra = max(extra, EMPURRAO * (1 - (t - b) / EMPURRAO_SAI_S))
    return extra


def nivel_base(p: plano.Plano, t: float) -> float:
    """O nível de zoom dos cortes em ``t``, sem o empurrão do adesivo."""
    nivel = 1.0
    for inicio, n in p.zoom:
        if inicio <= t:
            nivel = n
        else:
            break
    return nivel


def nivel_de_zoom(p: plano.Plano, t: float) -> float:
    return nivel_base(p, t) * (1 + empurrao(p, t))


def janela(largura: int, altura: int, nivel: float, ax: float, ay: float
           ) -> tuple[float, float, float, float]:
    """A janela do quadro original que o zoom mostra."""
    cw, ch = largura / nivel, altura / nivel
    x0 = min(max(ax * largura - cw / 2, 0.0), largura - cw)
    y0 = min(max(ay * altura - ch / 2, 0.0), altura - ch)
    return x0, y0, x0 + cw, y0 + ch


def montar_audio(audio: np.ndarray, linha: cortes.Linha, plano_: plano.Plano) -> np.ndarray:
    """O áudio só com os trechos que ficam, com fade nas bordas, e os efeitos por baixo."""
    taxa = video_mod.TAXA
    fade = max(1, int(FADE_S * taxa))
    pedacos = []
    for t in linha.trechos:
        p = audio[int(t.ini * taxa):int(t.fim * taxa)].copy()
        if len(p) > 2 * fade:
            rampa = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
            p[:fade] *= rampa
            p[-fade:] *= rampa[::-1]
        pedacos.append(p)
    voz = np.concatenate(pedacos) if pedacos else np.zeros((0, 2), np.float32)
    alvo = round(linha.duracao * taxa)
    if len(voz) < alvo:
        voz = np.concatenate([voz, np.zeros((alvo - len(voz), 2), np.float32)])
    if plano_.sons:
        voz = sons.misturar(voz, sons.trilha(plano_.sons, linha.duracao, taxa))
    return np.ascontiguousarray(voz.astype(np.float32))


def _icones(img: Image.Image, p: plano.Plano, t: float, lado_livre: int = 0) -> None:
    """Os ícones do momento. Com a pessoa num lado, eles vão para o outro."""
    largura, altura = img.size
    raio = round(min(largura, altura) * 0.09)
    for k, ic in enumerate(p.icones):
        if not ic.inicio <= t < ic.fim:
            continue
        s = icones.escala(t - ic.inicio, ic.fim - ic.inicio)
        if s <= 0.02:
            continue
        balao = icones.balao(ic.nome, raio, semente=k + 1)
        if abs(s - 1.0) > 0.01:
            lado = max(2, round(balao.width * s))
            balao = balao.resize((lado, lado), Image.BILINEAR)
        lado = lado_livre or ic.lado
        if p.vertical:
            cx, cy = largura * (0.5 + 0.30 * lado), altura * 0.27
        else:
            cx, cy = largura * (0.5 + 0.40 * lado), altura * 0.22
        img.paste(balao, (round(cx - balao.width / 2), round(cy - balao.height / 2)), balao)


@dataclass
class _Fala:
    """O que a fala decidiu: a linha do tempo, o plano e o som final."""

    linha: cortes.Linha
    plano: plano.Plano
    palavras: int
    duracao: float
    som: np.ndarray | None


def _planejar(fala: Path, duracao_da_fala: float, tem_audio: bool, edicao: OpcoesDeEdicao,
              saida_r: saida_mod.OpcoesDeSaida, previa_s: float | None, *, vertical: bool,
              mover: bool, avisar: Progresso, parar: Callable[[], bool]) -> _Fala:
    """Transcreve, corta e planeja a partir do arquivo da fala."""
    duracao = duracao_da_fala if not previa_s else min(duracao_da_fala, previa_s)
    if saida_r.formato == "gif":
        duracao = min(duracao, saida_mod.GIF_MAX_S)
    palavras = obter_palavras(fala, duracao_da_fala, edicao, avisar) if tem_audio else []
    palavras = [p for p in palavras if p.inicio < duracao]
    if parar():
        raise Cancelado

    avisar("cortando", 0.0, "")
    audio = (video_mod.ler_audio(fala, duracao_da_fala)[: int(duracao * video_mod.TAXA)]
             if tem_audio else np.zeros((0, 2), np.float32))
    if edicao.cortes and palavras:
        trechos = cortes.calcular(palavras, audio.mean(axis=1) if len(audio) else None,
                                  video_mod.TAXA, duracao, pausa_maxima=edicao.pausa_maxima)
    else:
        trechos = [cortes.Trecho(0.0, duracao)]
    linha = cortes.Linha(trechos)
    no_editado = linha.palavras(palavras)
    p = plano.montar(no_editado, linha.duracao, vertical=vertical, cortes=linha.cortes,
                     opcoes=edicao, nomes_de_icones=set(icones.nomes()), mover=mover)
    p.trechos = [(round(tr.ini, 3), round(tr.fim, 3)) for tr in linha.trechos]
    som = montar_audio(audio, linha, p) if tem_audio else None
    avisar("cortando", 1.0, f"{len(trechos)} trecho(s), {linha.duracao:.1f} s de "
                            f"{duracao:.1f} s")
    return _Fala(linha, p, len(palavras), duracao, som)


def _terminar(p: plano.Plano, destino: Path, saida_r: saida_mod.OpcoesDeSaida,
              avisar: Progresso) -> tuple[Path, list[Path]]:
    plano_json = destino.with_name(destino.stem + ".plano.json")
    plano_json.write_text(json.dumps(p.para_json(), ensure_ascii=False, indent=1),
                          encoding="utf-8")
    legendas = exportar.gravar(p, destino, com_srt=saida_r.srt, com_vtt=saida_r.vtt)
    avisar("pronto", 1.0, "")
    return plano_json, legendas


def editar(entrada: Path | None, destino: Path, edicao: OpcoesDeEdicao,
           opcoes_saida: saida_mod.OpcoesDeSaida, *, previa_s: float | None = None,
           progresso: Progresso | None = None,
           cancelar: Callable[[], bool] | None = None,
           montagem: Montagem | None = None) -> Resultado:
    """Edita ``entrada`` (ou a ``montagem``, em camadas) e grava em ``destino``.

    Levanta :class:`Cancelado` se pedirem."""
    comeco = time.monotonic()
    avisar = progresso or (lambda etapa, fracao, detalhe: None)
    parar = cancelar or (lambda: False)
    erros = edicao.problemas() + opcoes_saida.problemas()
    if montagem is not None:
        erros += montagem.problemas()
    if erros:
        raise ValueError("; ".join(erros))
    saida_r = opcoes_saida.resolvidas()
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if montagem is not None:
        return _editar_montagem(montagem, destino, edicao, saida_r, previa_s, avisar, parar,
                                comeco)

    entrada = Path(entrada)
    info = video_mod.sondar(entrada)
    f = _planejar(entrada, info.duracao, info.tem_audio, edicao, saida_r, previa_s,
                  vertical=info.vertical, mover=False, avisar=avisar, parar=parar)
    linha, p, duracao, som_final = f.linha, f.plano, f.duracao, f.som

    largura, altura = saida_mod.tamanho(info.largura, info.altura, saida_r.resolucao,
                                        saida_r.formato)
    fps = saida_mod.fps_de_saida(info.fps, saida_r.fps, saida_r.formato)
    legenda = Legenda(largura, altura, vertical=info.vertical, tamanho=edicao.tamanho_legenda)
    passo = 1.0 / float(fps)
    total_quadros = max(1, round(linha.duracao * float(fps)))

    with video_mod.Gravador(destino, saida_r, largura, altura, fps,
                            com_audio=som_final is not None) as gravador:
        if som_final is not None:
            gravador.preparar_audio(som_final)
        ultimo = None
        for t_src, matriz in video_mod.quadros(entrada, info.rotacao):
            if t_src > duracao:
                break
            t_out = linha.para_saida(t_src)
            if t_out is None:
                continue
            ultimo = matriz
            while gravador.indice < total_quadros and gravador.indice * passo <= t_out + passo / 2:
                _desenhar_quadro(gravador, matriz, p, legenda, edicao, largura, altura,
                                 gravador.indice * passo)
                if gravador.indice % 15 == 0:
                    avisar("desenhando", gravador.indice / total_quadros,
                           f"quadro {gravador.indice} de {total_quadros}")
                    if parar():
                        raise Cancelado
        while ultimo is not None and gravador.indice < total_quadros:
            _desenhar_quadro(gravador, ultimo, p, legenda, edicao, largura, altura,
                             gravador.indice * passo)
        avisar("finalizando", 0.5, "fechando o arquivo")

    plano_json, legendas = _terminar(p, destino, saida_r, avisar)
    return Resultado(destino, plano_json, legendas, f.palavras, duracao, linha.duracao,
                     time.monotonic() - comeco, largura, altura)


def _desenhar_quadro(gravador: video_mod.Gravador, matriz: np.ndarray, p: plano.Plano,
                     legenda: Legenda, edicao: OpcoesDeEdicao, largura: int, altura: int,
                     t: float) -> None:
    img = Image.fromarray(matriz)
    nivel = nivel_de_zoom(p, t)
    caixa = janela(img.width, img.height, nivel, edicao.ancora_x, edicao.ancora_y)
    if nivel > 1.0005 or img.size != (largura, altura):
        img = img.resize((largura, altura), Image.BILINEAR, box=caixa)
    _icones(img, p, t)
    legenda.desenhar(img, p, t)
    gravador.quadro(np.asarray(img))


def _editar_montagem(montagem: Montagem, destino: Path, edicao: OpcoesDeEdicao,
                     saida_r: saida_mod.OpcoesDeSaida, previa_s: float | None,
                     avisar: Progresso, parar: Callable[[], bool], comeco: float) -> Resultado:
    """O vídeo em camadas: o fundo encaixado e, por cima, a pessoa ou o personagem.

    O laço anda pelos quadros de saída: cada camada busca o quadro do instante de origem
    no próprio cursor (os vídeos podem ter fps diferentes), e o personagem anda pelo
    tempo de saída, para não pular nos cortes."""
    info_do_fundo = video_mod.sondar(montagem.fundo)
    fala = montagem.fonte_da_fala()
    if montagem.audio is not None and Path(fala) == Path(montagem.audio):
        duracao_da_fala, tem_audio = video_mod.duracao_do_audio(fala), True
    else:
        info_da_fala = video_mod.sondar(fala)
        duracao_da_fala, tem_audio = info_da_fala.duracao, info_da_fala.tem_audio
    if not tem_audio:
        avisar("transcrevendo", 1.0, "sem fala: o vídeo sai sem cortes e sem legenda")

    largura, altura = saida_mod.tamanho(
        *tamanho_do_quadro(montagem.formato, info_do_fundo.largura, info_do_fundo.altura),
        saida_r.resolucao, saida_r.formato)
    f = _planejar(fala, duracao_da_fala, tem_audio, edicao, saida_r, previa_s,
                  vertical=altura > largura, mover=edicao.mover, avisar=avisar, parar=parar)
    linha, p = f.linha, f.plano

    if montagem.pessoa is not None and montagem.recorte == "modnet":
        if not recorte.modelo_baixado():
            avisar("desenhando", 0.0, f"baixando o modelo de recorte ({recorte.TAMANHO}), "
                                      "só na primeira vez")
        if not recorte.preparar_modelo():
            raise RuntimeError("Não consegui baixar o modelo de recorte. Confira a internet, "
                               "ou envie o vídeo da pessoa já sem fundo.")
    montador = Montador(montagem, p, largura, altura, info_do_fundo, mover=edicao.mover)
    fps = saida_mod.fps_de_saida(info_do_fundo.fps, saida_r.fps, saida_r.formato)
    legenda = Legenda(largura, altura, vertical=altura > largura,
                      tamanho=edicao.tamanho_legenda)
    passo = 1.0 / float(fps)
    total_quadros = max(1, round(linha.duracao * float(fps)))

    with video_mod.Gravador(destino, saida_r, largura, altura, fps,
                            com_audio=f.som is not None) as gravador:
        if f.som is not None:
            gravador.preparar_audio(f.som)
        for i in range(total_quadros):
            t_saida = i * passo
            t_origem = linha.para_origem(t_saida)
            img = montador.quadro(t_origem, t_saida, nivel=nivel_base(p, t_saida),
                                  extra=empurrao(p, t_saida))
            _icones(img, p, t_saida, montador.lado_livre(t_saida))
            legenda.desenhar(img, p, t_saida)
            gravador.quadro(np.asarray(img))
            if i % 15 == 0:
                avisar("desenhando", i / total_quadros, f"quadro {i} de {total_quadros}")
                if parar():
                    raise Cancelado
        avisar("finalizando", 0.5, "fechando o arquivo")

    plano_json, legendas = _terminar(p, destino, saida_r, avisar)
    return Resultado(destino, plano_json, legendas, f.palavras, f.duracao, linha.duracao,
                     time.monotonic() - comeco, largura, altura)


__all__ = ["Cancelado", "Resultado", "editar", "empurrao", "janela", "montar_audio",
           "nivel_base", "nivel_de_zoom"]
