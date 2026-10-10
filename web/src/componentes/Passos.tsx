/**
 * Os quatro primeiros passos: enviar, edições, legenda e saída.
 */
import React, {useRef, useState} from 'react';
import {api} from '../api';
import {falaEfetiva, opcoesDeFala, semSom} from '../fala';
import {ORDEM, PLATAFORMAS, type Plataforma, juntar} from '../plataformas';
import {apelido} from '../presets';
import {bytes, duracao, numero} from '../formatar';
import type {
  AudioInfo, BibliotecaInfo, CenaDaMatriz, Edicao, EstiloDaLegenda, Estado, Fala, FonteDoFundo, FormatoDoQuadro,
  Modo, MontagemConfig, PersonagemInfo, PorCima, Preset, PresetsImportados, Saida, VideoInfo, Voz,
} from '../tipos';
import {Interruptor} from './Interruptor';
import {MinhaVoz} from './MinhaVoz';
import {RevisaoDaMatriz} from './RevisaoDaMatriz';

/** A matriz na tabela de revisão: as linhas e quem as escreveu. */
export type Revisao = {linhas: CenaDaMatriz[]; por: string; aviso: string; pedidos: number};

const Cabeca: React.FC<{n: number; titulo: string; texto: string}> = ({n, titulo, texto}) => (
  <header>
    <span className="numero" aria-hidden="true">{n}</span>
    <div>
      <h2>{titulo}</h2>
      <p>{texto}</p>
    </div>
  </header>
);

// ── 1. Enviar ────────────────────────────────────────────────────────────

/** O que se envia: o vídeo único ou uma das camadas da montagem. */
export type Envio = 'video' | 'fundo' | 'pessoa' | 'personagem' | 'audio' | 'biblioteca';

/** O custo de recortar a pessoa no vídeo inteiro pelo MODNet, medido num Apple M5 em
 *  04/10/2026: uns 0,07 s por quadro (um vídeo de 27 s a 25 fps levou uns 31 s a mais). */
const CUSTO_DO_RECORTE_POR_QUADRO = 0.07;

const Soltar: React.FC<{
  rotulo: string; dica: string; aceita: string; progresso: number | null;
  aoEscolher: (arquivo: File) => void; grande?: boolean; nome: string;
  /** Aceita vários de uma vez (os áudios, um por parágrafo). */
  aoEscolherVarios?: (arquivos: File[]) => void;
}> = ({rotulo, dica, aceita, progresso, aoEscolher, grande, nome, aoEscolherVarios}) => {
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastando, setArrastando] = useState(false);
  const escolher = (lista: FileList | null | undefined) => {
    const arquivos = Array.from(lista ?? []);
    if (aoEscolherVarios && arquivos.length) aoEscolherVarios(arquivos);
    else if (arquivos[0]) aoEscolher(arquivos[0]);
  };
  const soltar = (e: React.DragEvent) => {
    e.preventDefault();
    setArrastando(false);
    escolher(e.dataTransfer.files);
  };
  return (
    <div className={`envio${grande ? '' : ' pequena'}${arrastando ? ' arrastando' : ''}`} role="button" tabIndex={0}
      aria-label={rotulo} data-envio={nome}
      onClick={() => entrada.current?.click()}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && entrada.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setArrastando(true); }}
      onDragLeave={() => setArrastando(false)} onDrop={soltar}>
      {grande ? (
        <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M14 3v4a1 1 0 0 0 1 1h4" />
          <path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z" />
          <path d="M10 11l4 2.5l-4 2.5z" />
        </svg>
      ) : null}
      <strong>{progresso !== null ? `Enviando… ${numero(progresso * 100)}%` : rotulo}</strong>
      <small>{dica}</small>
      <input ref={entrada} type="file" accept={aceita} hidden multiple={Boolean(aoEscolherVarios)}
        onChange={(e) => escolher(e.target.files)} />
    </div>
  );
};

/** Os arquivos de uma pasta arrastada, com os das subpastas. O navegador entrega a pasta
 *  como uma "entrada", lida em lotes (de uns 100) até vir vazio. */
async function arquivosDaEntrada(entrada: FileSystemEntry): Promise<File[]> {
  if (entrada.isFile) {
    return new Promise((ok) => (entrada as FileSystemFileEntry).file((f) => ok([f]), () => ok([])));
  }
  if (!entrada.isDirectory) return [];
  const leitor = (entrada as FileSystemDirectoryEntry).createReader();
  const todas: FileSystemEntry[] = [];
  for (;;) {
    const lote = await new Promise<FileSystemEntry[]>((ok) => leitor.readEntries(ok, () => ok([])));
    if (!lote.length) break;
    todas.push(...lote);
  }
  return (await Promise.all(todas.map(arquivosDaEntrada))).flat();
}

/** A pasta das cenas: pelo seletor de pasta ou arrastando. Os vídeos de dentro (e das
 *  subpastas) vão para o editor, e uma matriz que estiver junto também. */
const SoltarPasta: React.FC<{progresso: string | null; aoEscolher: (arquivos: File[]) => void}> = (
  {progresso, aoEscolher},
) => {
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastando, setArrastando] = useState(false);
  const soltar = async (e: React.DragEvent) => {
    e.preventDefault();
    setArrastando(false);
    const entradas = Array.from(e.dataTransfer.items ?? [])
      .map((i) => i.webkitGetAsEntry?.())
      .filter((x): x is FileSystemEntry => Boolean(x));
    const arquivos = entradas.length ? (await Promise.all(entradas.map(arquivosDaEntrada))).flat()
      : Array.from(e.dataTransfer.files);
    if (arquivos.length) aoEscolher(arquivos);
  };
  // O seletor de pasta (``webkitdirectory``) não está nos tipos do React.
  const pasta = {webkitdirectory: '', directory: ''} as React.InputHTMLAttributes<HTMLInputElement>;
  return (
    <div className={`envio pequena${arrastando ? ' arrastando' : ''}`} role="button" tabIndex={0}
      aria-label="Arraste a pasta das cenas" data-envio="cenas"
      onClick={() => entrada.current?.click()}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && entrada.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setArrastando(true); }}
      onDragLeave={() => setArrastando(false)} onDrop={(e) => void soltar(e)}>
      <strong>{progresso ?? 'Arraste a pasta das cenas'}</strong>
      <small>ou clique para escolher · os vídeos de dentro, das subpastas também</small>
      <input ref={entrada} type="file" multiple hidden {...pasta}
        onChange={(e) => e.target.files?.length && aoEscolher(Array.from(e.target.files))} />
    </div>
  );
};

