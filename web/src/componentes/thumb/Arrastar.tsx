/**
 * Arrastar a pessoa e a mão na prévia. Uma camada transparente por cima do Player: o
 * ponteiro vira coordenada da composição e a mesma conta do desenho (``compor``) diz o
 * que está embaixo dele. O que se arrasta aqui é o que sai no PNG.
 *
 * Pelo teclado: as setas movem a pessoa (com Shift, de 5 em 5%).
 */
import React, {useMemo, useRef, useState} from 'react';
import {compor, type ThumbProps} from '../../thumb/Thumb';
import type {ThumbConfig} from '../../tipos';

type Arrasto = {alvo: 'pessoa' | 'mao'; x0: number; y0: number; a: number; b: number};

type Props = {props: ThumbProps; config: ThumbConfig; mudar: (p: Partial<ThumbConfig>) => void};

export const Arrastar: React.FC<Props> = ({props, config, mudar}) => {
  const camada = useRef<HTMLDivElement>(null);
  const arrasto = useRef<Arrasto | null>(null);
  const [cursor, setCursor] = useState('default');
  const cena = useMemo(() => compor(props), [props]);
  const W = props.largura;
  const H = props.altura;

  /** O ponto do ponteiro na composição (o Player encaixa o quadro com faixas, se precisar). */
  const ponto = (e: React.PointerEvent) => {
    const r = camada.current!.getBoundingClientRect();
    const escala = Math.min(r.width / W, r.height / H);
    return {x: (e.clientX - r.left - (r.width - W * escala) / 2) / escala,
      y: (e.clientY - r.top - (r.height - H * escala) / 2) / escala};
  };

  const oQueEsta = (x: number, y: number): 'pessoa' | 'mao' | null => {
    if (cena.mao && Math.hypot(x - cena.mao.cx, y - cena.mao.cy) < cena.mao.lado * 0.5) return 'mao';
    const c = cena.caixaDaPessoa;
    if (cena.comRecorte && x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h) return 'pessoa';
    return null;
  };

  const descer = (e: React.PointerEvent) => {
    const {x, y} = ponto(e);
    const alvo = oQueEsta(x, y);
    if (!alvo) return;
    e.preventDefault();
    camada.current?.setPointerCapture(e.pointerId);
    arrasto.current = alvo === 'mao'
      ? {alvo, x0: x, y0: y, a: config.maoX ?? (cena.mao?.cx ?? 0) / W, b: config.maoY ?? (cena.mao?.cy ?? 0) / H}
      : {alvo, x0: x, y0: y, a: config.pessoaDx, b: config.pessoaDy};
    setCursor('grabbing');
  };

  const mover = (e: React.PointerEvent) => {
    const {x, y} = ponto(e);
    const a = arrasto.current;
    if (!a) {
      setCursor(oQueEsta(x, y) ? 'grab' : 'default');
      return;
    }
    const dx = (x - a.x0) / W;
    const dy = (y - a.y0) / H;
    if (a.alvo === 'mao') mudar({maoX: a.a + dx, maoY: a.b + dy});
    else mudar({pessoaDx: a.a + dx, pessoaDy: a.b + dy});
  };

  const soltar = (e: React.PointerEvent) => {
    if (!arrasto.current) return;
    arrasto.current = null;
    camada.current?.releasePointerCapture(e.pointerId);
    setCursor('grab');
  };

  const tecla = (e: React.KeyboardEvent) => {
    if (!cena.comRecorte) return;
    const passo = e.shiftKey ? 0.05 : 0.01;
    const mov: Record<string, [number, number]> = {
      ArrowLeft: [-passo, 0], ArrowRight: [passo, 0], ArrowUp: [0, -passo], ArrowDown: [0, passo],
    };
    const m = mov[e.key];
    if (!m) return;
    e.preventDefault();
    mudar({pessoaDx: config.pessoaDx + m[0], pessoaDy: config.pessoaDy + m[1]});
  };

  return (
    <div ref={camada} className="arrastar" style={{cursor}} tabIndex={0} role="application"
      aria-label="Prévia da thumbnail: arraste a pessoa ou a mão; as setas movem a pessoa"
      onPointerDown={descer} onPointerMove={mover} onPointerUp={soltar} onPointerCancel={soltar}
      onKeyDown={tecla} />
  );
};
