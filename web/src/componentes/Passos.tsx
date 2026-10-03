/**
 * Os quatro primeiros passos: enviar, edições, legenda e saída.
 */
import React, {useRef, useState} from 'react';
import {bytes, duracao, numero} from '../formatar';
import type {Edicao, Estado, Saida, VideoInfo} from '../tipos';
import {Interruptor} from './Interruptor';

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

export const PassoEnvio: React.FC<{
  video: VideoInfo | null;
  progresso: number | null;
  erro: string;
  aoEscolher: (arquivo: File) => void;
}> = ({video, progresso, erro, aoEscolher}) => {
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastando, setArrastando] = useState(false);
  const soltar = (e: React.DragEvent) => {
    e.preventDefault();
    setArrastando(false);
    const arquivo = e.dataTransfer.files?.[0];
    if (arquivo) aoEscolher(arquivo);
  };
  return (
    <section className="passo" id="passo-envio">
      <Cabeca n={1} titulo="Envie o vídeo"
        texto="O arquivo é copiado para uma pasta do seu computador — não vai para a internet." />
      <div className={`envio${arrastando ? ' arrastando' : ''}`} role="button" tabIndex={0}
        onClick={() => entrada.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && entrada.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setArrastando(true); }}
        onDragLeave={() => setArrastando(false)} onDrop={soltar}>
        <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M14 3v4a1 1 0 0 0 1 1h4" />
          <path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z" />
          <path d="M10 11l4 2.5l-4 2.5z" />
        </svg>
        <strong>{progresso !== null ? `Enviando… ${numero(progresso * 100)}%` : 'Arraste o vídeo aqui'}</strong>
        <small>ou clique para escolher · MP4, MOV, MKV, WebM…</small>
        <input ref={entrada} type="file" accept="video/*,.mkv,.mov" hidden
          onChange={(e) => e.target.files?.[0] && aoEscolher(e.target.files[0])} />
      </div>
      {erro ? <div className="aviso erro">{erro}</div> : null}
      {video ? (
        <div className="ficha" aria-label="dados do vídeo">
          <span className="etiqueta">{video.nome}</span>
          <span className="etiqueta">{video.largura}×{video.altura}</span>
          <span className="etiqueta">{video.vertical ? 'vertical' : 'horizontal'}</span>
          <span className="etiqueta">{duracao(video.duracao)}</span>
          <span className="etiqueta">{numero(video.fps, video.fps % 1 ? 2 : 0)} fps</span>
          <span className="etiqueta">{bytes(video.tamanho_bytes)}</span>
          {!video.tem_audio ? <span className="etiqueta">sem áudio</span> : null}
        </div>
      ) : null}
    </section>
  );
};

// ── 2. Edições ───────────────────────────────────────────────────────────

export const PassoEdicoes: React.FC<{edicao: Edicao; mudar: (p: Partial<Edicao>) => void}> = ({edicao, mudar}) => (
  <section className="passo" id="passo-edicoes">
    <Cabeca n={2} titulo="Escolha as edições"
      texto="Tudo decidido por regras, sem IA na nuvem: o mesmo vídeo sai sempre igual." />
    <div className="grade">
      <Interruptor ligado={edicao.cortes} aoMudar={(v) => mudar({cortes: v})} titulo="Cortar silêncios"
        descricao="Tira as pausas longas entre as frases. A legenda acompanha o corte." />
      <Interruptor ligado={edicao.zoom} aoMudar={(v) => mudar({zoom: v})} titulo="Zoom de ênfase"
        descricao="Aproxima e afasta nos cortes, e dá um empurrão nas palavras que saltam." />
      <Interruptor ligado={edicao.adesivos} aoMudar={(v) => mudar({adesivos: v})} titulo="Palavras que saltam"
        descricao="Números e nomes saltam da legenda num adesivo colorido." />
      <Interruptor ligado={edicao.icones} aoMudar={(v) => mudar({icones: v})} titulo="Ícones automáticos"
        descricao="Quando a fala cita “dinheiro”, “celular”, “foguete”… o ícone aparece." />
      <Interruptor ligado={edicao.sons} aoMudar={(v) => mudar({sons: v})} titulo="Efeitos sonoros"
        descricao="Um pop quando algo aparece, um whoosh quando o zoom troca." />
    </div>
    <div className="campos">
      <label className="campo">
        <span>Pausa máxima: {numero(edicao.pausa_maxima, 2)} s</span>
        <input type="range" min={0.2} max={1.5} step={0.05} value={edicao.pausa_maxima}
          disabled={!edicao.cortes} onChange={(e) => mudar({pausa_maxima: Number(e.target.value)})} />
        <small>Pausas maiores que isto viram corte.</small>
      </label>
      <label className="campo">
        <span>Zoom: {numero((edicao.nivel_zoom - 1) * 100)}%</span>
        <input type="range" min={1} max={1.3} step={0.01} value={edicao.nivel_zoom}
          disabled={!edicao.zoom} onChange={(e) => mudar({nivel_zoom: Number(e.target.value)})} />
        <small>Quanto a câmera aproxima.</small>
      </label>
      <label className="campo">
        <span>Centro do zoom (altura): {numero(edicao.ancora_y * 100)}%</span>
        <input type="range" min={0.1} max={0.9} step={0.01} value={edicao.ancora_y}
          disabled={!edicao.zoom} onChange={(e) => mudar({ancora_y: Number(e.target.value)})} />
        <small>40% fica no rosto de quem fala para a câmera.</small>
      </label>
    </div>
  </section>
);

// ── 3. Legenda ───────────────────────────────────────────────────────────

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

export const PassoSaida: React.FC<{
  estado: Estado; saida: Saida; video: VideoInfo | null; mudar: (p: Partial<Saida>) => void;
}> = ({estado, saida, video, mudar}) => {
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