const FichaDaBiblioteca: React.FC<{b: BibliotecaInfo}> = ({b}) => (
  <div className="ficha" aria-label="dados da biblioteca de cenas">
    <span className="etiqueta">{b.nome}</span>
    <span className="etiqueta">{b.cenas} cenas</span>
    <span className="etiqueta">{duracao(b.duracao)} de cenas</span>
    {b.evitadas ? (
      <span className="etiqueta">
        {b.evitadas} marcada{b.evitadas > 1 ? 's' : ''} “evitar” (fica{b.evitadas > 1 ? 'm' : ''} de fora)
      </span>
    ) : null}
    {b.sem_descricao.length ? (
      <span className="etiqueta" title={b.sem_descricao.join(', ')}>
        {b.sem_descricao.length} clipe{b.sem_descricao.length > 1 ? 's' : ''} sem descrição
      </span>
    ) : null}
    {b.sem_clipe.length ? (
      <span className="etiqueta" title={b.sem_clipe.join(', ')}>
        {b.sem_clipe.length} na matriz sem clipe
      </span>
    ) : null}
  </div>
);

const FichaDoVideo: React.FC<{video: VideoInfo; rotulo?: string}> = ({video, rotulo = 'dados do vídeo'}) => (
  <div className="ficha" aria-label={rotulo}>
    <span className="etiqueta">{video.nome}</span>
    <span className="etiqueta">{video.largura}×{video.altura}</span>
    <span className="etiqueta">{video.vertical ? 'vertical' : 'horizontal'}</span>
    <span className="etiqueta">{duracao(video.duracao)}</span>
    <span className="etiqueta">{numero(video.fps, video.fps % 1 ? 2 : 0)} fps</span>
    <span className="etiqueta">{bytes(video.tamanho_bytes)}</span>
    {!video.tem_audio ? <span className="etiqueta">sem áudio</span> : null}
    {video.tem_alfa ? <span className="etiqueta">com transparência</span> : null}
  </div>
);

export type PropsDoEnvio = {
  modo: Modo;
  setModo: (m: Modo) => void;
  video: VideoInfo | null;
  fundo: VideoInfo | null;
  pessoa: VideoInfo | null;
  personagem: PersonagemInfo | null;
  /** Os áudios separados, na ordem em que tocam. */
  audios: AudioInfo[];
  /** A "Minha voz": a narração do roteiro, quando já saiu. */
  narracao: AudioInfo | null;
  aoNarrar: (a: AudioInfo | null) => void;
  /** A biblioteca de cenas, depois da matriz; e o que falta dela enquanto chega. */
  biblioteca: BibliotecaInfo | null;
  /** A pasta já chegou e falta a matriz. */
  faltaMatriz: boolean;
  enviandoBiblioteca: string | null;
  /** A biblioteca aberta no servidor (depois da pasta), para a matriz e as miniaturas. */
  bibliotecaId: string | null;
  /** O Gemini descrevendo as cenas, e a matriz na tabela de revisão. */
  gerandoMatriz: {prontas: number; total: number; pedidos: number} | null;
  revisao: Revisao | null;
  salvandoMatriz: boolean;
  aoGerarMatriz: (assunto: string) => void;
  aoRevisarMatriz: () => void;
  aoUsarMatriz: (linhas: CenaDaMatriz[]) => void;
  aoFecharRevisao: () => void;
  montagem: MontagemConfig;
  mudarMontagem: (p: Partial<MontagemConfig>) => void;
  progresso: Record<Envio, number | null>;
  erro: Record<Envio, string>;
  aoEscolher: (qual: Envio, arquivo: File) => void;
  aoEscolherAudios: (arquivos: File[]) => void;
  aoEscolherPasta: (arquivos: File[]) => void;
  aoEscolherMatriz: (arquivo: File) => void;
  aoTirarAudio: () => void;
  recorte: {baixado: boolean; tamanho: string};
  /** Onde o vídeo vai ser postado, as recomendadas pelo formato dele e os avisos. */
  plataformas: Plataforma[];
  recomendadas: Plataforma[];
  aoAlternarPlataforma: (p: Plataforma) => void;
  avisosDaPlataforma: string[];
};

const Aviso: React.FC<{texto: string}> = ({texto}) => (texto ? <div className="aviso erro">{texto}</div> : null);

const NOMES_DA_FALA: Record<Fala, string> = {fundo: 'O vídeo de fundo', pessoa: 'O vídeo da pessoa',
  audio: 'Áudio separado', voz: 'Minha voz (de um roteiro)'};

const FONTES_DO_FUNDO: [FonteDoFundo, string][] = [['video', 'Um vídeo'], ['cenas', 'Biblioteca de cenas']];
const POR_CIMA: [PorCima, string][] = [['pessoa', 'Vídeo da pessoa'], ['personagem', 'Personagem animado'],
  ['nada', 'Nada']];

/** Sem matriz (ou para trocar a que veio): o Gemini descreve as cenas, e a pessoa revisa. */
const GerarMatriz: React.FC<PropsDoEnvio> = (p) => {
  const [assunto, setAssunto] = useState('');
  const g = p.gerandoMatriz;
  return (
    <div className="gerar-matriz">
      <label className="campo">
        <span>{p.biblioteca ? 'Ou gere uma nova com o Gemini' : 'Sem matriz? O Gemini descreve as cenas'}</span>
        <input type="text" value={assunto} maxLength={200} disabled={Boolean(g)}
          placeholder="do que são as cenas (opcional): trailers do GTA 6"
          onChange={(e) => setAssunto(e.target.value)} />
        <small>
          Ele vê 3 quadros de cada clipe, 12 clipes por pedido da cota grátis, e escreve a descrição, as
          categorias, a energia e a monetização. Você revisa numa tabela antes de usar. Sem a chave (passo 5), sai
          um rascunho com o nome de cada arquivo.
        </small>
      </label>
      <div className="linha-de-opcoes">
        <button type="button" className="botao pequeno" disabled={Boolean(g)}
          onClick={() => p.aoGerarMatriz(assunto)}>
          {g ? 'Gerando…' : p.biblioteca ? 'Gerar de novo' : 'Gerar a matriz'}
        </button>
        {p.biblioteca ? (
          <button type="button" className="botao pequeno" disabled={Boolean(g)} onClick={p.aoRevisarMatriz}>
            Revisar a matriz
          </button>
        ) : null}
      </div>
      {g ? (
        <small className="andamento" aria-live="polite">
          Descrevendo {g.prontas} de {g.total} cenas… ({g.pedidos} {g.pedidos === 1 ? 'pedido' : 'pedidos'} ao Gemini)
        </small>
      ) : null}
    </div>
  );
};

