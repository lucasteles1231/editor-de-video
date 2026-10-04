/**
 * Os quatro primeiros passos: enviar, edições, legenda e saída.
 */
import React, {useRef, useState} from 'react';
import {api} from '../api';
import {falaEfetiva, opcoesDeFala, semSom} from '../fala';
import {bytes, duracao, numero} from '../formatar';
import type {
  AudioInfo, Edicao, Estado, Fala, FormatoDoQuadro, Modo, MontagemConfig, PersonagemInfo, PorCima, Preset, Saida,
  VideoInfo,
} from '../tipos';
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

/** O que se envia: o vídeo único ou uma das camadas da montagem. */
export type Envio = 'video' | 'fundo' | 'pessoa' | 'personagem' | 'audio';

/** O custo de recortar a pessoa no vídeo inteiro pelo MODNet, medido num Apple M5 em
 *  04/10/2026: uns 0,07 s por quadro (um vídeo de 27 s a 25 fps levou uns 31 s a mais). */
const CUSTO_DO_RECORTE_POR_QUADRO = 0.07;

const Soltar: React.FC<{
  rotulo: string; dica: string; aceita: string; progresso: number | null;
  aoEscolher: (arquivo: File) => void; grande?: boolean; nome: string;
}> = ({rotulo, dica, aceita, progresso, aoEscolher, grande, nome}) => {
  const entrada = useRef<HTMLInputElement>(null);
  const [arrastando, setArrastando] = useState(false);
  const soltar = (e: React.DragEvent) => {
    e.preventDefault();
    setArrastando(false);
    const arquivo = e.dataTransfer.files?.[0];
    if (arquivo) aoEscolher(arquivo);
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
      <input ref={entrada} type="file" accept={aceita} hidden
        onChange={(e) => e.target.files?.[0] && aoEscolher(e.target.files[0])} />
    </div>
  );
};

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
  audio: AudioInfo | null;
  montagem: MontagemConfig;
  mudarMontagem: (p: Partial<MontagemConfig>) => void;
  progresso: Record<Envio, number | null>;
  erro: Record<Envio, string>;
  aoEscolher: (qual: Envio, arquivo: File) => void;
  aoTirarAudio: () => void;
  recorte: {baixado: boolean; tamanho: string};
};

const Aviso: React.FC<{texto: string}> = ({texto}) => (texto ? <div className="aviso erro">{texto}</div> : null);

const NOMES_DA_FALA: Record<Fala, string> = {fundo: 'O vídeo de fundo', pessoa: 'O vídeo da pessoa',
  audio: 'Um áudio separado'};

