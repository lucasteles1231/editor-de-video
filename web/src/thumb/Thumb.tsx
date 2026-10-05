/**
 * A thumbnail: uma composição do Remotion feita inteira em SVG.
 *
 * Inteira em SVG por dois motivos: o mesmo desenho aparece ao vivo no Player do Remotion
 * e vira PNG no próprio navegador (exportar.ts), sem servidor de render e sem nenhuma
 * chamada de rede; e SVG se rasteriza igual no Chrome, no Edge, no Firefox e no Safari.
 *
 * O que ela desenha é uma ficha (ThumbProps), preenchida pelos controles da página ou pelo
 * Gemini, em camadas: fundo → luz → pessoa → mão → texto, selo e ícone. As regras de arte
 * vêm da pesquisa do Stickman (publish/miniatura.py): no máximo três elementos chamando
 * atenção, o rosto grande, algo apontando, de 2 a 5 palavras grossas com contorno, legível
 * a 120 px.
 *
 * A geometria fica em ``compor()``, uma função pura: o desenho e o arrastar na prévia
 * usam a mesma conta, e o que a pessoa arrasta é o que sai no PNG.
 */
import React from 'react';
import {AbsoluteFill} from 'remotion';
import rough from 'roughjs';
import type {Caixa, Cor, Fundo, Lado, Luz, Modelo} from '../tipos';
import {ADESIVO_FOLGA_X, ADESIVO_FOLGA_Y, ADESIVO_GIRO, FAMILIA, TITULO, comoAparece, diagramar, medir, tinta} from './medida';

export type ThumbProps = {
  largura: number;
  altura: number;
  /** O quadro da pessoa (URL ou data URL) e a proporção dele (largura / altura). */
  quadro: string;
  aspecto: number;
  /** A pessoa recortada, um PNG com transparência ('' sem recorte), e onde ela está. */
  recorte: string;
  pessoa: Caixa | null;
  rosto: Caixa | null;
  // ── o fundo atrás da pessoa recortada ──
  fundo: Fundo;
  /** A imagem do fundo: o quadro do conteúdo ou a imagem escolhida ('' sem). */
  fundoImagem: string;
  fundoAspecto: number;
  /** O fundo é o próprio quadro da pessoa (o "desfocado"): centra no rosto. */
  fundoDoProprioQuadro: boolean;
  foco: Caixa | null;
  desfoque: number;
  escurecer: number;
  vinheta: boolean;
  tom: boolean;
  // ── a pessoa ──
  lado: Lado;
  pessoaDx: number;
  pessoaDy: number;
  pessoaEscala: number;
  espelhar: boolean;
  contorno: boolean;
  luz: Luz;
  realce: boolean;
  // ── a mão ──
  /** A imagem da mão apontando ('' sem mão). */
  mao: string;
  maoAlvo: 'titulo' | 'alvo';
  maoX: number | null;
  maoY: number | null;
  maoEscala: number;
  // ── o texto e o resto ──
  texto: string;
  destaque: number;
  modelo: Modelo;
  cor: Cor;
  selo: string;
  numero: string;
  /** Os caminhos SVG do ícone (Tabler, caixa de 24); vazio, sem ícone. */
  icone: string[];
  /** O ícone de aviso da faixa do modelo alerta. */
  iconeAlerta: string[];
  seta: boolean;
  alvo: Caixa | null;
  /** As fontes (URL ou data URL): a da chamada e a do resto. */
  fonteTitulo: string;
  fonteTexto: string;
  /** A faixa da capa em pé que aparece em todas as plataformas marcadas (frações da
   *  altura): o perfil do TikTok e do Instagram mostra só o meio em 3:4, e a busca do
   *  YouTube, o meio da capa do Short em 3:2. A chamada e o selo ficam dentro dela; o
   *  rosto, dentro de ``rosto`` (a busca do YouTube só exige o texto). Sem ela, a capa
   *  inteira. */
  seguro?: {y0: number; y1: number; rosto?: {y0: number; y1: number}};
};

/** Quanto da largura do quadro da pessoa some aos poucos, num lado em que ela vinha
 * cortada; e quanto da altura, em cima. */
const SOME_DO_LADO = 0.2;
const SOME_EM_CIMA = 0.06;

const TINTA = '#1A1A1A';
const BRANCO = '#FFFFFF';
const BALAO = '#FFEC96';

/** A paleta fechada: todas aguentam o contorno preto em qualquer foto. */
export const PALETA: Record<Cor, string> = {
  amarelo: '#FFD400', rosa: '#FF3D7F', ciano: '#00C2FF', lima: '#9BE15D',
  laranja: '#FF7A00', roxo: '#B36BFF', vermelho: '#FF2D2D',
};

export type Retangulo = {x: number; y: number; w: number; h: number};
type Alvo = {cx: number; cy: number; altura: number};
type Formato = 'paisagem' | 'retrato' | 'quadrado';
type Posicao = {x: number; y: number; w: number; h: number};

const limitar = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

function misturar(hex: string, com: string, fracao: number): string {
  const a = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const b = [1, 3, 5].map((i) => parseInt(com.slice(i, i + 2), 16));
  return `#${a.map((v, i) => Math.round(v + (b[i] - v) * fracao).toString(16).padStart(2, '0')).join('')}`;
}

function formatoDe(W: number, H: number): Formato {
  return W / H > 1.2 ? 'paisagem' : W / H < 0.8 ? 'retrato' : 'quadrado';
}

/** Onde vai o texto, onde fica o rosto e onde fica a faixa do alerta, por formato. Em pé,
 *  tudo fica dentro da faixa ``seguro``. */
