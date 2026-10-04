/**
 * A thumbnail com IA, dentro do passo 5: a chave do Gemini, o aviso do que sai do
 * computador e as três ideias, cada uma desenhada pela mesma composição da prévia.
 */
import React, {useState} from 'react';
import {Thumb, type ThumbProps} from '../thumb/Thumb';
import type {EstadoIa, Ideia} from '../tipos';
import {Interruptor} from './Interruptor';

const ONDE_PEGAR = 'https://aistudio.google.com/apikey';

type Props = {
  ia: EstadoIa;
  usar: boolean;
  setUsar: (v: boolean) => void;
  aoSalvarChave: (chave: string) => Promise<void>;
  aoApagarChave: () => Promise<void>;
  /** A edição terminou: já dá para pedir ideias. */
  pronto: boolean;
  pensando: boolean;
  erro: string;
  ideias: Ideia[];
  escolhida: number;
  aoEscolher: (i: number) => void;
  aoPedirOutras: () => void;
  /** As props de cada ideia para a miniatura (null enquanto o recorte dela carrega). */
  propsDaIdeia: (ideia: Ideia) => ThumbProps | null;
  /** O fundo gerado custa dinheiro: só sai com o clique, ideia por ideia. */
  aoGerarFundo: (i: number) => void;
  gerando: number | null;
  pexelsConfigurado: boolean;
};

const FUNDOS: Record<Ideia['fundo'], string> = {
  video: 'fundo: outro quadro do vídeo', desfocado: 'fundo: o vídeo desfocado', cor: 'fundo: cor',
  banco: 'fundo: foto do Pexels', gerado: 'fundo: imagem gerada',
};

const Aviso: React.FC = () => (
  <small className="aviso-ia">
    Ao usar, o texto da fala e 8 quadros pequenos (512 px) vão para o Gemini, do Google. O vídeo
    não sai do computador. Na cota gratuita, o Google pode usar esse conteúdo para melhorar os
    produtos dele.
  </small>
);

export const PainelIa: React.FC<Props> = (p) => {
  const [chave, setChave] = useState('');
  const [salvando, setSalvando] = useState(false);
  const [erroChave, setErroChave] = useState('');

  const salvar = async (e: React.FormEvent) => {
    e.preventDefault();
    setSalvando(true);
    setErroChave('');
    try {
      await p.aoSalvarChave(chave.trim());
      setChave('');
    } catch (erro) {
      setErroChave((erro as Error).message);
    } finally {
      setSalvando(false);
    }
  };

  if (!p.ia.configurada) {
    return (
      <div className="painel-ia" id="painel-ia">
        <strong>Thumbnail com IA <span className="etiqueta">opcional</span></strong>
        <p>
          Com uma chave do Gemini, a IA lê o que você falou, olha 8 quadros do vídeo e sugere 3
          thumbnails de acordo com o conteúdo: chamada, quadro, cores, ícone e seta.
        </p>
        <form className="chave-ia" onSubmit={salvar}>
          <input type="password" autoComplete="off" spellCheck={false} value={chave}
            placeholder="Cole aqui a sua chave do Gemini" aria-label="chave do Gemini"
            onChange={(e) => setChave(e.target.value)} />
          <button type="submit" className="botao pequeno" disabled={!chave.trim() || salvando}>
            {salvando ? 'Conferindo…' : 'Salvar chave'}
          </button>
        </form>
        {erroChave ? <div className="aviso erro">{erroChave}</div> : null}
        <a href={ONDE_PEGAR} target="_blank" rel="noreferrer">Pegar uma chave grátis no Google AI Studio</a>
        <Aviso />
      </div>
    );
  }

  return (
    <div className="painel-ia" id="painel-ia">
      <Interruptor ligado={p.usar} aoMudar={p.setUsar} titulo="Sugerir thumbnails com IA"
        descricao="Quando a edição terminar, o Gemini sugere 3 ideias de acordo com o que você falou." />
      <div className="linha-de-opcoes chave-ok">
        <small>
          {p.ia.origem === 'variavel' ? 'Chave da variável GEMINI_API_KEY' : p.ia.falsa
            ? 'IA de teste (sem rede)' : `Chave do Gemini ${p.ia.final}`}
        </small>
        {p.ia.origem === 'arquivo' ? (
          <button type="button" className="botao pequeno" onClick={() => void p.aoApagarChave()}>
            Remover chave
          </button>
        ) : null}
      </div>
      {p.usar ? (
        <>
          {p.pensando ? <div className="aviso">O Gemini está olhando o vídeo…</div> : null}
          {p.erro ? <div className="aviso erro">{p.erro}</div> : null}
          {p.ideias.length ? (
            <div className="ideias" role="group" aria-label="ideias de thumbnail">
              {p.ideias.map((ideia, i) => {
                const props = p.propsDaIdeia(ideia);
                return (
                  <div key={`${ideia.chamada}-${i}`} className="ideia-cartao">
                    <button type="button" className="ideia" aria-pressed={p.escolhida === i}
                      onClick={() => p.aoEscolher(i)}>
                      <div className="miniatura-ideia">
                        {props ? <Thumb {...props} /> : <div className="carregando-ideia" />}
                      </div>
                      <span>{ideia.ideia || ideia.chamada}</span>
                      <small>{FUNDOS[ideia.fundo]}{ideia.mao !== 'nenhuma' ? ' · mão apontando' : ''}</small>
                    </button>
                    {ideia.fundo === 'gerado' && !ideia.imagem ? (
                      <button type="button" className="botao pequeno" disabled={p.gerando !== null}
                        title={ideia.cena} onClick={() => p.aoGerarFundo(i)}>
                        {p.gerando === i ? 'Gerando…' : 'Gerar fundo · ~US$ 0,04'}
                      </button>
                    ) : null}
                    {ideia.fundo === 'banco' && !ideia.imagem && !p.pexelsConfigurado ? (
                      <small>A foto vem do Pexels: cole a chave na aba Fundo.</small>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : !p.pronto && !p.pensando ? (
            <small>As ideias aparecem aqui quando a edição terminar.</small>
          ) : null}
          {p.pronto ? (
            <button type="button" className="botao pequeno" disabled={p.pensando} onClick={p.aoPedirOutras}>
              {p.ideias.length ? 'Sugerir outras 3' : 'Sugerir com IA'}
            </button>
          ) : null}
          <Aviso />
        </>
      ) : null}
    </div>
  );
};
