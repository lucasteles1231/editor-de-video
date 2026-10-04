/**
 * A coluna da direita: o vídeo, o botão de editar, o progresso e o resultado.
 */
import React from 'react';
import {api} from '../api';
import {duracao, numero} from '../formatar';
import type {Tarefa, VideoInfo} from '../tipos';

const ETAPAS = ['transcrevendo', 'cortando', 'desenhando', 'finalizando'];
const NOMES: Record<string, string> = {
  transcrevendo: 'Transcrever a fala', cortando: 'Cortar os silêncios',
  desenhando: 'Desenhar legenda, zoom e ícones', finalizando: 'Finalizar o arquivo',
};

type Props = {
  /** O vídeo mostrado: o único, ou, na montagem, o de fundo. */
  video: VideoInfo | null;
  /** Na montagem, a imagem de quem vai por cima (o recorte da pessoa ou o personagem), na
   *  posição de casa: embaixo no meio em pé, embaixo à direita deitado. */
  porCima?: {url: string; emPe: boolean} | null;
  podeEditar: boolean;
  tarefa: Tarefa | null;
  previa: boolean;
  setPrevia: (v: boolean) => void;
  aoEditar: () => void;
  aoCancelar: () => void;
  erro: string;
  thumbs: {nome: string; url: string; jpgBytes: number}[];
  gerandoThumbs: boolean;
  pastaSaida: string;
};

function mostrar(el: HTMLElement | null, block: ScrollLogicalPosition): void {
  const calmo = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  el?.scrollIntoView({behavior: calmo ? 'auto' : 'smooth', block});
}

export const Painel: React.FC<Props> = (p) => {
  const t = p.tarefa;
  const rodando = t?.estado === 'rodando';
  const pronto = t?.estado === 'pronto' && t.resultado;
  const indiceAtual = t ? ETAPAS.indexOf(t.etapa) : -1;

  // A coluna rola sozinha: ao começar, o progresso aparece inteiro; ao terminar, o
  // resultado sobe para o topo dela (as thumbnails ainda chegam e crescem para baixo).
  const editarRef = React.useRef<HTMLDivElement>(null);
  const resultado = React.useRef<HTMLDivElement>(null);
  const rodandoId = rodando ? t.id : '';
  const prontoId = pronto ? t.id : '';
  React.useEffect(() => {
    if (rodandoId) mostrar(editarRef.current, 'nearest');
  }, [rodandoId]);
  React.useEffect(() => {
    if (prontoId) mostrar(resultado.current, 'start');
  }, [prontoId]);
  const nThumbs = p.thumbs.length;
  React.useEffect(() => {
    if (nThumbs) mostrar(resultado.current, 'nearest');
  }, [nThumbs]);

  return (
    <aside className="lateral">
      <div className="painel">
        <h3>{pronto ? 'Vídeo editado' : 'Seu vídeo'}</h3>
        {pronto ? (
          <video key={t.id} className="tela" src={api.arquivoUrl(t.id, 'video', true)} controls playsInline />
        ) : p.video && p.porCima ? (
          <div className={`tela-montada${p.porCima.emPe ? ' em-pe' : ''}`}>
            <video key={p.video.id} className="tela" src={api.videoUrl(p.video.id)}
              controls playsInline preload="metadata" />
            <img className="por-cima" src={p.porCima.url} alt="" aria-hidden="true" />
          </div>
        ) : p.video ? (
          <video key={p.video.id} className="tela" src={api.videoUrl(p.video.id)}
            controls playsInline preload="metadata" />
        ) : (
          <div className="vazio">O vídeo aparece aqui depois de enviado.</div>
        )}
      </div>

      <div className="painel" id="botao-editar" ref={editarRef}>
        <button type="button" className="botao principal" disabled={!p.podeEditar || rodando} onClick={p.aoEditar}>
          {rodando ? 'Editando…' : pronto ? 'Editar de novo' : 'Editar vídeo'}
        </button>
        <label className="interruptor" style={{marginTop: 12, border: 'none', padding: '4px 2px'}}>
          <input type="checkbox" checked={p.previa} onChange={(e) => p.setPrevia(e.target.checked)} />
          <span className="chave" aria-hidden="true" />
          <span className="texto">
            <strong>Só os primeiros 15 s</strong>
            <small>Uma prévia rápida para conferir o estilo antes do vídeo inteiro.</small>
          </span>
        </label>
        {p.erro ? <div className="aviso erro">{p.erro}</div> : null}
        {t && t.estado !== 'pronto' ? (
          <div aria-live="polite">
            <div className="barra" role="progressbar" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={Math.round(t.fracao * 100)}>
              <div style={{width: `${Math.max(3, t.fracao * 100)}%`}} />
            </div>
            <strong>{numero(t.fracao * 100)}%</strong>
            {t.falta_s ? <span> · faltam uns {duracao(t.falta_s)}</span> : null}
            <ul className="etapas">
              {ETAPAS.map((e, i) => (
                <li key={e} className={i < indiceAtual ? 'feita' : i === indiceAtual ? 'atual' : ''}>
                  <span aria-hidden="true">{i < indiceAtual ? '✓' : i === indiceAtual ? '▸' : '·'}</span>
                  {NOMES[e]}
                </li>
              ))}
            </ul>
            {t.detalhe && t.estado === 'rodando' ? <small className="detalhe">{t.detalhe.split('\n')[0]}</small> : null}
            {t.estado === 'erro' ? <div className="aviso erro">{t.erro}</div> : null}
            {t.estado === 'cancelado' ? <div className="aviso">Edição cancelada.</div> : null}
            {rodando ? (
              <button type="button" className="botao pequeno" style={{marginTop: 10}} onClick={p.aoCancelar}>
                Cancelar
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="painel" id="passo-resultado" ref={resultado}>
        <h3>Resultado</h3>
        {pronto ? (
          <>
            <div className="numeros">
              <div><b>{duracao(t.resultado!.duracao_original)}</b><span>antes</span></div>
              <div><b>{duracao(t.resultado!.duracao_final)}</b><span>depois</span></div>
              <div><b>{duracao(t.resultado!.segundos)}</b><span>para editar</span></div>
            </div>
            <div className="downloads">
              <a className="botao pequeno" href={api.arquivoUrl(t.id, 'video')}>Baixar o vídeo</a>
              {t.resultado!.legendas.map((l) => {
                const ext = l.split('.').pop() ?? '';
                return <a key={l} className="botao pequeno" href={api.arquivoUrl(t.id, ext)}>Legenda .{ext}</a>;
              })}
              <a className="botao pequeno" href={api.arquivoUrl(t.id, 'plano')}>Plano (.json)</a>
              <button type="button" className="botao pequeno rosa" onClick={() => api.abrirPasta()}>Abrir a pasta</button>
            </div>
            {p.gerandoThumbs ? <p>Gerando as thumbnails…</p> : null}
            {p.thumbs.length ? (
              <div className="miniaturas">
                {p.thumbs.map((th) => (
                  <a key={th.nome} href={th.url} title={`baixar ${th.nome}`}>
                    <img src={th.url} alt={`thumbnail ${th.nome}`} />
                  </a>
                ))}
              </div>
            ) : null}
            <p className="salvo-em">
              Salvo em <code>{p.pastaSaida}</code>
            </p>
          </>
        ) : (
          <div className="vazio">Aqui aparecem o vídeo editado, as legendas e as thumbnails — com botão para abrir a pasta.</div>
        )}
      </div>
    </aside>
  );
};
