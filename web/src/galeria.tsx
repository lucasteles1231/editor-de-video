/**
 * Galeria de desenvolvimento: todos os modelos da thumbnail lado a lado, com um vídeo de
 * verdade e o recorte de verdade, para conferir o desenho de uma vez só. Não vai para a
 * página montada (só o index.html entra no build).
 *
 *   editar --porta 8765 --sem-navegador        (o vídeo enviado pela página ou pela API)
 *   npm run dev → http://localhost:5173/galeria.html?t=<token>#v=<id do vídeo>&s=<segundo>&a=<largura/altura>
 */
import {useEffect, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {api} from './api';
import {FONTES} from './componentes/ThumbPasso';
import {Thumb, type ThumbProps} from './thumb/Thumb';
import {carregarFonte} from './thumb/medida';
import type {RecorteInfo} from './tipos';

const q = new URLSearchParams(location.hash.slice(1));
const vid = q.get('v') ?? '';
const segundo = Number(q.get('s') ?? 1);
const aspecto = Number(q.get('a') ?? 0.5625);

type Caso = Partial<ThumbProps> & {nome: string; comRecorte?: boolean; outroQuadro?: number};

const MAO_3D = '/maos/mao-3d-default.png';
const MAO_VETOR = '/maos/mao-vetor-default.svg';

const CASOS: Caso[] = [
  {nome: 'vídeo desfocado · mão 3D', texto: 'Corta as pausas sozinho', destaque: 2, comRecorte: true, mao: MAO_3D},
  {nome: 'cor · luz na borda · mão vetor', texto: 'Legenda que acompanha', destaque: 1, cor: 'rosa', fundo: 'cor',
    comRecorte: true, luz: 'contorno', mao: MAO_VETOR},
  {nome: 'número · cor · halo', modelo: 'numero', numero: '3', texto: 'Dicas de edição', cor: 'lima', fundo: 'cor',
    comRecorte: true, selo: 'NOVO', luz: 'halo'},
  {nome: 'pergunta · raios · vinheta', modelo: 'pergunta', texto: 'Vale a pena editar?', destaque: 3, cor: 'ciano',
    comRecorte: true, luz: 'raios', vinheta: true},
  {nome: 'alerta · sem recorte', modelo: 'alerta', texto: 'Pare de cortar na mão', destaque: 4, cor: 'vermelho',
    selo: 'CUIDADO'},
  {nome: 'outro quadro de fundo · tom', texto: 'Microfone barato funciona', destaque: 0, cor: 'laranja',
    comRecorte: true, outroQuadro: 2.0, desfoque: 0.1, tom: true},
  {nome: 'menor, deslocada e espelhada', texto: 'Este microfone muda tudo', destaque: 1, comRecorte: true,
    pessoaEscala: 0.8, pessoaDx: 0.04, espelhar: true, fundo: 'cor', cor: 'roxo', mao: MAO_3D},
  {nome: 'mão em outro tom · seta', texto: 'Olha esse microfone', destaque: 2, comRecorte: true,
    mao: '/maos/mao-3d-medium-dark.png', seta: true, alvo: {x0: 0.55, y0: 0.32, x1: 0.85, y1: 0.56}},
  {nome: 'texto à direita · mão', texto: 'Edição em 1 minuto', destaque: 2, cor: 'roxo', fundo: 'cor',
    lado: 'direita', comRecorte: true, mao: MAO_VETOR},
  {nome: 'vertical · cor · mão', largura: 1080, altura: 1920, texto: 'Corta as pausas sozinho', destaque: 2,
    fundo: 'cor', comRecorte: true, mao: MAO_3D},
  {nome: 'vertical · número · halo', largura: 1080, altura: 1920, modelo: 'numero', numero: 'R$10',
    texto: 'Microfone que presta', cor: 'lima', comRecorte: true, luz: 'halo'},
  {nome: 'quadrado · pergunta · mão', largura: 1080, altura: 1080, modelo: 'pergunta', texto: 'Vale a pena?',
    destaque: 1, cor: 'ciano', fundo: 'cor', comRecorte: true, mao: MAO_VETOR},
  {nome: 'quadrado · alerta · raios', largura: 1080, altura: 1080, modelo: 'alerta',
    texto: 'Erro que todo mundo comete', destaque: 1, selo: 'ATENÇÃO', comRecorte: true, luz: 'raios'},
];

function Galeria() {
  const [recorte, setRecorte] = useState<RecorteInfo | null>(null);
  const [icones, setIcones] = useState<Record<string, string[]>>({});
  const [pronta, setPronta] = useState(false);
  useEffect(() => {
    Promise.all([carregarFonte(), api.recorteInfo(vid, segundo), api.icones()]).then(([, r, i]) => {
      setRecorte(r);
      setIcones(i);
      setPronta(true);
    });
  }, []);
  if (!pronta) return <p style={{color: '#fff', padding: 16}}>carregando…</p>;
  return (
    <div id="galeria" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 18, padding: 18,
      alignItems: 'start'}}>
      {CASOS.map(({nome, comRecorte, outroQuadro, ...c}) => {
        const props: ThumbProps = {
          largura: 1280, altura: 720, quadro: api.quadroUrl(vid, segundo, 1920), aspecto,
          recorte: comRecorte && recorte?.ok ? api.recorteUrl(vid, segundo, 1440) : '',
          pessoa: comRecorte ? recorte?.pessoa ?? null : null, rosto: recorte?.rosto ?? null,
          fundo: 'video', fundoImagem: api.quadroUrl(vid, outroQuadro ?? segundo, 1920), fundoAspecto: aspecto,
          fundoDoProprioQuadro: outroQuadro === undefined, foco: null, desfoque: 0.6, escurecer: 0.75,
          vinheta: false, tom: false, lado: 'esquerda', pessoaDx: 0, pessoaDy: 0, pessoaEscala: 1,
          espelhar: false, contorno: true, luz: 'nenhuma', realce: true, mao: '', maoAlvo: 'titulo',
          maoX: null, maoY: null, maoEscala: 1, texto: '', destaque: -1, modelo: 'classico', cor: 'amarelo',
          selo: '', numero: '', icone: [], iconeAlerta: icones.alerta ?? [], seta: false, alvo: null,
          fonteTitulo: FONTES.titulo, fonteTexto: FONTES.texto,
          ...c,
        };
        return (
          <figure key={nome} style={{margin: 0}}>
            <div style={{width: '100%', aspectRatio: `${props.largura} / ${props.altura}`,
              maxHeight: props.altura > props.largura ? 640 : undefined}}>
              <Thumb {...props} />
            </div>
            <figcaption style={{color: '#fff', font: '14px system-ui', marginTop: 6}}>{nome}</figcaption>
          </figure>
        );
      })}
    </div>
  );
}

const estilo = document.createElement('style');
estilo.textContent = '#galeria svg { width: 100%; height: 100%; display: block; }';
document.head.appendChild(estilo);
createRoot(document.getElementById('raiz')!).render(<Galeria />);
