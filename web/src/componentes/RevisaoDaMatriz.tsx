/**
 * A tabela de revisão da matriz: cada cena com a miniatura e os campos que o roteiro lê
 * (a descrição, as categorias, os personagens, a energia, a monetização e a observação),
 * para corrigir antes de usar. A matriz gerada pelo Gemini chega aqui, e a que veio na
 * pasta também pode ser revisada.
 */
import React, {useEffect, useState} from 'react';
import {api} from '../api';
import {paraJson} from '../matriz';
import type {CenaDaMatriz} from '../tipos';

const ENERGIAS: [string, string][] = [['', 'energia?'], ['baixa', 'Baixa'], ['media', 'Média'], ['alta', 'Alta']];
const MONETIZACOES: [string, string][] = [['ok', 'Monetizável'], ['cuidado', 'Cuidado'], ['evitar', 'Evitar']];
const PERIODOS: [string, string][] = [['', 'período?'], ['dia', 'Dia'], ['entardecer', 'Entardecer'],
  ['noite', 'Noite'], ['interno', 'Interno'], ['n/a', 'Não se aplica']];

const QUEM: Record<string, string> = {
  gemini: 'Descritas pelo Gemini',
  rascunho: 'Rascunho: a descrição veio do nome de cada arquivo',
  falsa: 'Descritas pela IA de teste',
};

export const RevisaoDaMatriz: React.FC<{
  biblioteca: string;
  linhas: CenaDaMatriz[];
  /** Quem escreveu ("gemini", "rascunho"…), vazio para a matriz que já estava em uso. */
  por: string;
  aviso: string;
  pedidos: number;
  salvando: boolean;
  aoUsar: (linhas: CenaDaMatriz[]) => void;
  aoFechar: () => void;
}> = (p) => {
  const [linhas, setLinhas] = useState(p.linhas);
  useEffect(() => setLinhas(p.linhas), [p.linhas]);
  const mudar = (i: number, parte: Partial<CenaDaMatriz>) =>
    setLinhas((ls) => ls.map((l, k) => (k === i ? {...l, ...parte} : l)));
  const semDescricao = linhas.filter((l) => !l.descricao.trim()).length;
  const baixar = () => {
    const url = URL.createObjectURL(new Blob([paraJson(linhas)], {type: 'application/json'}));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cenas.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const quem = p.por ? `${QUEM[p.por] ?? 'Gerada'}${p.por === 'gemini' ? ` (${p.pedidos} pedidos)` : ''}.`
    : 'A matriz em uso.';
  return (
    <div className="revisao" role="region" aria-label="revisão da matriz">
      <div className="revisao-topo">
        <strong>Revise a matriz · {linhas.length} cenas</strong>
        <small>
          {quem} A descrição é o que o roteiro lê para escolher as cenas: corrija o que estiver errado e marque
          como “Evitar” o que não pode entrar.
        </small>
        {p.aviso ? <div className="aviso">{p.aviso}</div> : null}
      </div>
      <div className="revisao-lista">
        {linhas.map((l, i) => (
          <div key={`${l.arquivo}-${i}`} className={`revisao-cena${l.monetizacao === 'evitar' ? ' evitar' : ''}`}>
            <img src={api.quadroDaCenaUrl(p.biblioteca, l.arquivo)} alt={`a cena ${l.arquivo}`} loading="lazy"
              width={160} height={90} />
            <div className="revisao-campos">
              <small className="revisao-arquivo">{l.arquivo}{l.duracao ? ` · ${l.duracao.toFixed(1)} s` : ''}</small>
              <textarea rows={2} aria-label={`descrição de ${l.arquivo}`} value={l.descricao}
                placeholder="o que aparece: quem, fazendo o quê, onde"
                onChange={(e) => mudar(i, {descricao: e.target.value})} />
              <div className="revisao-linha">
                <input type="text" aria-label={`categorias de ${l.arquivo}`} value={l.categorias}
                  placeholder="categorias, com vírgulas" onChange={(e) => mudar(i, {categorias: e.target.value})} />
                <input type="text" aria-label={`personagens de ${l.arquivo}`} value={l.personagens}
                  placeholder="personagens" onChange={(e) => mudar(i, {personagens: e.target.value})} />
              </div>
              <div className="revisao-linha">
                <select aria-label={`energia de ${l.arquivo}`} value={l.energia}
                  onChange={(e) => mudar(i, {energia: e.target.value})}>
                  {ENERGIAS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
                </select>
                <select aria-label={`período de ${l.arquivo}`} value={l.periodo}
                  onChange={(e) => mudar(i, {periodo: e.target.value})}>
                  {PERIODOS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
                </select>
                <select aria-label={`monetização de ${l.arquivo}`} value={l.monetizacao}
                  onChange={(e) => mudar(i, {monetizacao: e.target.value})}>
                  {MONETIZACOES.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
                </select>
              </div>
              <input type="text" aria-label={`observação de ${l.arquivo}`} value={l.obs}
                placeholder="observação: texto na tela, logo, troca de plano…"
                onChange={(e) => mudar(i, {obs: e.target.value})} />
            </div>
          </div>
        ))}
      </div>
      <div className="revisao-botoes">
        <button type="button" className="botao pequeno usar" disabled={p.salvando || semDescricao > 0}
          onClick={() => p.aoUsar(linhas)}>
          {p.salvando ? 'Salvando…' : 'Usar esta matriz'}
        </button>
        <button type="button" className="botao pequeno" onClick={baixar}>Baixar o cenas.json</button>
        <button type="button" className="botao pequeno" onClick={p.aoFechar}>Fechar</button>
        {semDescricao ? <small>{semDescricao} cena{semDescricao > 1 ? 's' : ''} sem descrição.</small>
          : <small>Baixe para guardar junto dos clipes: da próxima vez, ele entra sozinho.</small>}
      </div>
    </div>
  );
};
