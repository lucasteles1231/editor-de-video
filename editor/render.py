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

from editor import cortes, exportar, icones, mover, plano, recorte, sons, transcricao
from editor import saida as saida_mod
from editor import video as video_mod
from editor.legenda import Legenda
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


def obter_palavras(entrada: Path, info: video_mod.Info, edicao: OpcoesDeEdicao,
                   progresso: Progresso) -> list[transcricao.Palavra]:
    """A transcrição guardada deste vídeo, ou uma nova."""
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
        entrada, idioma=edicao.idioma, modelo=edicao.modelo, duracao=info.duracao,
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


def nivel_de_zoom(p: plano.Plano, t: float) -> float:
    nivel = 1.0
    for inicio, n in p.zoom:
        if inicio <= t:
            nivel = n
        else:
            break
    return nivel * (1 + empurrao(p, t))


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


def editar(entrada: Path, destino: Path, edicao: OpcoesDeEdicao,
           opcoes_saida: saida_mod.OpcoesDeSaida, *, previa_s: float | None = None,
           progresso: Progresso | None = None,
           cancelar: Callable[[], bool] | None = None) -> Resultado:
    """Edita ``entrada`` e grava em ``destino``. Levanta :class:`Cancelado` se pedirem."""
    comeco = time.monotonic()
    avisar = progresso or (lambda etapa, fracao, detalhe: None)
    parar = cancelar or (lambda: False)
    erros = edicao.problemas() + opcoes_saida.problemas()
    if erros:
        raise ValueError("; ".join(erros))
    saida_r = opcoes_saida.resolvidas()
    entrada, destino = Path(entrada), Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    info = video_mod.sondar(entrada)
    duracao = info.duracao if not previa_s else min(info.duracao, previa_s)
    if saida_r.formato == "gif":
        duracao = min(duracao, saida_mod.GIF_MAX_S)

    palavras = obter_palavras(entrada, info, edicao, avisar)
    palavras = [p for p in palavras if p.inicio < duracao]
    if parar():
        raise Cancelado

    avisar("cortando", 0.0, "")
    audio = video_mod.ler_audio(entrada, info.duracao)[: int(duracao * video_mod.TAXA)]
    if edicao.cortes and palavras:
        trechos = cortes.calcular(palavras, audio.mean(axis=1) if len(audio) else None,
                                  video_mod.TAXA, duracao, pausa_maxima=edicao.pausa_maxima)
    else:
        trechos = [cortes.Trecho(0.0, duracao)]
    linha = cortes.Linha(trechos)
    no_editado = linha.palavras(palavras)
    p = plano.montar(no_editado, linha.duracao, vertical=info.vertical, cortes=linha.cortes,
                     opcoes=edicao, nomes_de_icones=set(icones.nomes()))
    p.trechos = [(round(tr.ini, 3), round(tr.fim, 3)) for tr in linha.trechos]
    som_final = montar_audio(audio, linha, p) if info.tem_audio else None
    avisar("cortando", 1.0, f"{len(trechos)} trecho(s), {linha.duracao:.1f} s de "
                            f"{duracao:.1f} s")

    largura, altura = saida_mod.tamanho(info.largura, info.altura, saida_r.resolucao,
                                        saida_r.formato)
    pessoa = None
    if p.movimentos:
        if not recorte.modelo_baixado():
            avisar("desenhando", 0.0, f"baixando o modelo de recorte ({recorte.TAMANHO}), "
                                      "só na primeira vez")
        if recorte.preparar_modelo():
            pessoa = mover.Pessoa(p, largura, altura, fundo=edicao.fundo_da_pessoa,
                                  cor=edicao.cor_do_fundo)
        else:
            # Sem o modelo (sem internet na primeira vez), a edição sai do mesmo jeito,
            # só que com a pessoa parada.
            avisar("desenhando", 0.0, "sem o modelo de recorte: a pessoa fica no lugar")
            p.movimentos = []
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
                                 gravador.indice * passo, pessoa)
                if gravador.indice % 15 == 0:
                    avisar("desenhando", gravador.indice / total_quadros,
                           f"quadro {gravador.indice} de {total_quadros}")
                    if parar():
                        raise Cancelado
        while ultimo is not None and gravador.indice < total_quadros:
            _desenhar_quadro(gravador, ultimo, p, legenda, edicao, largura, altura,
                             gravador.indice * passo, pessoa)
        avisar("finalizando", 0.5, "fechando o arquivo")

    plano_json = destino.with_name(destino.stem + ".plano.json")
    plano_json.write_text(json.dumps(p.para_json(), ensure_ascii=False, indent=1),
                          encoding="utf-8")
    legendas = exportar.gravar(p, destino, com_srt=saida_r.srt, com_vtt=saida_r.vtt)
    avisar("pronto", 1.0, "")
    return Resultado(destino, plano_json, legendas, len(palavras), duracao, linha.duracao,
                     time.monotonic() - comeco, largura, altura)


def _desenhar_quadro(gravador: video_mod.Gravador, matriz: np.ndarray, p: plano.Plano,
                     legenda: Legenda, edicao: OpcoesDeEdicao, largura: int, altura: int,
                     t: float, pessoa: mover.Pessoa | None = None) -> None:
    img = pessoa.quadro(matriz, t, empurrao(p, t)) if pessoa is not None else None
    if img is None:
        img = Image.fromarray(matriz)
        nivel = nivel_de_zoom(p, t)
        caixa = janela(img.width, img.height, nivel, edicao.ancora_x, edicao.ancora_y)
        if nivel > 1.0005 or img.size != (largura, altura):
            img = img.resize((largura, altura), Image.BILINEAR, box=caixa)
    _icones(img, p, t, pessoa.lado_livre(t) if pessoa is not None else 0)
    legenda.desenhar(img, p, t)
    gravador.quadro(np.asarray(img))


__all__ = ["Cancelado", "Resultado", "editar", "empurrao", "janela", "montar_audio",
           "nivel_de_zoom"]
