/**
 * A aba Pessoa: o recorte, o tamanho e a posição (que também se arrasta na prévia), o
 * espelho e a luz em volta dela.
 */
import React from 'react';
import {api} from '../../api';
import {duracao} from '../../formatar';
import type {Lado, Luz, ThumbConfig, VideoInfo} from '../../tipos';
import {Interruptor} from '../Interruptor';

const LUZES: [Luz, string][] = [['nenhuma', 'Nenhuma'], ['contorno', 'Na borda'], ['halo', 'Halo'],
  ['raios', 'Raios']];
const LADOS: [Lado, string][] = [['esquerda', 'Texto à esquerda'], ['direita', 'Texto à direita']];

type Props = {
  config: ThumbConfig;
  mudar: (p: Partial<ThumbConfig>) => void;
  video: VideoInfo | null;
  situacaoDoRecorte: string;
  temAlvo: boolean;
};

export const AbaPessoa: React.FC<Props> = ({config, mudar, video, situacaoDoRecorte, temAlvo}) => {
  const mexida = config.pessoaDx !== 0 || config.pessoaDy !== 0 || config.pessoaEscala !== 1;
  return (
    <div className="aba">
      <Interruptor ligado={config.recorte} aoMudar={(v) => mudar({recorte: v})} titulo="Recortar a pessoa"
        descricao="Tira o fundo de quem fala. Roda no seu computador." />
      {situacaoDoRecorte ? <small>{situacaoDoRecorte}</small> : null}
      {config.recorte ? (
        <>
          <small>Arraste a pessoa na prévia para mudar de lugar (ou use as setas do teclado).</small>
          <label className="campo">
            <span>Tamanho: {Math.round(config.pessoaEscala * 100)}%</span>
            <input type="range" min={0.6} max={1.6} step={0.02} value={config.pessoaEscala}
              onChange={(e) => mudar({pessoaEscala: Number(e.target.value)})} />
          </label>
          <div className="linha-de-opcoes">
            <button type="button" className="botao pequeno" disabled={!mexida}
              onClick={() => mudar({pessoaDx: 0, pessoaDy: 0, pessoaEscala: 1})}>Voltar ao automático</button>
          </div>
          <Interruptor ligado={config.espelhar} aoMudar={(v) => mudar({espelhar: v})} titulo="Espelhar"
            descricao="Vira a pessoa para o outro lado, para olhar para o texto." />
          <Interruptor ligado={config.contorno} aoMudar={(v) => mudar({contorno: v})} titulo="Contorno branco"
            descricao="O visual de adesivo, que destaca a pessoa de qualquer fundo." />
          <div className="campo">
            <span>Luz</span>
            <div className="linha-de-opcoes" role="group" aria-label="luz na pessoa">
              {LUZES.map(([l, nome]) => (
                <button key={l} type="button" className="pilula" aria-pressed={config.luz === l}
                  onClick={() => mudar({luz: l})}>{nome}</button>
              ))}
            </div>
          </div>
          <Interruptor ligado={config.realce} aoMudar={(v) => mudar({realce: v})} titulo="Realce"
            descricao="Um pouco mais de contraste e de cor na pessoa, para ela saltar do fundo." />
        </>
      ) : null}
      {temAlvo ? (
        <Interruptor ligado={config.seta} aoMudar={(v) => mudar({seta: v})} titulo="Seta e círculo"
          descricao="Apontam para o que a IA achou que vale mostrar no quadro." />
      ) : null}
      <div className="campo">
        <span>Lado do texto (na thumbnail deitada)</span>
        <div className="linha-de-opcoes" role="group" aria-label="lado do texto">
          {LADOS.map(([l, nome]) => (
            <button key={l} type="button" className="pilula" aria-pressed={config.lado === l}
              onClick={() => mudar({lado: l, pessoaDx: 0, maoX: null, maoY: null})}>{nome}</button>
          ))}
        </div>
      </div>
      <label className="campo">
        <span>Quadro da pessoa: {duracao(config.t)}</span>
        <input type="range" min={0} max={Math.max(0.1, (video?.duracao ?? 1) - 0.1)} step={0.1}
          value={config.t} disabled={!video} onChange={(e) => mudar({t: Number(e.target.value)})} />
        <button type="button" className="botao pequeno" disabled={!video}
          onClick={() => video && api.quadroAutomatico(video.id).then((r) => mudar({t: r.t}))}>
          Escolher o mais nítido
        </button>
      </label>
    </div>
  );
};