const EnvioDaMontagem: React.FC<PropsDoEnvio> = (p) => {
  const m = p.montagem;
  const fala = falaEfetiva(m, p.fundo, p.pessoa, p.audio);
  const mudos = [semSom(p.fundo) ? 'o vídeo de fundo' : '',
    m.porCima === 'pessoa' && semSom(p.pessoa) ? 'o vídeo da pessoa' : ''].filter(Boolean);
  const nenhumSom = fala !== 'audio' && semSom(fala === 'fundo' ? p.fundo : p.pessoa);
  const custo = p.pessoa ? p.pessoa.duracao * p.pessoa.fps * CUSTO_DO_RECORTE_POR_QUADRO : 0;
  return (
    <div className="camadas">
      <div className="camada">
        <strong>O vídeo de fundo</strong>
        <small>Sem pessoa: a tela gravada, o jogo, os slides.</small>
        <Soltar nome="fundo" rotulo="Arraste o fundo aqui" dica="ou clique · MP4, MOV, MKV, WebM…"
          aceita="video/*,.mkv,.mov" progresso={p.progresso.fundo} aoEscolher={(f) => p.aoEscolher('fundo', f)} />
        <Aviso texto={p.erro.fundo} />
        {p.fundo ? <FichaDoVideo video={p.fundo} rotulo="dados do fundo" /> : null}
      </div>

      <div className="camada">
        <strong>Por cima</strong>
        <div className="linha-de-opcoes" role="group" aria-label="o que vai por cima">
          {([['pessoa', 'Vídeo da pessoa'], ['personagem', 'Personagem animado']] as [PorCima, string][]).map(([v, nome]) => (
            <button key={v} type="button" className="pilula" aria-pressed={m.porCima === v}
              onClick={() => p.mudarMontagem({porCima: v})}>{nome}</button>
          ))}
        </div>
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
        ) : (
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
        )}
      </div>

      <div className="camada">
        <strong>O áudio vem de</strong>
        <div className="linha-de-opcoes" role="group" aria-label="de onde vem o áudio">
          {opcoesDeFala(m).map((f) => {
            const mudo = f === 'fundo' ? semSom(p.fundo) : f === 'pessoa' ? semSom(p.pessoa) : false;
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
            : fala === 'audio' && !p.audio ? 'Envie o áudio: dele saem a legenda e os cortes.'
              : 'Dele saem a legenda e os cortes.'}
          {mudos.length && !nenhumSom ? ` Sem som: ${mudos.join(' e ')}.` : ''}
        </small>
        {fala === 'audio' ? (p.audio ? (
          <div className="ficha" aria-label="dados do áudio separado">
            <span className="etiqueta">{p.audio.nome}</span>
            <span className="etiqueta">{duracao(p.audio.duracao)}</span>
            <button type="button" className="botao pequeno" onClick={p.aoTirarAudio}>Trocar o áudio</button>
          </div>
        ) : (
          <Soltar nome="audio" rotulo="Arraste o áudio" dica="MP3, WAV, M4A…" aceita="audio/*,.mp3,.wav,.m4a"
            progresso={p.progresso.audio} aoEscolher={(f) => p.aoEscolher('audio', f)} />
        )) : null}
        <Aviso texto={p.erro.audio} />
      </div>
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
  </section>
);

// ── 2. Edições ───────────────────────────────────────────────────────────

export const PassoEdicoes: React.FC<{
  edicao: Edicao; mudar: (p: Partial<Edicao>) => void;
  /** Na montagem, o que vai por cima (e pode mudar de lugar); ``null`` no vídeo único. */
  porCima: PorCima | null;
  presets: Preset[];
  /** O preset que bate com a tela; ``null`` é "Personalizado". */
  marcado: string | null;
  aoEscolherPreset: (p: Preset) => void;
  temas: Record<string, string>;
}> = ({edicao, mudar, porCima, presets, marcado, aoEscolherPreset, temas}) => {
  const tocando = useRef<HTMLAudioElement | null>(null);
  const ouvir = () => {
    tocando.current?.pause();
    const som = new Audio(api.somDoTemaUrl(edicao.tema_dos_sons, edicao.volume_dos_sons));
    tocando.current = som;
    som.play().catch(() => undefined);
  };
  return (
    <section className="passo" id="passo-edicoes">
      <Cabeca n={2} titulo="Escolha as edições"
        texto="Comece por um preset e ajuste o que quiser. Tudo decidido por regras, sem IA na nuvem: o mesmo vídeo sai sempre igual." />
      <div className="presets" role="group" aria-label="presets de edição">
        {presets.map((p) => (
          <button key={p.nome} type="button" className="preset" aria-pressed={marcado === p.nome}
            onClick={() => aoEscolherPreset(p)}>
            <strong>{p.titulo}</strong>
            <small>{p.frase}</small>
          </button>
        ))}
        <div className={`preset personalizado${marcado === null ? ' marcado' : ''}`}
          aria-current={marcado === null ? 'true' : undefined}>
          <strong>Personalizado</strong>
          <small>Vira este quando você muda algum valor de um preset.</small>
        </div>
      </div>
      <div className="grade">
        <Interruptor ligado={edicao.cortes} aoMudar={(v) => mudar({cortes: v})} titulo="Cortar silêncios"
          descricao="Tira as pausas longas entre as frases. A legenda acompanha o corte." />
        <Interruptor ligado={edicao.zoom} aoMudar={(v) => mudar({zoom: v})} titulo="Zoom de ênfase"
          descricao="Aproxima e afasta nos cortes, e dá um empurrão nas palavras que saltam." />
        <Interruptor ligado={edicao.adesivos} aoMudar={(v) => mudar({adesivos: v})} titulo="Palavras que saltam"
          descricao="Números e nomes saltam da legenda num adesivo colorido." />
        <Interruptor ligado={edicao.icones} aoMudar={(v) => mudar({icones: v})} titulo="Ícones automáticos"
          descricao="Quando a fala cita “dinheiro”, “celular”, “foguete”… o ícone aparece." />
        {porCima ? (
          <Interruptor ligado={edicao.mover} aoMudar={(v) => mudar({mover: v})}
            titulo={porCima === 'personagem' ? 'Mover o personagem' : 'Mover a pessoa'}
            descricao="Em alguns cortes, vai para um lado, para o meio, para cima, para baixo, para perto ou para longe." />
        ) : null}
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
        <label className="campo">
          <span>Letras por linha</span>
          <select value={edicao.caracteres_por_linha ?? ''}
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