function planta(W: number, H: number, f: Formato, lado: Lado, faixa: boolean, selo: number,
                seguro: {y0: number; y1: number; rosto?: {y0: number; y1: number}} = {y0: 0, y1: 1}) {
  const m = Math.min(W, H) * 0.055;
  if (f === 'paisagem') {
    const alturaDaFaixa = faixa ? H * 0.17 : selo;
    const coluna = W * 0.54;
    const texto = {x: lado === 'esquerda' ? m : W - coluna, y: m + alturaDaFaixa, w: coluna - m,
      h: H - 2 * m - alturaDaFaixa};
    const rosto: Alvo = {cx: lado === 'esquerda' ? W * 0.76 : W * 0.24, cy: H * (faixa ? 0.47 : 0.4),
      altura: H * 0.42};
    return {m, texto, rosto, faixa: faixa ? {x: -m, y: m * 0.4, w: W + 2 * m, h: alturaDaFaixa} : null};
  }
  const alturaDaFaixa = faixa ? H * (f === 'retrato' ? 0.09 : 0.13) : selo;
  const topo = seguro.y0 * H;
  const fundo = seguro.y1 * H;
  const fundoDoRosto = (seguro.rosto ?? seguro).y1 * H;
  const texto = {x: m, y: topo + m + alturaDaFaixa, w: W - 2 * m, h: H * (f === 'retrato' ? 0.33 : 0.36)};
  const rosto: Alvo = f === 'retrato'
    ? {cx: W * 0.5, cy: H * 0.6, altura: H * 0.24}
    : {cx: W * 0.5, cy: H * 0.66, altura: H * 0.3};
  if (fundo - topo < H * 0.999 || fundoDoRosto < H * 0.999) {
    // Com recorte, a chamada fica com até 55% do que sobra da faixa dela, e o rosto vem
    // logo abaixo. A caixa do rosto é a cabeça medida na silhueta, do cabelo até perto
    // dos olhos: o queixo fica uns 60% dela mais abaixo, e também tem de caber (no teste
    // com a faixa do alerta, ele encostava no corte do feed do Instagram).
    texto.h = Math.min(texto.h, (fundo - texto.y) * 0.55);
    const baseDoTexto = texto.y + texto.h;
    rosto.altura = Math.max(H * 0.1, Math.min(rosto.altura, (fundoDoRosto - baseDoTexto) / 1.7));
    rosto.cy = Math.min(Math.max(rosto.cy, baseDoTexto + rosto.altura * 0.55), fundoDoRosto - rosto.altura * 1.1);
  }
  return {m, texto, rosto, faixa: faixa ? {x: -m, y: topo + m * 0.4, w: W + 2 * m, h: alturaDaFaixa} : null};
}

/** O rosto quando ninguém disse onde ele está: o terço de cima, no meio. */
function rostoPadrao(aspecto: number): Caixa {
  return aspecto < 1 ? {x0: 0.3, y0: 0.12, x1: 0.7, y1: 0.3} : {x0: 0.38, y0: 0.15, x1: 0.62, y1: 0.45};
}

/** O quadro inteiro, com o rosto no alvo: nunca deixa vão em cima nem embaixo. */
function posicionarQuadro(W: number, H: number, aspecto: number, rosto: Caixa, alvo: Alvo,
                          cobrir: boolean): Posicao {
  let s = Math.max(alvo.altura / Math.max(0.03, rosto.y1 - rosto.y0), H);
  if (cobrir) s = Math.max(s, W / aspecto);
  const w = aspecto * s;
  const fcx = ((rosto.x0 + rosto.x1) / 2) * aspecto;
  const fcy = (rosto.y0 + rosto.y1) / 2;
  const y = limitar(alvo.cy - fcy * s, H - s, 0);
  const x = w >= W ? limitar(alvo.cx - fcx * s, W - w, 0) : limitar(alvo.cx - fcx * s, 0, W - w);
  return {x, y, w, h: s};
}

/** Uma imagem de conteúdo cobrindo a thumbnail, com a região do foco no meio e grande. */
function posicionarConteudo(W: number, H: number, aspecto: number, foco: Caixa | null): Posicao {
  let s = Math.max(H, W / aspecto);
  let cx = 0.5;
  let cy = 0.5;
  if (foco) {
    const fw = Math.max(0.05, foco.x1 - foco.x0) * aspecto;
    const fh = Math.max(0.05, foco.y1 - foco.y0);
    s = Math.max(s, Math.min(W / fw, H / fh) * 0.85);
    cx = (foco.x0 + foco.x1) / 2;
    cy = (foco.y0 + foco.y1) / 2;
  }
  const w = aspecto * s;
  return {x: limitar(W / 2 - cx * w, W - w, 0), y: limitar(H / 2 - cy * s, H - s, 0), w, h: s};
}

/** Uma caixa do quadro (frações) no espaço da thumbnail, com o quadro em ``p``. */
function naThumb(c: Caixa, p: Posicao): Retangulo {
  return {x: p.x + c.x0 * p.w, y: p.y + c.y0 * p.h, w: (c.x1 - c.x0) * p.w, h: (c.y1 - c.y0) * p.h};
}

export type Mao = {cx: number; cy: number; lado: number; angulo: number; espelhada: boolean};

