/**
 * De onde vem o áudio da montagem: do vídeo de fundo, do vídeo da pessoa ou de um áudio
 * separado. Com o personagem, que não tem som, só do fundo ou do separado.
 *
 * A escolha de quem edita vale enquanto ela fizer sentido. Sem escolha (ou com uma que
 * não serve mais, como "a pessoa" depois de trocar para o personagem), vale a primeira
 * que tem som: a pessoa, o fundo, o áudio separado. Sem som em lugar nenhum, o fundo: o
 * vídeo sai mudo, sem cortes e sem legenda.
 */
import type {AudioInfo, Fala, MontagemConfig, VideoInfo} from './tipos';

/** Se um vídeo enviado não tem som (o que ainda não foi enviado pode ter). */
export const semSom = (v: VideoInfo | null) => Boolean(v && !v.tem_audio);

export function opcoesDeFala(m: MontagemConfig): Fala[] {
  return m.porCima === 'pessoa' ? ['fundo', 'pessoa', 'audio'] : ['fundo', 'audio'];
}

export function falaEfetiva(m: MontagemConfig, fundo: VideoInfo | null, pessoa: VideoInfo | null,
                            audio: AudioInfo | null): Fala {
  const pode = (f: Fala) => opcoesDeFala(m).includes(f)
    && (f === 'fundo' ? !semSom(fundo) : f === 'pessoa' ? !semSom(pessoa) : true);
  if (m.fala && pode(m.fala)) return m.fala;
  if (m.porCima === 'pessoa' && pessoa?.tem_audio) return 'pessoa';
  if (fundo?.tem_audio) return 'fundo';
  if (audio) return 'audio';
  return 'fundo';
}
