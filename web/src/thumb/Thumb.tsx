/**
 * A thumbnail: uma composição do Remotion feita inteira em SVG.
 *
 * Inteira em SVG por dois motivos: o mesmo desenho aparece ao vivo no Player do
 * Remotion e vira PNG no próprio navegador (exportar.ts), sem servidor de render e
 * sem nenhuma chamada de rede; e SVG se rasteriza igual no Chrome, no Edge e no Safari.
 */
import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Arranjo} from '../tipos';
import {DESTAQUE_ALTURA, DESTAQUE_BASE, DESTAQUE_ESCALA, DESTAQUE_GIRO, FAMILIA, diagramar} from './medida';

export type ThumbProps = {
  largura: number;
  altura: number;
  /** A imagem de fundo (URL ou data URL). */
  fundo: string;
  texto: string;
  destaque: number;
  /** Os caminhos SVG do ícone (Tabler, caixa de 24); vazio, sem ícone. */
  icone: string[];
  arranjo: Arranjo;
  /** 0 a 1: o quanto o lado do texto escurece. */
  escurecer: number;
  /** A fonte (URL ou data URL). */
  fonte: string;
};

const TINTA = '#1A1A1A';
const AMARELO = '#FFD400';
const BALAO = '#FFEC96';

export const Thumb: React.FC<ThumbProps> = (p) => {
  const {largura: W, altura: H} = p;
  const curto = Math.min(W, H);
  const margem = curto * 0.07;
  const lado = p.arranjo === 'lado';
  const area = lado
    ? {x: margem, w: W * 0.56 - margem, h: H - 2 * margem}
    : {x: margem, w: W - 2 * margem, h: H * (W > H ? 0.5 : 0.36)};
  const pxMax = Math.min(H * 0.17, W * (lado ? 0.1 : 0.13));
  const d = diagramar(p.texto, p.destaque, area.w, area.h, pxMax);
  const alturaDoBloco = d.altura;
  const topo = lado
    ? (H - alturaDoBloco) / 2
    : p.arranjo === 'em-cima'
      ? margem
      : H - margem - alturaDoBloco;
  const traco = Math.max(2, d.px * 0.13);

  // Cada palavra no lugar dela: a linha de base de cada linha soma as alturas de cima.
  const postas: {chave: string; texto: string; x: number; baseY: number; largura: number;
    destaque: boolean}[] = [];
  let y = topo;
  d.linhas.forEach((linha, k) => {
    const inicioX = lado ? area.x : area.x + (area.w - linha.largura) / 2;
    for (const w of linha.palavras) {
      postas.push({chave: `${k}-${w.indice}`, texto: w.texto, x: inicioX + w.x, baseY: y + linha.base,
        largura: w.largura, destaque: w.indice === p.destaque});
    }
    y += linha.altura;
  });

  const gradiente = lado
    ? {x1: '0', y1: '0', x2: '1', y2: '0'}
    : p.arranjo === 'em-cima'
      ? {x1: '0', y1: '0', x2: '0', y2: '1'}
      : {x1: '0', y1: '1', x2: '0', y2: '0'};

  const raio = curto * 0.13;
  const iconeX = W - margem - raio;
  const iconeY = p.arranjo === 'em-cima' ? H - margem - raio : margem + raio;

  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
      <defs>
        <style>{`@font-face{font-family:'${FAMILIA}';font-weight:700;src:url(${p.fonte}) format('truetype');}`}</style>
        <linearGradient id="escuro" {...gradiente}>
          <stop offset="0" stopColor="#000" stopOpacity={0.9 * p.escurecer} />
          <stop offset="0.55" stopColor="#000" stopOpacity={0.35 * p.escurecer} />
          <stop offset="1" stopColor="#000" stopOpacity={0} />
        </linearGradient>
      </defs>
      <rect width={W} height={H} fill={TINTA} />
      {p.fundo ? (
        <image href={p.fundo} x={0} y={0} width={W} height={H} preserveAspectRatio="xMidYMid slice" />
      ) : null}
      <rect width={W} height={H} fill="url(#escuro)" />

      {/* O adesivo vem antes do texto comum: se ainda encostar numa vizinha, fica por
          baixo dela, e nenhuma letra some. */}
      {postas.filter((w) => w.destaque).map((w) => {
        const px = d.px * DESTAQUE_ESCALA;
        const cx = w.x + w.largura / 2;
        const cy = w.baseY - px * DESTAQUE_BASE;
        const altura = px * DESTAQUE_ALTURA;
        return (
          <g key={w.chave} transform={`rotate(${DESTAQUE_GIRO} ${cx} ${cy})`}>
            <rect x={w.x + traco} y={cy - altura / 2 + traco * 1.2} width={w.largura} height={altura}
              rx={altura * 0.32} fill="#000" opacity={0.45} />
            <rect x={w.x} y={cy - altura / 2} width={w.largura} height={altura} rx={altura * 0.32}
              fill={AMARELO} stroke={TINTA} strokeWidth={traco * 0.9} />
            <text x={cx} y={cy + px * DESTAQUE_BASE} textAnchor="middle" fontFamily={FAMILIA}
              fontWeight={700} fontSize={px} fill={TINTA}>{w.texto}</text>
          </g>
        );
      })}
      {postas.filter((w) => !w.destaque).map((w) => (
        <text key={w.chave} x={w.x} y={w.baseY} fontFamily={FAMILIA} fontWeight={700}
          fontSize={d.px} fill="#FFFFFF" stroke="#000" strokeWidth={traco}
          strokeLinejoin="round" paintOrder="stroke">{w.texto}</text>
      ))}

      {p.icone.length ? (
        <g>
          <circle cx={iconeX + raio * 0.08} cy={iconeY + raio * 0.1} r={raio} fill="#000" opacity={0.35} />
          <circle cx={iconeX} cy={iconeY} r={raio} fill={BALAO} stroke={TINTA} strokeWidth={raio * 0.07} />
          <g transform={`translate(${iconeX - raio * 0.62} ${iconeY - raio * 0.62}) scale(${(raio * 1.24) / 24})`}
            fill="none" stroke={TINTA} strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
            {p.icone.map((caminho, i) => <path key={i} d={caminho} />)}
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