/** Toda a geometria da thumbnail, sem desenhar nada. */
export function compor(p: ThumbProps) {
  const {largura: W, altura: H} = p;
  const f = formatoDe(W, H);
  const curto = Math.min(W, H);
  const comRecorte = Boolean(p.recorte && p.pessoa);
  const seloPx = curto * 0.075;
  const selo = p.selo && p.modelo !== 'alerta' ? comoAparece(p.selo) : '';
  const seguro = f === 'paisagem' ? {y0: 0, y1: 1} : p.seguro ?? {y0: 0, y1: 1};
  const {m, texto: area, rosto: alvoDoRosto, faixa} = planta(W, H, f, p.lado, p.modelo === 'alerta',
    selo ? seloPx * 1.9 : 0, seguro);
  const seloY = seguro.y0 * H + m;
  const rosto = p.rosto ?? rostoPadrao(p.aspecto);

  // A pessoa sem recorte é o próprio quadro, com o rosto no alvo.
  const quadro = posicionarQuadro(W, H, p.aspecto, rosto, alvoDoRosto, false);
  const fundoCobrindo = posicionarQuadro(W, H, p.aspecto, rosto, alvoDoRosto, true);
  const sobra = !comRecorte && quadro.w < W - 1;

  // O fundo atrás da pessoa recortada.
  const fundoPos = comRecorte && p.fundo !== 'cor' && p.fundoImagem
    ? (p.fundoDoProprioQuadro ? fundoCobrindo : posicionarConteudo(W, H, p.fundoAspecto, p.foco))
    : null;

  // A pessoa recortada: o rosto no alvo; depois o tamanho escolhido (em volta do rosto), o
  // busto chegando de novo à borda de baixo e o deslocamento escolhido.
  let pessoa: Posicao | null = null;
  if (comRecorte) {
    const s = alvoDoRosto.altura / Math.max(0.03, rosto.y1 - rosto.y0) * p.pessoaEscala;
    const w = p.aspecto * s;
    let x = alvoDoRosto.cx - ((rosto.x0 + rosto.x1) / 2) * w;
    let y = alvoDoRosto.cy - ((rosto.y0 + rosto.y1) / 2) * s;
    const base = p.pessoa ? p.pessoa.y1 : 1;
    if (y + base * s < H) y = H - base * s;
    x += p.pessoaDx * W;
    y += p.pessoaDy * H;
    pessoa = {x, y, w, h: s};
  }
  const caixaDaPessoa: Retangulo = pessoa && p.pessoa ? naThumb(p.pessoa, pessoa) : naThumb(rosto, quadro);
  // Onde a pessoa já vinha cortada pela borda do quadro original (o braço num vídeo em pé, o
  // cabelo encostado em cima), ela some aos poucos. Numa thumbnail deitada essa borda cai no
  // meio da imagem, e uma reta atravessando o ombro denunciava o recorte (visto no teste
  // real de 03/10/2026).
  const cortada = comRecorte && p.pessoa
    ? {esquerda: p.espelhar ? p.pessoa.x1 >= 0.995 : p.pessoa.x0 <= 0.005,
      direita: p.espelhar ? p.pessoa.x0 <= 0.005 : p.pessoa.x1 >= 0.995,
      topo: p.pessoa.y0 <= 0.005}
    : {esquerda: false, direita: false, topo: false};
  const posDoRosto = pessoa ?? quadro;
  const centroDoRosto = {x: posDoRosto.x + ((rosto.x0 + rosto.x1) / 2) * posDoRosto.w,
    y: posDoRosto.y + ((rosto.y0 + rosto.y1) / 2) * posDoRosto.h};

  // ── o texto ──
  const corpoMaximo = f === 'paisagem' ? H * 0.2 : W * 0.15;
  let numeroPx = 0;
  let numeroAltura = 0;
  if (p.modelo === 'numero' && p.numero) {
    const n = comoAparece(p.numero);
    const tetoPorLargura = (area.w * 0.95) / Math.max(1, medir(n, 100, TITULO) / 100);
    numeroPx = Math.min(area.h * 0.62 / 0.82, tetoPorLargura, f === 'paisagem' ? H * 0.5 : W * 0.5);
    const t = tinta(n, numeroPx, TITULO);
    numeroAltura = t.sobe + t.desce + numeroPx * 0.08;
  }
  const d = diagramar(p.texto, p.modelo === 'numero' ? -1 : p.destaque, area.w, area.h - numeroAltura,
    p.modelo === 'numero' ? corpoMaximo * 0.6 : corpoMaximo, {maxLinhas: p.modelo === 'numero' ? 2 : 3});
  const topoDoBloco = area.y + (area.h - numeroAltura - d.altura) / 2;
  const alinhar = f !== 'paisagem' ? 'centro' : p.lado === 'esquerda' ? 'esquerda' : 'direita';
  const xDaLinha = (larguraDaLinha: number) =>
    alinhar === 'centro' ? area.x + (area.w - larguraDaLinha) / 2
      : alinhar === 'esquerda' ? area.x : area.x + area.w - larguraDaLinha;
  const postas: {chave: string; texto: string; x: number; baseY: number; largura: number; destaque: boolean}[] = [];
  let y = topoDoBloco + numeroAltura;
  let esquerdaDoTexto = Infinity;
  let direitaDoTexto = -Infinity;
  d.linhas.forEach((linha, k) => {
    const x0 = xDaLinha(linha.largura);
    esquerdaDoTexto = Math.min(esquerdaDoTexto, x0);
    direitaDoTexto = Math.max(direitaDoTexto, x0 + linha.largura);
    for (const w of linha.palavras) {
      postas.push({chave: `${k}-${w.indice}`, texto: w.texto, x: x0 + w.x, baseY: y + linha.base,
        largura: w.largura, destaque: w.indice === p.destaque && p.modelo !== 'numero'});
    }
    y += linha.altura;
  });
  if (!Number.isFinite(esquerdaDoTexto)) {
    esquerdaDoTexto = area.x;
    direitaDoTexto = area.x + area.w;
  }
  const blocoDeTexto: Retangulo = {x: esquerdaDoTexto, y: topoDoBloco, w: direitaDoTexto - esquerdaDoTexto,
    h: Math.max(1, y - topoDoBloco)};

  // ── a seta e o alvo ──
  const ondeEstaOAlvo = p.alvo ? naThumb(p.alvo, pessoa ?? quadro) : null;

  // ── a mão: entre a pessoa e o título, com o dedo virado para o alvo ──
  let mao: Mao | null = null;
  if (p.mao) {
    const lado = curto * 0.27 * p.maoEscala;
    const alvo = p.maoAlvo === 'alvo' && ondeEstaOAlvo
      ? {x: ondeEstaOAlvo.x + ondeEstaOAlvo.w / 2, y: ondeEstaOAlvo.y + ondeEstaOAlvo.h / 2}
      : {x: blocoDeTexto.x + blocoDeTexto.w / 2, y: blocoDeTexto.y + blocoDeTexto.h / 2};
    let cx: number;
    let cy: number;
    if (p.maoX !== null && p.maoY !== null) {
      cx = p.maoX * W;
      cy = p.maoY * H;
    } else if (p.maoAlvo === 'alvo' && ondeEstaOAlvo) {
      const dePerto = p.lado === 'esquerda' ? -1 : 1;
      cx = limitar(alvo.x + dePerto * (ondeEstaOAlvo.w / 2 + lado * 0.6), lado / 2, W - lado / 2);
      cy = limitar(alvo.y + lado * 0.35, lado / 2, H - lado / 2);
    } else if (f === 'paisagem') {
      // Ao lado do texto e quase na altura do meio dele: o dedo aponta quase na
      // horizontal. Embaixo do texto, a mão apontava em diagonal e lia torta.
      const borda = p.lado === 'esquerda' ? blocoDeTexto.x + blocoDeTexto.w : blocoDeTexto.x;
      cx = limitar(borda + (p.lado === 'esquerda' ? 1 : -1) * lado * 0.6, lado / 2, W - lado / 2);
      cy = limitar(blocoDeTexto.y + blocoDeTexto.h * 0.62, lado / 2, H - lado / 2 - m * 0.4);
    } else {
      // Em pé e quadrada, embaixo do texto há dois lugares: o "?" da pergunta fica com o
      // da direita, e a mão vai para o outro.
      const direita = p.modelo === 'pergunta' ? p.lado === 'direita' : p.lado !== 'direita';
      cx = direita ? W * 0.8 : W * 0.2;
      cy = limitar(area.y + area.h + lado * 0.6, lado / 2, H - lado / 2);
    }
    const angulo = Math.atan2(alvo.y - cy, alvo.x - cx);
    mao = {cx, cy, lado, angulo, espelhada: Math.cos(angulo) < 0};
  }

  return {W, H, f, m, curto, comRecorte, seloPx, selo, seloY, area, faixa, alvoDoRosto, rosto, quadro,
    fundoCobrindo, sobra, fundoPos, pessoa, caixaDaPessoa, cortada, centroDoRosto, numeroPx, d, topoDoBloco,
    alinhar, postas, blocoDeTexto, ondeEstaOAlvo, mao};
}

