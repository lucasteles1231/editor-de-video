/**
 * A thumbnail vira PNG no próprio navegador: o SVG da composição, com as fontes e as
 * imagens embutidas (o quadro, o recorte, o fundo e a mão), é desenhado num canvas. Nada
 * sai do computador.
 */
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {comToken} from '../api';
import {Thumb, type ThumbProps} from './Thumb';

function comoDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const leitor = new FileReader();
    leitor.onload = () => resolve(String(leitor.result));
    leitor.onerror = () => reject(leitor.error);
    leitor.readAsDataURL(blob);
  });
}

const fontes: Record<string, Promise<string>> = {};

/** A fonte como data URL: dentro de uma imagem SVG nada externo é carregado. */
export function fonteEmbutida(url: string): Promise<string> {
  if (!url || url.startsWith('data:')) return Promise.resolve(url);
  fontes[url] ??= fetch(url).then((r) => r.blob()).then(comoDataUrl);
  return fontes[url];
}

export async function imagemEmbutida(url: string): Promise<string> {
  if (!url || url.startsWith('data:')) return url;
  const r = await fetch(/[?&]t=/.test(url) ? url : comToken(url));
  return comoDataUrl(await r.blob());
}

export async function gerarPng(props: ThumbProps): Promise<Blob> {
  const [fonteTitulo, fonteTexto, quadro, recorte, fundoImagem, mao] = await Promise.all([
    fonteEmbutida(props.fonteTitulo), fonteEmbutida(props.fonteTexto),
    imagemEmbutida(props.quadro), imagemEmbutida(props.recorte), imagemEmbutida(props.fundoImagem),
    imagemEmbutida(props.mao)]);
  const svg = renderToStaticMarkup(createElement(Thumb, {
    ...props, fonteTitulo, fonteTexto, quadro, recorte, fundoImagem, mao,
  }));
  const url = URL.createObjectURL(new Blob([svg], {type: 'image/svg+xml;charset=utf-8'}));
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = props.largura;
    canvas.height = props.altura;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('o navegador não deu um canvas');
    ctx.drawImage(img, 0, 0, props.largura, props.altura);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('o PNG não saiu'))), 'image/png'));
  } finally {
    URL.revokeObjectURL(url);
  }
}
