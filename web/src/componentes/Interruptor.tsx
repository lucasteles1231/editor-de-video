import React from 'react';

type Props = {
  ligado: boolean;
  aoMudar: (ligado: boolean) => void;
  titulo: string;
  descricao?: string;
  desabilitado?: boolean;
};

/** Um liga-desliga com título e uma linha do que ele faz. */
export const Interruptor: React.FC<Props> = ({ligado, aoMudar, titulo, descricao, desabilitado}) => (
  <label className={`interruptor${desabilitado ? ' desligado' : ''}`}>
    <input type="checkbox" checked={ligado} disabled={desabilitado}
      onChange={(e) => aoMudar(e.target.checked)} />
    <span className="chave" aria-hidden="true" />
    <span className="texto">
      <strong>{titulo}</strong>
      {descricao ? <small>{descricao}</small> : null}
    </span>
  </label>
);