export type Cena = ReturnType<typeof compor>;

function TextoComContorno(props: {x: number; y: number; px: number; texto: string; familia: string;
  cor?: string; contorno?: number; ancora?: 'start' | 'middle' | 'end'}) {
  const {x, y, px, texto, familia, cor = BRANCO, contorno = 0.14, ancora = 'start'} = props;
  return (
    <text x={x} y={y} fontFamily={familia} fontWeight={familia === TITULO ? 400 : 700} fontSize={px}
      fill={cor} stroke={TINTA} strokeWidth={px * contorno} strokeLinejoin="round" paintOrder="stroke"
      textAnchor={ancora}>{texto}</text>
  );
}

function Icone({caminhos, cx, cy, lado, traco}: {caminhos: string[]; cx: number; cy: number; lado: number; traco: number}) {
  return (
    <g transform={`translate(${cx - lado / 2} ${cy - lado / 2}) scale(${lado / 24})`} fill="none" stroke={TINTA}
      strokeWidth={traco} strokeLinecap="round" strokeLinejoin="round">
      {caminhos.map((d, i) => <path key={i} d={d} />)}
    </g>
  );
}

/** Traço de caneta (roughjs, semente fixa: a prévia e o PNG saem iguais), em duas camadas:
 *  preto largo por baixo e a cor por cima, para ler sobre qualquer fundo. */
function Rabisco({desenhos, cor, largura}: {desenhos: ReturnType<ReturnType<typeof rough.generator>['line']>[];
  cor: string; largura: number}) {
  const gerador = rough.generator();
  const caminhos = desenhos.flatMap((d) => gerador.toPaths(d).map((p) => p.d));
  return (
    <g fill="none" strokeLinecap="round" strokeLinejoin="round">
      {caminhos.map((d, i) => <path key={`p${i}`} d={d} stroke={TINTA} strokeWidth={largura * 2.2} />)}
      {caminhos.map((d, i) => <path key={`c${i}`} d={d} stroke={cor} strokeWidth={largura} />)}
    </g>
  );
}

