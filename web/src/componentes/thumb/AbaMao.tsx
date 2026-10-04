/**
 * A aba Mão: o emoji da mão apontando (Fluent UI Emoji, da Microsoft, licença MIT), em
 * 3D ou em vetor, nos seis tons do emoji. Ela gira sozinha até o dedo mirar o título (ou o
 * que a IA marcou), e pode ser arrastada na prévia.
 */
import React from 'react';
import {api} from '../../api';
import type {EstiloDaMao, ThumbConfig, TomDaMao} from '../../tipos';
import {Interruptor} from '../Interruptor';

const TONS: [TomDaMao, string][] = [['default', 'amarelo'], ['light', 'claro'], ['medium-light', 'médio-claro'],
  ['medium', 'médio'], ['medium-dark', 'médio-escuro'], ['dark', 'escuro']];
const ESTILOS: [EstiloDaMao, string][] = [['3d', '3D'], ['vetor', 'Vetor']];

type Props = {config: ThumbConfig; mudar: (p: Partial<ThumbConfig>) => void; temAlvo: boolean};

export const AbaMao: React.FC<Props> = ({config, mudar, temAlvo}) => {
  const ligada = config.mao !== 'nenhuma';
  return (
    <div className="aba">
      <Interruptor ligado={ligada} titulo="Mão apontando"
        descricao="Um emoji de mão com o dedo virado para o título. Ela gira sozinha até mirar."
        aoMudar={(v) => mudar({mao: v ? 'titulo' : 'nenhuma'})} />
      {ligada ? (
        <>
          {temAlvo ? (
            <div className="campo">
              <span>Aponta para</span>
              <div className="linha-de-opcoes" role="group" aria-label="para onde a mão aponta">
                <button type="button" className="pilula" aria-pressed={config.mao === 'titulo'}
                  onClick={() => mudar({mao: 'titulo'})}>O título</button>
                <button type="button" className="pilula" aria-pressed={config.mao === 'alvo'}
                  onClick={() => mudar({mao: 'alvo'})}>O que a IA marcou</button>
              </div>
            </div>
          ) : null}
          <div className="campo">
            <span>Estilo</span>
            <div className="linha-de-opcoes" role="group" aria-label="estilo da mão">
              {ESTILOS.map(([e, nome]) => (
                <button key={e} type="button" className="pilula com-mao" aria-pressed={config.maoEstilo === e}
                  onClick={() => mudar({maoEstilo: e})}>
                  <img src={api.maoUrl(e, config.maoTom)} alt="" aria-hidden="true" />{nome}
                </button>
              ))}
            </div>
          </div>
          <div className="campo">
            <span>Tom</span>
            <div className="tons" role="group" aria-label="tom da mão">
              {TONS.map(([t, nome]) => (
                <button key={t} type="button" aria-pressed={config.maoTom === t} aria-label={`tom ${nome}`} title={nome}
                  onClick={() => mudar({maoTom: t})}>
                  <img src={api.maoUrl(config.maoEstilo, t)} alt="" aria-hidden="true" />
                </button>
              ))}
            </div>
          </div>
          <label className="campo">
            <span>Tamanho: {Math.round(config.maoEscala * 100)}%</span>
            <input type="range" min={0.5} max={1.8} step={0.05} value={config.maoEscala}
              onChange={(e) => mudar({maoEscala: Number(e.target.value)})} />
          </label>
          <small>Arraste a mão na prévia para mudar de lugar; ela continua mirando o título.</small>
          <div className="linha-de-opcoes">
            <button type="button" className="botao pequeno" disabled={config.maoX === null}
              onClick={() => mudar({maoX: null, maoY: null})}>Voltar ao lugar automático</button>
          </div>
        </>
      ) : null}
    </div>
  );
};
