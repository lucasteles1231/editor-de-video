/**
 * 5. Thumbnail: uma capa separada, desenhada pela composição do Remotion e mostrada
 * ao vivo no Player enquanto se mexe nas opções.
 */
import {Player} from '@remotion/player';
import React, {useEffect, useMemo, useState} from 'react';
import {api} from '../api';
import {duracao} from '../formatar';
import {TAMANHOS, ThumbComposicao, type ThumbProps} from '../thumb/Thumb';
import type {Arranjo, ThumbConfig, VideoInfo} from '../tipos';
import {Interruptor} from './Interruptor';

const ARRANJOS: [Arranjo, string][] = [['embaixo', 'Texto embaixo'], ['em-cima', 'Texto em cima'],
  ['lado', 'Texto ao lado']];

type Props = {
  video: VideoInfo | null;
  config: ThumbConfig;
  mudar: (p: Partial<ThumbConfig>) => void;
  icones: Record<string, string[]>;
  fonteOk: boolean;
};

export function propsDaThumb(config: ThumbConfig, video: VideoInfo, tamanho: string,
                             icones: Record<string, string[]>, fonte: string): ThumbProps {
  const {largura, altura} = TAMANHOS[tamanho];
  return {
    largura, altura,
    fundo: api.quadroUrl(video.id, config.t, Math.max(largura, altura)),
    texto: config.texto || 'Escreva o título da sua thumbnail',
    destaque: config.destaque,
    icone: config.icone ? (icones[config.icone] ?? []) : [],
    arranjo: config.arranjo,
    escurecer: config.escurecer,
    fonte,
  };
}

export const ThumbPasso: React.FC<Props> = ({video, config, mudar, icones, fonteOk}) => {
  const [busca, setBusca] = useState('');
  const [tamanhoDaPrevia, setTamanhoDaPrevia] = useState('1280x720');
  const palavras = config.texto.trim().split(/\s+/).filter(Boolean);
  const nomes = useMemo(() => Object.keys(icones).filter((n) => n.includes(busca.toLowerCase())),
    [icones, busca]);
  const previa = config.tamanhos.includes(tamanhoDaPrevia) ? tamanhoDaPrevia : (config.tamanhos[0] ?? '1280x720');

  useEffect(() => {
    if (!config.tamanhos.includes(tamanhoDaPrevia) && config.tamanhos[0]) setTamanhoDaPrevia(config.tamanhos[0]);
  }, [config.tamanhos, tamanhoDaPrevia]);

  const alternarTamanho = (t: string) => {
    const tem = config.tamanhos.includes(t);
    const novos = tem ? config.tamanhos.filter((x) => x !== t) : [...config.tamanhos, t];
    if (novos.length) mudar({tamanhos: novos});
  };

  return (
    <section className="passo" id="passo-thumb">
      <header>
        <span className="numero" aria-hidden="true">5</span>
        <div>
          <h2>Thumbnail</h2>
          <p>Uma capa à parte, feita com Remotion. A prévia muda enquanto você escolhe.</p>
        </div>
      </header>
      <Interruptor ligado={config.ativo} aoMudar={(v) => mudar({ativo: v})} titulo="Gerar thumbnail"
        descricao="Sai como PNG e como JPG de até 2 MB (o limite do YouTube), na mesma pasta do vídeo." />
      <div className={config.ativo ? '' : 'desligado'} aria-disabled={!config.ativo}>
        <div className="thumb-area">
          <div>
            {video && fonteOk ? (
              <div className="previa-thumb">
                <Player component={ThumbComposicao}
                  inputProps={propsDaThumb(config, video, previa, icones, '/fontes/DejaVuSans-Bold.ttf')}
                  durationInFrames={1} fps={30}
                  compositionWidth={TAMANHOS[previa].largura} compositionHeight={TAMANHOS[previa].altura}
                  style={{width: '100%', aspectRatio: `${TAMANHOS[previa].largura} / ${TAMANHOS[previa].altura}`,
                    maxHeight: 520}}
                  acknowledgeRemotionLicense />
              </div>
            ) : (
              <div className="vazio">Envie um vídeo para ver a prévia da thumbnail.</div>
            )}
            <div className="linha-de-opcoes" style={{marginTop: 12}} role="group" aria-label="tamanhos">
              {Object.entries(TAMANHOS).map(([t, info]) => (
                <button key={t} type="button" className="pilula" aria-pressed={config.tamanhos.includes(t)}
                  onClick={() => alternarTamanho(t)} title={info.nome}>{info.nome}</button>
              ))}
            </div>
            {config.tamanhos.length > 1 ? (
              <div className="linha-de-opcoes" style={{marginTop: 8}}>
                <small style={{alignSelf: 'center'}}>Prévia de:</small>
                {config.tamanhos.map((t) => (
                  <button key={t} type="button" className="pilula" aria-pressed={previa === t}
                    onClick={() => setTamanhoDaPrevia(t)}>{t.replace('x', '×')}</button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="campos" style={{marginTop: 0, gridTemplateColumns: 'minmax(0, 1fr)'}}>
            <label className="campo">
              <span>Título</span>
              <input type="text" value={config.texto} maxLength={70}
                placeholder="Vem da primeira frase do vídeo depois de editar"
                onChange={(e) => mudar({texto: e.target.value, destaque: -1})} />
              {palavras.length ? (
                <>
                  <small>Toque numa palavra para ela virar o adesivo amarelo:</small>
                  <div className="palavras">
                    {palavras.map((p, i) => (
                      <button key={`${i}-${p}`} type="button" aria-pressed={config.destaque === i}
                        onClick={() => mudar({destaque: config.destaque === i ? -1 : i})}>{p}</button>
                    ))}
                  </div>
                </>
              ) : null}
            </label>
            <label className="campo">
              <span>Quadro de fundo: {duracao(config.t)}</span>
              <input type="range" min={0} max={Math.max(0.1, (video?.duracao ?? 1) - 0.1)} step={0.1}
                value={config.t} disabled={!video} onChange={(e) => mudar({t: Number(e.target.value)})} />
              <button type="button" className="botao pequeno" disabled={!video}
                onClick={() => video && api.quadroAutomatico(video.id).then((r) => mudar({t: r.t}))}>
                Escolher o mais nítido
              </button>
            </label>
            <div className="campo">
              <span>Arranjo</span>
              <div className="linha-de-opcoes" role="group" aria-label="arranjo">
                {ARRANJOS.map(([a, nome]) => (
                  <button key={a} type="button" className="pilula" aria-pressed={config.arranjo === a}
                    onClick={() => mudar({arranjo: a})}>{nome}</button>
                ))}
              </div>
            </div>
            <label className="campo">
              <span>Escurecer o fundo: {Math.round(config.escurecer * 100)}%</span>
              <input type="range" min={0} max={1} step={0.05} value={config.escurecer}
                onChange={(e) => mudar({escurecer: Number(e.target.value)})} />
            </label>
            <div className="campo">
              <span>Ícone {config.icone ? `· ${config.icone}` : '(opcional)'}</span>
              <input type="text" placeholder="buscar: dinheiro, celular, foguete…" value={busca}
                onChange={(e) => setBusca(e.target.value)} />
              <div className="icones-lista">
                <button type="button" aria-pressed={!config.icone} title="sem ícone"
                  onClick={() => mudar({icone: ''})}>—</button>
                {nomes.map((n) => (
                  <button key={n} type="button" aria-pressed={config.icone === n} title={n}
                    onClick={() => mudar({icone: n})}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      {icones[n].map((d, i) => <path key={i} d={d} />)}
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