export const Thumb: React.FC<ThumbProps> = (p) => {
  const id = React.useId().replace(/[^a-zA-Z0-9]/g, '');
  const c = compor(p);
  const {W, H, f, m, curto, comRecorte, seloPx, selo, seloY, area, faixa, quadro, fundoCobrindo, sobra, fundoPos,
    pessoa, cortada, centroDoRosto, d, alinhar} = c;
  const someDosLados = Boolean(pessoa && (cortada.esquerda || cortada.direita));
  const someEmCima = Boolean(pessoa && cortada.topo);
  const destaqueCor = PALETA[p.cor];
  const corDoAdesivo = comRecorte && p.fundo === 'cor' ? BRANCO : destaqueCor;
  const raio = curto * 0.012;
  const temFundoDeImagem = !comRecorte || p.fundo !== 'cor';

  // ── a seta e o círculo ──
  const gerador = rough.generator();
  const traco = curto * 0.012;
  const rabiscos = [];
  if (p.seta && c.ondeEstaOAlvo) {
    const a = c.ondeEstaOAlvo;
    const folga = 0.18;
    rabiscos.push(gerador.ellipse(a.x + a.w / 2, a.y + a.h / 2, a.w * (1 + folga * 2), a.h * (1 + folga * 2),
      {roughness: 1.4, bowing: 1, seed: 11, strokeWidth: traco}));
    const fimX = a.x + a.w / 2 + (p.lado === 'esquerda' ? -1 : 1) * a.w * (0.5 + folga);
    const fimY = a.y + a.h / 2;
    const comecoX = f === 'paisagem' ? (p.lado === 'esquerda' ? area.x + area.w * 0.95 : area.x + area.w * 0.05)
      : W * 0.18;
    const comecoY = f === 'paisagem' ? limitar(fimY + H * 0.22, H * 0.25, H - m * 2) : area.y + area.h + m;
    const curvaX = (comecoX + fimX) / 2;
    const curvaY = Math.max(comecoY, fimY) + H * 0.08;
    rabiscos.push(gerador.path(`M ${comecoX} ${comecoY} Q ${curvaX} ${curvaY} ${fimX} ${fimY}`,
      {roughness: 1.2, bowing: 0.8, seed: 7, strokeWidth: traco}));
    const angulo = Math.atan2(fimY - curvaY, fimX - curvaX);
    const ponta = curto * 0.05;
    for (const lado of [-1, 1]) {
      const ang = angulo + Math.PI + lado * 0.5;
      rabiscos.push(gerador.line(fimX, fimY, fimX + Math.cos(ang) * ponta, fimY + Math.sin(ang) * ponta,
        {roughness: 1, seed: 13 + lado, strokeWidth: traco}));
    }
  }

  // ── o ícone, o "?" e o selo ──
  // Os balões ficam do lado da pessoa, longe do texto: o "?" da pergunta no canto de baixo
  // (ou ao lado da cabeça, em pé); o ícone vai para o canto de cima se dividir o lugar
  // com o "?" ou com a mão.
  const raioDoIcone = curto * 0.115;
  const raioDaPergunta = curto * 0.14;
  const ladoDaPessoaX = (r: number) => (f !== 'paisagem' || p.lado === 'esquerda' ? W - r - m : r + m);
  const pergunta = p.modelo === 'pergunta'
    ? {cx: ladoDaPessoaX(raioDaPergunta),
      cy: f === 'paisagem' ? H - raioDaPergunta - m : area.y + area.h + raioDaPergunta + m * 0.5}
    : null;
  // Em pé e quadrada: se o "?" e a mão já ocupam os dois lugares, o ícone desce.
  const lugaresTomados = f !== 'paisagem' && pergunta && p.mao;
  const icone = p.icone.length
    ? pergunta || p.mao
      ? {cx: f === 'paisagem' ? ladoDaPessoaX(raioDoIcone) : lugaresTomados ? W - raioDoIcone - m : raioDoIcone + m,
        cy: f === 'paisagem' ? raioDoIcone + m
          : area.y + area.h + raioDoIcone + m * 0.5 + (lugaresTomados ? raioDaPergunta * 2.4 : 0)}
      : {cx: ladoDaPessoaX(raioDoIcone),
        cy: f === 'paisagem' ? H - raioDoIcone - m : area.y + area.h + raioDoIcone + m * 0.5}
    : null;
  const seloLargura = selo ? medir(selo, seloPx, TITULO) + seloPx * 0.9 : 0;
  const seloX = f === 'paisagem' && p.lado === 'direita' ? W - m - seloLargura : m;

  const gradiente = f === 'paisagem'
    ? (p.lado === 'esquerda' ? {x1: '0', y1: '0', x2: '1', y2: '0'} : {x1: '1', y1: '0', x2: '0', y2: '0'})
    : {x1: '0', y1: '0', x2: '0', y2: '1'};
  const luzX = centroDoRosto.x / W;
  const luzY = centroDoRosto.y / H;
  const desfoque = p.desfoque * curto * 0.035;
  const corDaLuz = p.fundo === 'cor' && comRecorte ? BRANCO : destaqueCor;

  // Os raios de luz atrás da pessoa: fatias saindo do rosto, uma sim, uma não.
  const raios = comRecorte && p.luz === 'raios'
    ? Array.from({length: 16}, (_, i) => {
      const a0 = (i / 16) * Math.PI * 2;
      const a1 = a0 + Math.PI / 16;
      const r = Math.hypot(W, H);
      return `M ${centroDoRosto.x} ${centroDoRosto.y} L ${centroDoRosto.x + Math.cos(a0) * r} `
        + `${centroDoRosto.y + Math.sin(a0) * r} L ${centroDoRosto.x + Math.cos(a1) * r} `
        + `${centroDoRosto.y + Math.sin(a1) * r} Z`;
    })
    : [];

  const maoTransform = c.mao
    ? `translate(${c.mao.cx} ${c.mao.cy}) rotate(${((c.mao.espelhada ? c.mao.angulo - Math.PI : c.mao.angulo) * 180) / Math.PI})`
      + (c.mao.espelhada ? ' scale(-1 1)' : '')
    : '';

  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <style>{`@font-face{font-family:'${TITULO}';font-weight:400;src:url(${p.fonteTitulo}) format('truetype');}`
          + `@font-face{font-family:'${FAMILIA}';font-weight:700;src:url(${p.fonteTexto}) format('truetype');}`}</style>
        <linearGradient id={`${id}escuro`} {...gradiente}>
          <stop offset="0" stopColor="#000" stopOpacity={0.88 * p.escurecer} />
          <stop offset="0.5" stopColor="#000" stopOpacity={0.4 * p.escurecer} />
          <stop offset="0.85" stopColor="#000" stopOpacity={0} />
        </linearGradient>
        <radialGradient id={`${id}cor`} cx={luzX} cy={luzY} r="0.9">
          <stop offset="0" stopColor={misturar(destaqueCor, BRANCO, 0.25)} />
          <stop offset="0.55" stopColor={destaqueCor} />
          <stop offset="1" stopColor={misturar(destaqueCor, '#000000', 0.45)} />
        </radialGradient>
        <radialGradient id={`${id}vinheta`} cx="0.5" cy="0.5" r="0.75">
          <stop offset="0.55" stopColor="#000" stopOpacity={0} />
          <stop offset="1" stopColor="#000" stopOpacity={0.62} />
        </radialGradient>
        <radialGradient id={`${id}halo`} cx={luzX} cy={luzY} r="0.45">
          <stop offset="0" stopColor={misturar(corDaLuz, BRANCO, 0.35)} stopOpacity={0.95} />
          <stop offset="0.45" stopColor={corDaLuz} stopOpacity={0.55} />
          <stop offset="1" stopColor={corDaLuz} stopOpacity={0} />
        </radialGradient>
        <radialGradient id={`${id}raios`} cx={luzX} cy={luzY} r="0.8">
          <stop offset="0.1" stopColor={corDaLuz} stopOpacity={0.55} />
          <stop offset="1" stopColor={corDaLuz} stopOpacity={0} />
        </radialGradient>
        <filter id={`${id}borrao`} x="0" y="0" width="100%" height="100%">
          <feGaussianBlur stdDeviation={Math.max(desfoque, 0.01)} edgeMode="duplicate" />
        </filter>
        <filter id={`${id}enchimento`} x="0" y="0" width="100%" height="100%">
          <feGaussianBlur stdDeviation={curto * 0.02} edgeMode="duplicate" />
        </filter>
        {/* A pessoa: o realce (contraste e saturação), a luz colorida na borda dela, o
            contorno branco e a sombra — cada um só se estiver ligado. */}
        <filter id={`${id}pessoa`} x="-20%" y="-20%" width="140%" height="140%" colorInterpolationFilters="sRGB">
          {p.realce ? (
            <>
              <feColorMatrix in="SourceGraphic" type="saturate" values="1.3" result="saturada" />
              <feComponentTransfer in="saturada" result="corpo">
                <feFuncR type="linear" slope={1.12} intercept={-0.05} />
                <feFuncG type="linear" slope={1.12} intercept={-0.05} />
                <feFuncB type="linear" slope={1.12} intercept={-0.05} />
              </feComponentTransfer>
            </>
          ) : (
            <feOffset in="SourceGraphic" dx={0} dy={0} result="corpo" />
          )}
          <feComponentTransfer in="SourceAlpha" result="duro">
            <feFuncA type="linear" slope={6} intercept={-2.4} />
          </feComponentTransfer>
          <feMorphology in="duro" operator="dilate" radius={p.contorno ? raio : raio * 0.2} result="grosso" />
          <feFlood floodColor={BRANCO} result="branco" />
          <feComposite in="branco" in2="grosso" operator="in" result="borda" />
          <feGaussianBlur in="grosso" stdDeviation={raio * 1.2} result="borrado" />
          <feOffset in="borrado" dx={raio * 0.8} dy={raio} result="deslocado" />
          <feFlood floodColor="#000" floodOpacity={0.45} result="preto" />
          <feComposite in="preto" in2="deslocado" operator="in" result="sombra" />
          {p.luz === 'contorno' ? (
            <>
              {/* a luz de borda: um aro por dentro da silhueta, na cor, como luz batendo */}
              <feMorphology in="duro" operator="erode" radius={raio * 1.4} result="miolo" />
              <feComposite in="duro" in2="miolo" operator="out" result="aro" />
              <feGaussianBlur in="aro" stdDeviation={raio * 0.9} result="aroSuave" />
              <feFlood floodColor={corDaLuz} floodOpacity={0.9} result="tinta" />
              <feComposite in="tinta" in2="aroSuave" operator="in" result="aroColorido" />
              <feComposite in="aroColorido" in2="duro" operator="in" result="aroDentro" />
              {/* e um brilho por fora, da mesma cor */}
              <feMorphology in="duro" operator="dilate" radius={raio * 0.8} result="largo" />
              <feGaussianBlur in="largo" stdDeviation={raio * 2.4} result="largoSuave" />
              <feComposite in="tinta" in2="largoSuave" operator="in" result="brilho" />
            </>
          ) : null}
          <feMerge>
            <feMergeNode in="sombra" />
            {p.luz === 'contorno' ? <feMergeNode in="brilho" /> : null}
            {p.contorno ? <feMergeNode in="borda" /> : null}
            <feMergeNode in="corpo" />
            {p.luz === 'contorno' ? <feMergeNode in="aroDentro" /> : null}
          </feMerge>
        </filter>
        {/* A mão: contorno branco e sombra, como um adesivo. */}
        <filter id={`${id}mao`} x="-25%" y="-25%" width="150%" height="150%" colorInterpolationFilters="sRGB">
          <feMorphology in="SourceAlpha" operator="dilate" radius={raio * 0.9} result="grosso" />
          <feFlood floodColor={BRANCO} result="branco" />
          <feComposite in="branco" in2="grosso" operator="in" result="borda" />
          <feGaussianBlur in="grosso" stdDeviation={raio} result="borrado" />
          <feOffset in="borrado" dx={raio * 0.7} dy={raio} result="deslocado" />
          <feFlood floodColor="#000" floodOpacity={0.4} result="preto" />
          <feComposite in="preto" in2="deslocado" operator="in" result="sombra" />
          <feMerge>
            <feMergeNode in="sombra" />
            <feMergeNode in="borda" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <linearGradient id={`${id}bordaGrad`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity={0} />
          <stop offset="0.1" stopColor="#fff" stopOpacity={1} />
          <stop offset="0.9" stopColor="#fff" stopOpacity={1} />
          <stop offset="1" stopColor="#fff" stopOpacity={0} />
        </linearGradient>
        {pessoa ? (
          <clipPath id={`${id}corte`}>
            <rect x={pessoa.x} y={pessoa.y} width={pessoa.w} height={H * 4} />
          </clipPath>
        ) : null}
        {pessoa && someDosLados ? (
          <>
            <linearGradient id={`${id}someX`} gradientUnits="userSpaceOnUse" x1={pessoa.x} y1={0}
              x2={pessoa.x + pessoa.w} y2={0}>
              <stop offset={0} stopColor="#fff" stopOpacity={cortada.esquerda ? 0 : 1} />
              <stop offset={SOME_DO_LADO} stopColor="#fff" stopOpacity={1} />
              <stop offset={1 - SOME_DO_LADO} stopColor="#fff" stopOpacity={1} />
              <stop offset={1} stopColor="#fff" stopOpacity={cortada.direita ? 0 : 1} />
            </linearGradient>
            <mask id={`${id}someLados`} maskUnits="userSpaceOnUse" x={0} y={0} width={W} height={H}>
              <rect width={W} height={H} fill={`url(#${id}someX)`} />
            </mask>
          </>
        ) : null}
        {pessoa && someEmCima ? (
          <>
            <linearGradient id={`${id}someY`} gradientUnits="userSpaceOnUse" x1={0} y1={pessoa.y}
              x2={0} y2={pessoa.y + pessoa.h * SOME_EM_CIMA}>
              <stop offset={0} stopColor="#fff" stopOpacity={0} />
              <stop offset={1} stopColor="#fff" stopOpacity={1} />
            </linearGradient>
            <mask id={`${id}someTopo`} maskUnits="userSpaceOnUse" x={0} y={0} width={W} height={H}>
              <rect width={W} height={H} fill={`url(#${id}someY)`} />
            </mask>
          </>
        ) : null}
        <mask id={`${id}bordas`} maskUnits="userSpaceOnUse" x={quadro.x} y={quadro.y} width={quadro.w} height={quadro.h}>
          <rect x={quadro.x} y={quadro.y} width={quadro.w} height={quadro.h} fill={`url(#${id}bordaGrad)`} />
        </mask>
      </defs>

      {/* ── o fundo ── */}
      <rect width={W} height={H} fill={TINTA} />
      {comRecorte && p.fundo === 'cor' ? <rect width={W} height={H} fill={`url(#${id}cor)`} /> : null}
      {fundoPos ? (
        <g filter={desfoque > 0.5 ? `url(#${id}borrao)` : undefined}>
          <image href={p.fundoImagem} x={fundoPos.x} y={fundoPos.y} width={fundoPos.w} height={fundoPos.h}
            preserveAspectRatio="none" />
        </g>
      ) : null}
      {/* Sem recorte, a pessoa é o próprio quadro e fica nítida; o desfocado só preenche o
          que o quadro não cobre (um vídeo em pé numa thumbnail deitada). */}
      {!comRecorte && p.quadro && sobra ? (
        <g filter={`url(#${id}enchimento)`}>
          <image href={p.quadro} x={fundoCobrindo.x} y={fundoCobrindo.y} width={fundoCobrindo.w}
            height={fundoCobrindo.h} preserveAspectRatio="none" />
        </g>
      ) : null}
      {!comRecorte && p.quadro ? (
        <image href={p.quadro} x={quadro.x} y={quadro.y} width={quadro.w} height={quadro.h}
          preserveAspectRatio="none" mask={sobra ? `url(#${id}bordas)` : undefined} />
      ) : null}
      {temFundoDeImagem && p.tom ? <rect width={W} height={H} fill={destaqueCor} opacity={0.22} /> : null}
      {temFundoDeImagem ? <rect width={W} height={H} fill={`url(#${id}escuro)`} /> : null}
      {p.vinheta ? <rect width={W} height={H} fill={`url(#${id}vinheta)`} /> : null}

      {/* ── a luz atrás da pessoa ── */}
      {raios.length ? (
        <g fill={`url(#${id}raios)`}>
          {raios.map((r, i) => <path key={i} d={r} />)}
        </g>
      ) : null}
      {comRecorte && p.luz === 'halo' ? <rect width={W} height={H} fill={`url(#${id}halo)`} /> : null}

      {/* ── a pessoa recortada ── O contorno fica preso à área do quadro original: onde a
          pessoa já vinha cortada pela borda dele (um braço, o cabelo), uma linha branca
          reta denunciava o recorte. */}
      {comRecorte && pessoa ? (
        <g clipPath={`url(#${id}corte)`}>
          <g mask={someDosLados ? `url(#${id}someLados)` : undefined}>
            <g mask={someEmCima ? `url(#${id}someTopo)` : undefined}>
              <g filter={`url(#${id}pessoa)`}>
                <image href={p.recorte} x={pessoa.x} y={pessoa.y} width={pessoa.w} height={pessoa.h}
                  preserveAspectRatio="none"
                  transform={p.espelhar ? `translate(${2 * pessoa.x + pessoa.w} 0) scale(-1 1)` : undefined} />
              </g>
            </g>
          </g>
        </g>
      ) : null}

      {rabiscos.length ? <Rabisco desenhos={rabiscos} cor={destaqueCor} largura={traco} /> : null}

      {/* ── a faixa do alerta ── */}
      {faixa ? (
        <g transform={`rotate(-2 ${W / 2} ${faixa.y + faixa.h / 2})`}>
          <rect x={faixa.x} y={faixa.y + faixa.h * 0.12} width={faixa.w} height={faixa.h} fill="#000" opacity={0.4} />
          <rect x={faixa.x} y={faixa.y} width={faixa.w} height={faixa.h} fill={destaqueCor}
            stroke={TINTA} strokeWidth={curto * 0.008} />
          {p.iconeAlerta.length ? (
            <Icone caminhos={p.iconeAlerta} cx={m + faixa.h * 0.55} cy={faixa.y + faixa.h / 2} lado={faixa.h * 0.72}
              traco={2.2} />
          ) : null}
          <TextoComContorno x={m + faixa.h * 1.1} y={faixa.y + faixa.h * 0.76} px={faixa.h * 0.66}
            texto={comoAparece(p.selo || 'Atenção')} familia={TITULO} />
        </g>
      ) : null}

      {/* ── o número gigante ── */}
      {c.numeroPx ? (
        <TextoComContorno x={alinhar === 'centro' ? area.x + area.w / 2 : alinhar === 'esquerda' ? area.x : area.x + area.w}
          y={c.topoDoBloco + tinta(comoAparece(p.numero), c.numeroPx, TITULO).sobe} px={c.numeroPx}
          texto={comoAparece(p.numero)} familia={TITULO} cor={comRecorte && p.fundo === 'cor' ? BRANCO : destaqueCor}
          contorno={0.07} ancora={alinhar === 'centro' ? 'middle' : alinhar === 'esquerda' ? 'start' : 'end'} />
      ) : null}

      {/* ── a chamada: o adesivo primeiro, o texto comum por cima ── */}
      {c.postas.filter((w) => w.destaque).map((w) => {
        const t = tinta(w.texto, d.px, TITULO);
        const altura = t.sobe + t.desce + 2 * d.px * ADESIVO_FOLGA_Y;
        const topo = w.baseY - t.sobe - d.px * ADESIVO_FOLGA_Y;
        const cx = w.x + w.largura / 2;
        const cy = topo + altura / 2;
        return (
          <g key={w.chave} transform={`rotate(${ADESIVO_GIRO} ${cx} ${cy})`}>
            <rect x={w.x + d.px * 0.06} y={topo + d.px * 0.08} width={w.largura} height={altura}
              rx={altura * 0.18} fill="#000" opacity={0.45} />
            <rect x={w.x} y={topo} width={w.largura} height={altura} rx={altura * 0.18} fill={corDoAdesivo}
              stroke={TINTA} strokeWidth={d.px * 0.07} />
            <text x={w.x + d.px * ADESIVO_FOLGA_X} y={w.baseY} fontFamily={TITULO} fontSize={d.px}
              fill={TINTA}>{w.texto}</text>
          </g>
        );
      })}
      {c.postas.filter((w) => !w.destaque).map((w) => (
        <TextoComContorno key={w.chave} x={w.x} y={w.baseY} px={d.px} texto={w.texto} familia={TITULO} />
      ))}

      {/* ── o selo ── */}
      {selo ? (
        <g transform={`rotate(-5 ${seloX + seloLargura / 2} ${seloY + seloPx * 0.7})`}>
          <rect x={seloX + seloPx * 0.08} y={seloY + seloPx * 0.1} width={seloLargura} height={seloPx * 1.4}
            rx={seloPx * 0.3} fill="#000" opacity={0.45} />
          <rect x={seloX} y={seloY} width={seloLargura} height={seloPx * 1.4} rx={seloPx * 0.3}
            fill={corDoAdesivo} stroke={TINTA} strokeWidth={seloPx * 0.1} />
          <text x={seloX + seloPx * 0.45} y={seloY + seloPx * 1.13} fontFamily={TITULO} fontSize={seloPx}
            fill={TINTA}>{selo}</text>
        </g>
      ) : null}

      {/* ── o "?" da pergunta, num balão da cor de destaque ── */}
      {pergunta ? (
        <g transform={`rotate(8 ${pergunta.cx} ${pergunta.cy})`}>
          <circle cx={pergunta.cx + raioDaPergunta * 0.08} cy={pergunta.cy + raioDaPergunta * 0.1}
            r={raioDaPergunta} fill="#000" opacity={0.4} />
          <circle cx={pergunta.cx} cy={pergunta.cy} r={raioDaPergunta} fill={corDoAdesivo} stroke={TINTA}
            strokeWidth={raioDaPergunta * 0.08} />
          <text x={pergunta.cx} y={pergunta.cy + raioDaPergunta * 0.47} fontFamily={TITULO}
            fontSize={raioDaPergunta * 1.35} fill={TINTA} textAnchor="middle">?</text>
        </g>
      ) : null}

      {/* ── o ícone num balão ── */}
      {icone ? (
        <g transform={`rotate(-6 ${icone.cx} ${icone.cy})`}>
          <circle cx={icone.cx + raioDoIcone * 0.08} cy={icone.cy + raioDoIcone * 0.1} r={raioDoIcone}
            fill="#000" opacity={0.4} />
          <circle cx={icone.cx} cy={icone.cy} r={raioDoIcone} fill={BALAO} stroke={TINTA}
            strokeWidth={raioDoIcone * 0.07} />
          <Icone caminhos={p.icone} cx={icone.cx} cy={icone.cy} lado={raioDoIcone * 1.24} traco={2.2} />
        </g>
      ) : null}

      {/* ── a mão apontando: gira até o dedo mirar o alvo, e espelha para a esquerda, para
          não ficar de cabeça para baixo ── */}
      {c.mao ? (
        <g filter={`url(#${id}mao)`}>
          <g transform={maoTransform}>
            <image href={p.mao} x={-c.mao.lado / 2} y={-c.mao.lado / 2} width={c.mao.lado} height={c.mao.lado}
              preserveAspectRatio="xMidYMid meet" />
          </g>
        </g>
      ) : null}
    </svg>
  );
};

/** A composição para o Player do Remotion: o SVG ocupando o quadro inteiro. */
export const ThumbComposicao: React.FC<ThumbProps> = (p) => (
  <AbsoluteFill>
    <Thumb {...p} />
  </AbsoluteFill>
);

export const TAMANHOS: Record<string, {largura: number; altura: number; nome: string}> = {
  '1280x720': {largura: 1280, altura: 720, nome: 'YouTube (1280×720)'},
  '1080x1920': {largura: 1080, altura: 1920, nome: 'Shorts, Reels, TikTok (1080×1920)'},
  '1080x1080': {largura: 1080, altura: 1080, nome: 'Quadrado (1080×1080)'},
};