const EnvioDaMontagem: React.FC<PropsDoEnvio> = (p) => {
  const m = p.montagem;
  const comCenas = m.fonteDoFundo === 'cenas';
  const fundo = comCenas ? null : p.fundo;
  const fala = falaEfetiva(m, fundo, p.pessoa, p.audios);
  const mudos = [semSom(fundo) ? 'o vídeo de fundo' : '',
    m.porCima === 'pessoa' && semSom(p.pessoa) ? 'o vídeo da pessoa' : ''].filter(Boolean);
  const nenhumSom = fala !== 'audio' && fala !== 'voz' && semSom(fala === 'fundo' ? fundo : p.pessoa);
  const custo = p.pessoa ? p.pessoa.duracao * p.pessoa.fps * CUSTO_DO_RECORTE_POR_QUADRO : 0;
  return (
    <div className="camadas">
      <div className="camada">
        <strong>O fundo</strong>
        <div className="linha-de-opcoes" role="group" aria-label="de onde vem o fundo">
          {FONTES_DO_FUNDO.map(([v, nome]) => (
            <button key={v} type="button" className="pilula" aria-pressed={m.fonteDoFundo === v}
              onClick={() => p.mudarMontagem({fonteDoFundo: v})}>{nome}</button>
          ))}
        </div>
        {comCenas ? (
          <>
            <small>
              A pasta com os clipes e a matriz que descreve cada um (o <code>cenas.json</code>). O Gemini escolhe as
              cenas pelo que é dito; sem ele, as palavras escolhem.
            </small>
            <SoltarPasta progresso={p.enviandoBiblioteca} aoEscolher={p.aoEscolherPasta} />
            {p.faltaMatriz || p.biblioteca ? (
              <Soltar nome="matriz" rotulo={p.biblioteca ? 'Trocar a matriz' : 'Agora, a matriz'}
                dica="o cenas.json: uma lista com o arquivo e a descrição de cada cena" aceita=".json,application/json"
                progresso={null} aoEscolher={p.aoEscolherMatriz} />
            ) : null}
            {p.faltaMatriz || p.biblioteca ? <GerarMatriz {...p} /> : null}
            <Aviso texto={p.erro.biblioteca} />
            {p.biblioteca ? <FichaDaBiblioteca b={p.biblioteca} /> : null}
            {p.revisao && p.bibliotecaId ? (
              <RevisaoDaMatriz biblioteca={p.bibliotecaId} linhas={p.revisao.linhas} por={p.revisao.por}
                aviso={p.revisao.aviso} pedidos={p.revisao.pedidos} salvando={p.salvandoMatriz}
                aoUsar={p.aoUsarMatriz} aoFechar={p.aoFecharRevisao} />
            ) : null}
          </>
        ) : (
          <>
            <small>Sem pessoa: a tela gravada, o jogo, os slides.</small>
            <Soltar nome="fundo" rotulo="Arraste o fundo aqui" dica="ou clique · MP4, MOV, MKV, WebM…"
              aceita="video/*,.mkv,.mov" progresso={p.progresso.fundo} aoEscolher={(f) => p.aoEscolher('fundo', f)} />
            <Aviso texto={p.erro.fundo} />
            {p.fundo ? <FichaDoVideo video={p.fundo} rotulo="dados do fundo" /> : null}
          </>
        )}
      </div>

      <div className="camada">
        <strong>Por cima</strong>
        <div className="linha-de-opcoes" role="group" aria-label="o que vai por cima">
          {POR_CIMA.map(([v, nome]) => (
            <button key={v} type="button" className="pilula" aria-pressed={m.porCima === v}
              onClick={() => p.mudarMontagem({porCima: v})}>{nome}</button>
          ))}
        </div>
        {m.porCima === 'nada' ? <small>Só o fundo, com a legenda e as animações por cima.</small> : null}
        {m.porCima === 'pessoa' ? (
          <>
            <Soltar nome="pessoa" rotulo="Arraste o vídeo da pessoa" dica="você falando · MP4, MOV, WebM…"
              aceita="video/*,.mkv,.mov,.webm" progresso={p.progresso.pessoa}
              aoEscolher={(f) => p.aoEscolher('pessoa', f)} />
            <Aviso texto={p.erro.pessoa} />
            {p.pessoa ? (
              <>
                <FichaDoVideo video={p.pessoa} rotulo="dados do vídeo da pessoa" />
                <div className="campo">
                  <span>Tirar o fundo da pessoa</span>
                  <div className="linha-de-opcoes" role="group" aria-label="como tirar o fundo da pessoa">
                    <button type="button" className="pilula" aria-pressed={m.recorte === 'transparente'}
                      disabled={!p.pessoa.tem_alfa} onClick={() => p.mudarMontagem({recorte: 'transparente'})}>
                      Já vem sem fundo
                    </button>
                    <button type="button" className="pilula" aria-pressed={m.recorte === 'modnet'}
                      onClick={() => p.mudarMontagem({recorte: 'modnet'})}>Recortar com o MODNet</button>
                  </div>
                  <small className="custo">
                    {m.recorte === 'transparente'
                      ? 'O arquivo tem transparência: o recorte é o dele, sem custo nenhum.'
                      : `Recorta o vídeo inteiro no seu computador: uns ${duracao(Math.max(5, custo))} a mais num `
                        + 'MacBook M5.'
                        + (p.recorte.baixado ? '' : ` Na primeira vez, o editor baixa o modelo (${p.recorte.tamanho}).`)
                        + (p.pessoa.tem_alfa ? ''
                          : ' Para não esperar, exporte o vídeo já sem fundo, em WebM VP9 ou MOV ProRes 4444.')}
                  </small>
                </div>
              </>
            ) : null}
          </>
        ) : m.porCima === 'personagem' ? (
          <>
            <Soltar nome="personagem" rotulo="Arraste o personagem" dica="GIF, PNG animado ou WebP, em loop"
              aceita="image/gif,image/png,image/webp,.gif,.png,.webp,.apng" progresso={p.progresso.personagem}
              aoEscolher={(f) => p.aoEscolher('personagem', f)} />
            <Aviso texto={p.erro.personagem} />
            {p.personagem ? (
              <div className="personagem">
                <img src={api.personagemArquivoUrl(p.personagem.id)} alt={`o personagem ${p.personagem.nome}`} />
                <div className="ficha" aria-label="dados do personagem">
                  <span className="etiqueta">{p.personagem.nome}</span>
                  <span className="etiqueta">{p.personagem.largura}×{p.personagem.altura}</span>
                  <span className="etiqueta">{p.personagem.quadros} quadros</span>
                  <span className="etiqueta">{duracao(p.personagem.duracao)} em loop</span>
                  <span className="etiqueta">{p.personagem.tem_alfa ? 'transparente' : 'com fundo'}</span>
                </div>
                {!p.personagem.tem_alfa ? (
                  <Interruptor ligado={m.tirarFundo && p.personagem.fundo_de_cor} desabilitado={!p.personagem.fundo_de_cor}
                    aoMudar={(v) => p.mudarMontagem({tirarFundo: v})} titulo="Tirar o fundo de cor dele"
                    descricao={p.personagem.fundo_de_cor ? 'Os quatro cantos têm a mesma cor, e ela some.'
                      : 'Os cantos têm cores diferentes: não dá para saber qual é o fundo.'} />
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      <div className="camada">
        <strong>O áudio vem de</strong>
        <div className="linha-de-opcoes" role="group" aria-label="de onde vem o áudio">
          {opcoesDeFala(m).map((f) => {
            const mudo = f === 'fundo' ? semSom(fundo) : f === 'pessoa' ? semSom(p.pessoa) : false;
            return (
              <button key={f} type="button" className="pilula" aria-pressed={fala === f} disabled={mudo}
                title={mudo ? 'este vídeo não tem som' : undefined} onClick={() => p.mudarMontagem({fala: f})}>
                {NOMES_DA_FALA[f]}
              </button>
            );
          })}
        </div>
        <small>
          {nenhumSom ? 'Nenhum dos vídeos tem som: sem um áudio separado, o vídeo sai mudo, sem cortes e sem legenda.'
            : fala === 'audio' && !p.audios.length ? 'Envie o áudio: dele saem a legenda e os cortes.'
              : fala === 'voz' ? 'A sua voz, gravada uma vez, narra o roteiro. Da narração saem a legenda e os cortes.'
                : 'Dele saem a legenda e os cortes.'}
          {mudos.length && !nenhumSom ? ` Sem som: ${mudos.join(' e ')}.` : ''}
        </small>
        {fala === 'audio' ? (
          <>
            {p.audios.length ? (
              <div className="ficha" aria-label="os áudios separados">
                {p.audios.map((a, i) => (
                  <span key={a.id} className="etiqueta">{p.audios.length > 1 ? `${i + 1}. ` : ''}{a.nome} · {duracao(a.duracao)}</span>
                ))}
                <button type="button" className="botao pequeno" onClick={p.aoTirarAudio}>
                  {p.audios.length > 1 ? 'Trocar os áudios' : 'Trocar o áudio'}
                </button>
              </div>
            ) : null}
            <Soltar nome="audio" rotulo={p.audios.length ? 'Juntar mais áudios' : 'Arraste o áudio (ou vários)'}
              dica="MP3, WAV, M4A… Vários (um por parágrafo) tocam na ordem do nome, 0,3 s entre eles."
              aceita="audio/*,.mp3,.wav,.m4a" progresso={p.progresso.audio}
              aoEscolher={(f) => p.aoEscolherAudios([f])} aoEscolherVarios={p.aoEscolherAudios} />
          </>
        ) : fala === 'voz' ? <MinhaVoz narracao={p.narracao} aoNarrar={p.aoNarrar} /> : null}
        <Aviso texto={p.erro.audio} />
      </div>
    </div>
  );
};

/** Onde o vídeo vai ser postado: decide o formato da thumbnail e, na montagem, o do vídeo. */
const OndePostar: React.FC<PropsDoEnvio> = (p) => {
  const emPe = p.recomendadas.length > 0 && !p.recomendadas.includes('youtube');
  return (
    <div className="plataformas" id="plataformas">
      <strong>Onde você vai postar?</strong>
      <div className="linha-de-opcoes" role="group" aria-label="onde você vai postar">
        {ORDEM.map((pl) => (
          <button key={pl} type="button" className="pilula" aria-pressed={p.plataformas.includes(pl)}
            onClick={() => p.aoAlternarPlataforma(pl)}>
            {PLATAFORMAS[pl].nome}
            {p.recomendadas.includes(pl) ? <>{' '}<span className="recomendado">recomendado</span></> : null}
          </button>
        ))}
      </div>
      <small>
        {p.recomendadas.length
          ? `Para um vídeo ${emPe ? 'em pé' : 'deitado'}, o editor recomenda ${juntar(p.recomendadas.map((x) => PLATAFORMAS[x].nome))}. `
          : 'Envie o vídeo, e o editor recomenda pelo formato dele. '}
        Dá para marcar várias: a thumbnail sai no formato de cada uma{p.modo === 'montagem'
          ? ', e o vídeo montado também' : ''}.
      </small>
      {p.plataformas.includes('shorts') ? <small>{PLATAFORMAS.shorts.nota}</small> : null}
      {p.avisosDaPlataforma.map((a) => <div key={a} className="aviso">{a}</div>)}
    </div>
  );
};

export const PassoEnvio: React.FC<PropsDoEnvio> = (p) => (
  <section className="passo" id="passo-envio">
    <Cabeca n={1} titulo="Envie o vídeo"
      texto="Os arquivos são copiados para uma pasta do seu computador — não vão para a internet." />
    <div className="linha-de-opcoes modos" role="group" aria-label="como é o seu vídeo">
      <button type="button" className="pilula" aria-pressed={p.modo === 'um'} onClick={() => p.setModo('um')}>
        Um vídeo com você falando
      </button>
      <button type="button" className="pilula" aria-pressed={p.modo === 'montagem'}
        onClick={() => p.setModo('montagem')}>Um fundo e, por cima, você ou um personagem</button>
    </div>
    {p.modo === 'um' ? (
      <>
        <Soltar grande nome="video" rotulo="Arraste o vídeo aqui" dica="ou clique para escolher · MP4, MOV, MKV, WebM…"
          aceita="video/*,.mkv,.mov" progresso={p.progresso.video} aoEscolher={(f) => p.aoEscolher('video', f)} />
        <Aviso texto={p.erro.video} />
        {p.video ? <FichaDoVideo video={p.video} /> : null}
      </>
    ) : (
      <EnvioDaMontagem {...p} />
    )}
    <OndePostar {...p} />
  </section>
);

// ── 2. Edições ───────────────────────────────────────────────────────────

const VOZES: [Voz, string, string][] = [
  ['original', 'Original', 'A voz como foi gravada.'],
  ['limpa', 'Limpa', 'Tira o grave, o eco do cômodo e o chiado, e deixa cada parte no mesmo volume.'],
  ['estudio', 'Estúdio', 'A limpa, mais o brilho, a compressão e a voz aberta em estéreo (a do preset de notícia).'],
];

export const PassoEdicoes: React.FC<{
  edicao: Edicao; mudar: (p: Partial<Edicao>) => void;
  /** Na montagem, o que vai por cima (e pode mudar de lugar); ``null`` no vídeo único. */
  porCima: PorCima | null;
  presets: Preset[];
  /** O preset que bate com a tela; ``null`` é "Personalizado". */
  marcado: string | null;
  aoEscolherPreset: (p: Preset) => void;
  /** Os presets de quem usa: salvar o que está na tela, apagar e importar. */
  aoSalvarPreset: (titulo: string, frase: string, substituir: boolean) => Promise<void>;
  aoApagarPreset: (p: Preset) => Promise<void>;
  aoImportarPresets: (arquivo: File) => Promise<PresetsImportados>;
  temas: Record<string, string>;
  /** Na montagem, a janela com a câmera vale. */
  naMontagem: boolean;
}> = ({edicao, mudar, porCima, presets, marcado, aoEscolherPreset, aoSalvarPreset, aoApagarPreset,
  aoImportarPresets, temas, naMontagem}) => {
  const tocando = useRef<HTMLAudioElement | null>(null);
  const [salvando, setSalvando] = useState<{titulo: string; frase: string; conflito: boolean; erro: string} | null>(
    null);
  const [importado, setImportado] = useState<{texto: string; erro: boolean} | null>(null);
  const salvar = async (substituir: boolean) => {
    if (!salvando) return;
    // O que a página já sabe, ela diz na hora (o servidor confere de novo).
    const nome = apelido(salvando.titulo);
    if (presets.some((p) => !p.meu && (p.nome === nome || apelido(p.titulo) === nome))) {
      setSalvando({...salvando, erro: `“${salvando.titulo.trim()}” é o nome de um preset pronto: escolha outro.`});
      return;
    }
    if (!substituir && presets.some((p) => p.meu && p.nome === nome)) {
      setSalvando({...salvando, conflito: true, erro: ''});
      return;
    }
    try {
      await aoSalvarPreset(salvando.titulo, salvando.frase, substituir);
      setSalvando(null);
    } catch (e) {
      const mensagem = (e as Error).message;
      setSalvando({...salvando, conflito: mensagem.startsWith('Já existe'), erro: mensagem.startsWith('Já existe') ? '' : mensagem});
    }
  };
  const importar = async (arquivo: File) => {
    try {
      const r = await aoImportarPresets(arquivo);
      const partes = [r.entraram.length ? `Entraram: ${r.entraram.join(', ')}.` : 'Nenhum preset entrou.'];
      if (r.recusados.length) partes.push(`Ficaram de fora: ${r.recusados.join('; ')}.`);
      setImportado({texto: partes.join(' '), erro: !r.entraram.length});
    } catch (e) {
      setImportado({texto: (e as Error).message, erro: true});
    }
  };
  const ouvir = () => {
    tocando.current?.pause();
    const som = new Audio(api.somDoTemaUrl(edicao.tema_dos_sons, edicao.volume_dos_sons));
    tocando.current = som;
    som.play().catch(() => undefined);
  };
  return (
    <section className="passo" id="passo-edicoes">
      <Cabeca n={2} titulo="Escolha as edições"
        texto="Comece por um preset e ajuste o que quiser. Tudo é decidido por regras, no seu computador; só os cartões animados, as cenas da biblioteca e os destaques da legenda pedem o Gemini." />
      <div className="presets" role="group" aria-label="presets de edição">
        {presets.map((p) => (p.meu ? (
          <div key={p.nome} className="preset-meu">
            <button type="button" className="preset meu" aria-pressed={marcado === p.nome}
              onClick={() => aoEscolherPreset(p)}>
              <strong>{p.titulo} <span className="selo-meu">seu</span></strong>
              <small>{p.frase}</small>
            </button>
            <button type="button" className="apagar-preset" aria-label={`apagar o preset ${p.titulo}`}
              title="Apagar este preset"
              onClick={() => aoApagarPreset(p).catch((e: Error) => setImportado({texto: e.message, erro: true}))}>
              ×
            </button>
          </div>
        ) : (
          <button key={p.nome} type="button" className="preset" aria-pressed={marcado === p.nome}
            onClick={() => aoEscolherPreset(p)}>
            <strong>{p.titulo}</strong>
            <small>{p.frase}</small>
          </button>
        )))}
        <div className={`preset personalizado${marcado === null ? ' marcado' : ''}`}
          aria-current={marcado === null ? 'true' : undefined}>
          <strong>Personalizado</strong>
          <small>Vira este quando você muda algum valor de um preset.</small>
          {marcado === null ? (
            <button type="button" className="botao pequeno salvar-preset" disabled={salvando !== null}
              onClick={() => setSalvando({titulo: '', frase: '', conflito: false, erro: ''})}>
              Salvar como preset
            </button>
          ) : null}
        </div>
      </div>
      {salvando ? (
        <form className="novo-preset" aria-label="salvar como preset" onSubmit={(e) => {
          e.preventDefault();
          void salvar(false);
        }}>
          <label className="campo">
            <span>Nome do preset</span>
            <input type="text" value={salvando.titulo} maxLength={40} autoFocus placeholder="Meu vlog"
              onChange={(e) => setSalvando({...salvando, titulo: e.target.value, conflito: false, erro: ''})} />
          </label>
          <label className="campo">
            <span>Frase (opcional)</span>
            <input type="text" value={salvando.frase} maxLength={160} placeholder="Para que tipo de vídeo ele serve"
              onChange={(e) => setSalvando({...salvando, frase: e.target.value})} />
          </label>
          <small>
            Ele guarda as edições, a saída e o modelo e a cor da thumbnail que estão na tela, e fica só neste
            computador, na pasta do seu usuário.
          </small>
          {salvando.conflito ? (
            <div className="aviso">Já existe um preset seu com esse nome. Substituir pelo que está na tela?</div>
          ) : null}
          {salvando.erro ? <div className="aviso erro">{salvando.erro}</div> : null}
          <div className="linha-de-opcoes">
            {salvando.conflito ? (
              <button type="button" className="botao pequeno usar" onClick={() => void salvar(true)}>Substituir</button>
            ) : (
              <button type="submit" className="botao pequeno usar" disabled={!salvando.titulo.trim()}>Salvar</button>
            )}
            <button type="button" className="botao pequeno" onClick={() => setSalvando(null)}>Cancelar</button>
          </div>
        </form>
      ) : null}
      <div className="presets-meus">
        <small>Os seus presets ficam só neste computador.</small>
        {presets.some((p) => p.meu) ? (
          <a className="link" href={api.exportarPresetsUrl()} download="meus-presets.json">Exportar os seus</a>
        ) : null}
        <label className="link">
          Importar
          <input type="file" accept=".json,application/json" hidden aria-label="importar presets"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = '';
              if (f) void importar(f);
            }} />
        </label>
      </div>
      {importado ? <div className={`aviso${importado.erro ? ' erro' : ''}`} role="status">{importado.texto}</div> : null}
      <div className="grade">
        <Interruptor ligado={edicao.cortes} aoMudar={(v) => mudar({cortes: v})} titulo="Cortar silêncios"
          descricao="Tira as pausas longas entre as frases. A legenda acompanha o corte." />
        <Interruptor ligado={edicao.zoom} aoMudar={(v) => mudar({zoom: v})} titulo="Zoom de ênfase"
          descricao="Aproxima e afasta nos cortes, e dá um empurrão nas palavras que saltam." />
        <Interruptor ligado={edicao.adesivos} aoMudar={(v) => mudar({adesivos: v})} titulo="Palavras que saltam"
          descricao="Números e nomes saltam da legenda num adesivo colorido." />
        <Interruptor ligado={edicao.icones} aoMudar={(v) => mudar({icones: v})} titulo="Ícones automáticos"
          descricao="Quando a fala cita “dinheiro”, “celular”, “foguete”… o ícone aparece." />
        {porCima && porCima !== 'nada' ? (
          <Interruptor ligado={edicao.mover} aoMudar={(v) => mudar({mover: v})}
            titulo={porCima === 'personagem' ? 'Mover o personagem' : 'Mover a pessoa'}
            descricao="Em alguns cortes, vai para um lado, para o meio, para cima, para baixo, para perto ou para longe." />
        ) : null}
        {naMontagem ? (
          <Interruptor ligado={edicao.janela} aoMudar={(v) => mudar({janela: v})} titulo="Janela e câmera"
            descricao="A cena numa janela 16:9 que cresce e encolhe, com a câmera empurrando, e o personagem em pé na borda dela." />
        ) : null}
        <Interruptor ligado={edicao.animacoes} aoMudar={(v) => mudar({animacoes: v})} titulo="Cartões animados"
          descricao="Selo, lista, quadro, enquete, carimbo, número e flash, escritos pelo Gemini na palavra certa. Precisa da chave dele (passo 5)." />
      </div>
      <div className="campos">
        <div className="campo largo">
          <span id="rotulo-voz">Voz</span>
          <div className="linha-de-opcoes" role="group" aria-labelledby="rotulo-voz">
            {VOZES.map(([v, nome]) => (
              <button key={v} type="button" className="pilula" aria-pressed={edicao.voz === v}
                onClick={() => mudar({voz: v})}>{nome}</button>
            ))}
          </div>
          <small>{VOZES.find(([v]) => v === edicao.voz)?.[2]}</small>
        </div>
        <label className="campo largo">
          <span>Bipe nas palavras</span>
          <input type="text" value={edicao.bipe} maxLength={500} placeholder="cocaína, sexo, decapitação"
            onChange={(e) => mudar({bipe: e.target.value})} />
          <small>Separadas por vírgula. Uma sílaba vira bipe na voz e asteriscos na legenda: “coca**na”.</small>
        </label>
      </div>
      <div className="campos">
        <label className="campo">
          <span>Ritmo: {numero(edicao.ritmo, 1)}×</span>
          <input type="range" min={0.5} max={2} step={0.1} value={edicao.ritmo}
            onChange={(e) => mudar({ritmo: Number(e.target.value)})} />
          <small>Mais alto: mais adesivos, ícones, zooms e sons, mais perto um do outro.</small>
        </label>
        <label className="campo">
          <span>Pausa máxima: {numero(edicao.pausa_maxima, 2)} s</span>
          <input type="range" min={0.2} max={1.5} step={0.05} value={edicao.pausa_maxima}
            disabled={!edicao.cortes} onChange={(e) => mudar({pausa_maxima: Number(e.target.value)})} />
          <small>Pausas maiores que isto viram corte.</small>
        </label>
        <label className="campo">
          <span>Respiro no corte: {numero(edicao.respiro, 2)} s</span>
          <input type="range" min={0.05} max={0.4} step={0.05} value={edicao.respiro}
            disabled={!edicao.cortes} onChange={(e) => mudar({respiro: Number(e.target.value)})} />
          <small>O silêncio que fica no lugar da pausa cortada.</small>
        </label>
        <label className="campo">
          <span>Zoom: {numero((edicao.nivel_zoom - 1) * 100)}%</span>
          <input type="range" min={1} max={1.3} step={0.01} value={edicao.nivel_zoom}
            disabled={!edicao.zoom} onChange={(e) => mudar({nivel_zoom: Number(e.target.value)})} />
          <small>Quanto a câmera aproxima.</small>
        </label>
        <label className="campo">
          <span>Empurrão do adesivo: {numero(edicao.empurrao * 100)}%</span>
          <input type="range" min={0} max={0.15} step={0.01} value={edicao.empurrao}
            disabled={!edicao.zoom || !edicao.adesivos} onChange={(e) => mudar({empurrao: Number(e.target.value)})} />
          <small>O zoom rápido quando uma palavra salta.</small>
        </label>
        <label className="campo">
          <span>Centro do zoom (altura): {numero(edicao.ancora_y * 100)}%</span>
          <input type="range" min={0.1} max={0.9} step={0.01} value={edicao.ancora_y}
            disabled={!edicao.zoom} onChange={(e) => mudar({ancora_y: Number(e.target.value)})} />
          <small>40% fica no rosto de quem fala para a câmera.</small>
        </label>
      </div>
      <div className="sons">
        <div className="grade">
          <Interruptor ligado={edicao.sons} aoMudar={(v) => mudar({sons: v})} titulo="Efeitos sonoros"
            descricao="Um som quando algo aparece e outro quando o zoom troca ou a pessoa muda de lugar." />
          <Interruptor ligado={edicao.sons_por_palavra} aoMudar={(v) => mudar({sons_por_palavra: v})}
            titulo="Sons por palavra" desabilitado={!edicao.sons}
            descricao="“Dinheiro” toca moedas, “errado” uma buzina, “funcionou” um sino." />
          <Interruptor ligado={edicao.som_nos_cortes} aoMudar={(v) => mudar({som_nos_cortes: v})}
            titulo="Som em cada corte" desabilitado={!edicao.sons || !edicao.cortes}
            descricao="Um clique baixo em cada corte, no estilo dos vídeos de jogo." />
        </div>
        <div className="campos">
          <div className="campo">
            <span id="rotulo-tema">Tema dos sons</span>
            <div className="com-botao">
              <select aria-labelledby="rotulo-tema" value={edicao.tema_dos_sons} disabled={!edicao.sons}
                onChange={(e) => mudar({tema_dos_sons: e.target.value})}>
                {Object.entries(temas).map(([nome, titulo]) => <option key={nome} value={nome}>{titulo}</option>)}
              </select>
              <button type="button" className="botao pequeno" onClick={ouvir} disabled={!edicao.sons}>
                Ouvir
              </button>
            </div>
            <small>Sons da Kenney, em domínio público.</small>
          </div>
          <label className="campo">
            <span>Volume dos sons: {numero(edicao.volume_dos_sons * 100)}%</span>
            <input type="range" min={0.3} max={1.5} step={0.05} value={edicao.volume_dos_sons}
              disabled={!edicao.sons} onChange={(e) => mudar({volume_dos_sons: Number(e.target.value)})} />
            <small>A voz manda: os sons ficam sempre por baixo dela.</small>
          </label>
        </div>
      </div>
    </section>
  );
};

// ── 3. Legenda ───────────────────────────────────────────────────────────

/** As larguras de legenda oferecidas (os presets usam 14, 20 e 36). */
const LARGURAS = [10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 42];

const ESTILOS: [EstiloDaLegenda, string, string][] = [
  ['classica', 'Clássica', 'Uma linha por vez, em karaokê: a palavra-chave acende amarela.'],
  ['destaques', 'Destaques', 'Até 4 palavras que entram uma a uma, com os nomes em ciano, as expressões em rosa e '
    + 'a frase de efeito numa pílula amarela. Quem marca é o Gemini; sem ele, os nomes e os números.'],
];

const IDIOMAS: [string, string][] = [['pt', 'Português'], ['en', 'Inglês'], ['es', 'Espanhol'],
  ['fr', 'Francês'], ['it', 'Italiano'], ['de', 'Alemão']];

export const PassoLegenda: React.FC<{
  estado: Estado; edicao: Edicao; saida: Saida;
  mudar: (p: Partial<Edicao>) => void; mudarSaida: (p: Partial<Saida>) => void;
}> = ({estado, edicao, saida, mudar, mudarSaida}) => {
  const modelo = estado.modelos.find((m) => m.nome === edicao.modelo);
  return (
    <section className="passo" id="passo-legenda">
      <Cabeca n={3} titulo="Legenda"
        texto="A fala é transcrita no seu computador pelo Whisper, palavra por palavra." />
      <div className="campos">
        <label className="campo">
          <span>Idioma da fala</span>
          <select value={edicao.idioma} onChange={(e) => mudar({idioma: e.target.value})}>
            {IDIOMAS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </label>
        <label className="campo">
          <span>Modelo do Whisper</span>
          <select value={edicao.modelo} onChange={(e) => mudar({modelo: e.target.value})}>
            {estado.modelos.map((m) => (
              <option key={m.nome} value={m.nome}>
                {m.nome} · {m.tamanho}{m.baixado ? ' · baixado' : ''}
              </option>
            ))}
          </select>
          <small>{modelo && !modelo.baixado
            ? `Será baixado na primeira vez (${modelo.tamanho}).`
            : 'small é o equilíbrio; medium erra menos e é mais lento.'}</small>
        </label>
        <label className="campo">
          <span>Tamanho da letra: {numero(edicao.tamanho_legenda * 100)}%</span>
          <input type="range" min={0.6} max={1.6} step={0.05} value={edicao.tamanho_legenda}
            onChange={(e) => mudar({tamanho_legenda: Number(e.target.value)})} />
        </label>
        <div className="campo">
          <span id="rotulo-estilo">Estilo</span>
          <div className="linha-de-opcoes" role="group" aria-labelledby="rotulo-estilo">
            {ESTILOS.map(([v, nome]) => (
              <button key={v} type="button" className="pilula" aria-pressed={edicao.estilo_da_legenda === v}
                onClick={() => mudar({estilo_da_legenda: v})}>{nome}</button>
            ))}
          </div>
          <small>{ESTILOS.find(([v]) => v === edicao.estilo_da_legenda)?.[2]}</small>
        </div>
        <label className="campo">
          <span>Letras por linha</span>
          <select value={edicao.caracteres_por_linha ?? ''} disabled={edicao.estilo_da_legenda !== 'classica'}
            onChange={(e) => mudar({caracteres_por_linha: e.target.value ? Number(e.target.value) : null})}>
            <option value="">Automático</option>
            {LARGURAS.map((n) => <option key={n} value={n}>Até {n}</option>)}
          </select>
          <small>Automático: até 18 em pé e 32 deitado. Menos letras, menos palavras por vez.</small>
        </label>
      </div>
      <div className="grade" style={{marginTop: 14}}>
        <Interruptor ligado={saida.srt} aoMudar={(v) => mudarSaida({srt: v})} titulo="Arquivo .srt"
          descricao="A legenda à parte, para subir no YouTube ou editar." />
        <Interruptor ligado={saida.vtt} aoMudar={(v) => mudarSaida({vtt: v})} titulo="Arquivo .vtt"
          descricao="O mesmo, no formato da web." />
      </div>
    </section>
  );
};

// ── 4. Saída ─────────────────────────────────────────────────────────────

const NOMES_FORMATO: Record<string, string> = {mp4: 'MP4', mov: 'MOV', webm: 'WebM', mkv: 'MKV', gif: 'GIF'};
const NOMES_RESOLUCAO: Record<string, string> = {original: 'Original', '2160p': '4K', '1440p': '1440p',
  '1080p': '1080p', '720p': '720p', '480p': '480p'};
const NOMES_QUALIDADE: Record<string, string> = {alta: 'Alta', equilibrada: 'Equilibrada', leve: 'Leve'};

function ladoCurto(video: VideoInfo | null) {
  return video ? Math.min(video.largura, video.altura) : Infinity;
}

const FORMATOS_DO_QUADRO: [FormatoDoQuadro, string][] = [['fundo', 'Igual ao fundo'], ['vertical', 'Em pé (9:16)'],
  ['horizontal', 'Deitado (16:9)'], ['quadrado', 'Quadrado']];

export const PassoSaida: React.FC<{
  estado: Estado; saida: Saida; video: VideoInfo | null; mudar: (p: Partial<Saida>) => void;
  /** Na montagem, o formato do quadro final (o fundo é encaixado nele). */
  quadro?: {valor: FormatoDoQuadro; mudar: (f: FormatoDoQuadro) => void} | null;
}> = ({estado, saida, video, mudar, quadro}) => {
  const formatos = Object.keys(estado.formatos);
  const codecs = estado.formatos[saida.formato]?.codecs ?? [];
  const curto = ladoCurto(video);
  const escolherFormato = (f: string) => {
    const lista = estado.formatos[f]?.codecs ?? [];
    mudar({formato: f, codec: lista.includes(saida.codec) ? saida.codec : (lista[0] ?? ''), audio: ''});
  };
  return (
    <section className="passo" id="passo-saida">
      <Cabeca n={4} titulo="Saída"
        texto="Só aparece o que este computador consegue gravar." />
      {quadro ? (
        <div className="campo">
          <span>Formato do quadro</span>
          <div className="linha-de-opcoes" role="group" aria-label="formato do quadro">
            {FORMATOS_DO_QUADRO.map(([f, nome]) => (
              <button key={f} type="button" className="pilula" aria-pressed={quadro.valor === f}
                onClick={() => quadro.mudar(f)}>{nome}</button>
            ))}
          </div>
          <small>O fundo entra inteiro, e as sobras ficam com ele mesmo, desfocado.</small>
        </div>
      ) : null}
      <div className="campo">
        <span>Formato</span>
        <div className="linha-de-opcoes" role="group" aria-label="formato">
          {formatos.map((f) => (
            <button key={f} type="button" className="pilula" aria-pressed={saida.formato === f}
              onClick={() => escolherFormato(f)}>{NOMES_FORMATO[f] ?? f}</button>
          ))}
        </div>
      </div>
      {saida.formato === 'gif' ? (
        <div className="aviso">GIF sai sem som, com até {estado.gif_max_s} s, 15 quadros por segundo e no máximo 480 px no lado curto.</div>
      ) : null}
      <div className="campos">
        <label className="campo">
          <span>Codec</span>
          <select value={saida.codec || codecs[0]} disabled={codecs.length < 2}
            onChange={(e) => mudar({codec: e.target.value})}>
            {codecs.map((c) => <option key={c} value={c}>{estado.codecs[c] ?? c}</option>)}
          </select>
        </label>
        <label className="campo">
          <span>Resolução</span>
          <select value={saida.resolucao} onChange={(e) => mudar({resolucao: e.target.value})}
            disabled={saida.formato === 'gif'}>
            {estado.resolucoes.map((r) => {
              const alvo = r === 'original' ? 0 : Number(r.replace('p', ''));
              const maior = alvo > curto;
              return (
                <option key={r} value={r} disabled={maior}>
                  {NOMES_RESOLUCAO[r] ?? r}{maior ? ' (maior que o original)' : ''}
                </option>
              );
            })}
          </select>
        </label>
        <label className="campo">
          <span>Quadros por segundo</span>
          <select value={saida.fps} onChange={(e) => mudar({fps: e.target.value})}
            disabled={saida.formato === 'gif'}>
            {estado.fps.map((f) => <option key={f} value={f}>{f === 'original' ? 'Original' : `${f} fps`}</option>)}
          </select>
        </label>
        <label className="campo">
          <span>Qualidade</span>
          <select value={saida.qualidade} onChange={(e) => mudar({qualidade: e.target.value})}>
            {estado.qualidades.map((q) => <option key={q} value={q}>{NOMES_QUALIDADE[q] ?? q}</option>)}
          </select>
          <small>Alta é a melhor imagem; leve é o arquivo menor.</small>
        </label>
      </div>
    </section>
  );
};
