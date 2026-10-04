"""
O comando ``editar``.

    editar                       abre a interface no navegador
    editar video.mp4             edita direto no terminal
    editar video.mp4 --formato webm --resolucao 720p --sem-cortes
    editar --formatos            o que este computador consegue gravar
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import time
from pathlib import Path

from editor import __version__
from editor import saida as saida_mod
from editor.opcoes import CORES, FUNDOS_DA_PESSOA, OpcoesDeEdicao
from editor.transcricao import MODELOS


def _utf8() -> None:
    """Acentos no console antigo do Windows: sem isto, "transcrição" quebra a saída."""
    for fluxo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            fluxo.reconfigure(encoding="utf-8", errors="replace")


def _ancora(texto: str) -> tuple[float, float]:
    try:
        x, y = (float(v) for v in texto.split(","))
    except ValueError as erro:
        raise argparse.ArgumentTypeError("use x,y entre 0 e 1, por exemplo 0.5,0.4") from erro
    return x, y


class _Formato(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, prefix or "uso: ")


def argumentos() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="editar", formatter_class=_Formato,
        description="Edita vídeos falados no estilo dos Shorts: legenda karaokê, cortes de "
                    "silêncio, zoom, adesivos, ícones e sons. Tudo no seu computador.",
        epilog="Sem nenhum vídeo, abre a interface no navegador.", add_help=False)
    # Os títulos e a ajuda que o argparse escreve em inglês.
    p._positionals.title = "argumento"
    p._optionals.title = "opções"
    p.add_argument("-h", "--ajuda", "--help", action="help", help="mostra esta ajuda e sai")
    p.add_argument("video", nargs="?", type=Path, help="o vídeo a editar")
    p.add_argument("-o", "--saida", type=Path, help="onde gravar (padrão: <nome>-editado.<ext>)")
    g = p.add_argument_group("edição")
    g.add_argument("--sem-cortes", action="store_true", help="não corta os silêncios")
    g.add_argument("--sem-zoom", action="store_true", help="sem zoom de ênfase")
    g.add_argument("--sem-adesivos", action="store_true", help="sem palavras que saltam")
    g.add_argument("--sem-icones", action="store_true", help="sem ícones automáticos")
    g.add_argument("--sem-sons", action="store_true", help="sem efeitos sonoros")
    g.add_argument("--pausa", type=float, default=0.45, help="pausa máxima mantida (s)")
    g.add_argument("--zoom", type=float, default=1.12, help="nível do zoom (1.12 = 12%%)")
    g.add_argument("--ancora", type=_ancora, default=(0.5, 0.40),
                   help="centro do zoom em x,y (padrão 0.5,0.4)")
    g.add_argument("--tamanho-legenda", type=float, default=1.0,
                   help="1.0 padrão, 0.8 menor, 1.25 maior")
    g.add_argument("--mover-pessoa", action="store_true",
                   help="em alguns cortes, a pessoa recortada muda de lugar (mais lento)")
    g.add_argument("--fundo-da-pessoa", default="video", choices=list(FUNDOS_DA_PESSOA),
                   help="o que fica atrás dela: o vídeo desfocado ou uma cor")
    g.add_argument("--cor-do-fundo", default="roxo", choices=list(CORES),
                   help="a cor, com --fundo-da-pessoa cor")
    g.add_argument("--idioma", default="pt", help="idioma da fala (pt, en, es...)")
    g.add_argument("--modelo", default="small", choices=list(MODELOS),
                   help="tamanho do Whisper (padrão small)")
    g.add_argument("--previa", type=float, metavar="SEGUNDOS",
                   help="edita só os primeiros segundos, para testar rápido")
    s = p.add_argument_group("saída")
    s.add_argument("--formato", choices=list(saida_mod.FORMATOS),
                   help="padrão: a extensão do -o, ou mp4")
    s.add_argument("--codec", default="", choices=list(saida_mod.CODECS),
                   help="padrão: o melhor do formato")
    s.add_argument("--resolucao", default="original", choices=list(saida_mod.RESOLUCOES))
    s.add_argument("--fps", default="original", choices=list(saida_mod.FPS))
    s.add_argument("--qualidade", default="alta", choices=list(saida_mod.QUALIDADES))
    s.add_argument("--srt", action="store_true", help="grava também a legenda .srt")
    s.add_argument("--vtt", action="store_true", help="grava também a legenda .vtt")
    i = p.add_argument_group("interface")
    i.add_argument("--porta", type=int, default=0, help="porta da interface (padrão: livre)")
    i.add_argument("--sem-navegador", action="store_true", help="não abre o navegador")
    p.add_argument("--formatos", action="store_true",
                   help="mostra o que este computador consegue gravar")
    p.add_argument("--versao", action="version", version=f"editor-de-video {__version__}",
                   help="mostra a versão e sai")
    return p


class _Barra:
    """O progresso numa linha só do terminal."""

    def __init__(self) -> None:
        self.etapa = ""

    def __call__(self, etapa: str, fracao: float, detalhe: str) -> None:
        if etapa != self.etapa and self.etapa:
            print()
        self.etapa = etapa
        texto = f"  {etapa:<12} {fracao * 100:5.1f}%  {detalhe}"
        print(f"\r{texto[:110]:<110}", end="", flush=True)


def _formato_de(caminho: Path | None) -> str | None:
    if caminho is None:
        return None
    ext = caminho.suffix.lower().lstrip(".")
    return ext if ext in saida_mod.FORMATOS else None


def main(argv: list[str] | None = None) -> int:
    _utf8()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    a = argumentos().parse_args(argv)

    if a.formatos:
        for formato, d in saida_mod.disponiveis().items():
            print(f"{formato:5} vídeo: {', '.join(d['codecs']):24} áudio: "
                  f"{', '.join(d['audios']) or '—'}")
        return 0

    if a.video is None:
        from editor.servidor import abrir

        return abrir(porta=a.porta, navegador=not a.sem_navegador)

    if not a.video.is_file():
        print(f"não achei o vídeo: {a.video}", file=sys.stderr)
        return 2
    edicao = OpcoesDeEdicao(cortes=not a.sem_cortes, zoom=not a.sem_zoom,
                            adesivos=not a.sem_adesivos, icones=not a.sem_icones,
                            sons=not a.sem_sons, pausa_maxima=a.pausa, nivel_zoom=a.zoom,
                            ancora_x=a.ancora[0], ancora_y=a.ancora[1],
                            tamanho_legenda=a.tamanho_legenda, idioma=a.idioma,
                            modelo=a.modelo, mover_pessoa=a.mover_pessoa,
                            fundo_da_pessoa=a.fundo_da_pessoa, cor_do_fundo=a.cor_do_fundo)
    # Sem --formato, vale a extensão do -o: "-o final.mov" grava MOV.
    formato = a.formato or _formato_de(a.saida) or "mp4"
    saida = saida_mod.OpcoesDeSaida(formato=formato, codec=a.codec, resolucao=a.resolucao,
                                    fps=a.fps, qualidade=a.qualidade, srt=a.srt, vtt=a.vtt)
    erros = edicao.problemas() + saida.problemas()
    if erros:
        for e in erros:
            print(f"erro: {e}", file=sys.stderr)
        return 2
    destino = a.saida or a.video.with_name(f"{a.video.stem}-editado.{formato}")

    from editor.render import editar

    print(f"editando {a.video.name} → {destino.name}")
    comeco = time.monotonic()
    r = editar(a.video, destino, edicao, saida, previa_s=a.previa, progresso=_Barra())
    print(f"\n\npronto em {time.monotonic() - comeco:.0f} s: {r.video}")
    print(f"  {r.duracao_original:.1f} s → {r.duracao_final:.1f} s  ·  {r.largura}×{r.altura}"
          f"  ·  {r.palavras} palavras")
    for extra in (r.plano, *r.legendas):
        print(f"  {extra}")
    return 0


__all__ = ["argumentos", "main"]
