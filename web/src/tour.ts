/**
 * O tour guiado: os dois jeitos de usar e, depois, um passo por área da página (nove ao
 * todo). Abre sozinho na primeira visita e o botão "Tour" do topo refaz.
 *
 * O balão abre ao lado do cartão (à direita na coluna das opções, à esquerda no
 * painel): por cima, ele cobria justamente as opções que estava explicando.
 */
import {driver} from 'driver.js';
import 'driver.js/dist/driver.css';

const VISTO = 'editor-tour-visto';

export function comecarTour(): void {
  const tour = driver({
    showProgress: true,
    progressText: '{{current}} de {{total}}',
    nextBtnText: 'Próximo',
    prevBtnText: 'Voltar',
    doneBtnText: 'Começar a editar',
    popoverClass: 'tour-editor',
    smoothScroll: true,
    allowClose: true,
    steps: [
      {
        popover: {
          title: 'Dois jeitos de usar',
          description: '<b>Um vídeo seu falando:</b> arraste o vídeo e escolha um preset. Sai cortado, legendado, com zoom, sons e thumbnail.<br><br>'
            + '<b>Uma notícia montada com cenas:</b> traga a pasta das cenas (com a matriz <code>cenas.json</code>), o áudio da narração (um ou vários arquivos, ou só o roteiro, lido pela <b>Minha voz</b>) e, se quiser, um personagem em GIF. Escolha o preset <b>Notícia com cenas</b>: o Gemini escolhe as cenas, escreve os cartões e marca a legenda.<br><br>'
            + 'Tudo roda no seu computador. O Gemini é opcional e só entra com a sua chave (passo 5).',
        },
      },
      {
        element: '#passo-envio',
        popover: {
          side: 'right',
          align: 'start',
          title: '1. Envie o vídeo',
          description: '<b>Um vídeo com você falando</b>, vertical ou horizontal. Ou <b>um fundo e, por cima…</b>, em camadas:<br>'
            + '• <b>o fundo:</b> um vídeo, ou a <b>biblioteca de cenas</b>: arraste a pasta, e a matriz <code>cenas.json</code> que estiver dentro entra junto. Sem matriz, o botão <b>Gerar a matriz</b> pede ao Gemini a descrição de cada cena, e você revisa numa tabela;<br>'
            + '• <b>por cima:</b> o vídeo da pessoa, um personagem animado (GIF) ou nada;<br>'
            + '• <b>o áudio:</b> do vídeo, arquivos separados (um por parágrafo, que tocam na ordem do nome) ou a <b>Minha voz</b>: você lê um texto de 2 minutos uma vez, e a sua voz narra qualquer roteiro. Ela é opcional e se instala à parte, por um botão.<br>'
            + 'Os arquivos são copiados para uma pasta do seu computador.',
        },
      },
      {
        element: '#plataformas',
        popover: {
          side: 'right',
          align: 'start',
          title: 'Onde você vai postar',
          description: 'Marque uma ou várias plataformas. O editor recomenda pelo formato do vídeo, a thumbnail sai no tamanho de cada uma e, na montagem, o vídeo sai em pé (Shorts, TikTok, Reels) ou deitado (YouTube).',
        },
      },
      {
        element: '#passo-edicoes',
        popover: {
          side: 'right',
          align: 'start',
          title: '2. Escolha as edições',
          description: 'Comece por um preset e ajuste o que quiser; do jeito que ficar, ele vira um preset seu com <b>Salvar como preset</b>. O <b>Notícia com cenas</b> liga a janela com câmera (o personagem na borda da cena), os cartões animados, a voz de estúdio, o bipe nas palavras da lista e os sons do tema Notícia. Os outros cuidam de cortes, zoom, palavras que saltam, ícones e sons; o botão Ouvir toca cada tema.',
        },
      },
      {
        element: '#passo-legenda',
        popover: {
          side: 'right',
          align: 'start',
          title: '3. Legenda',
          description: 'O idioma da fala e o tamanho do Whisper, que transcreve no seu computador (o medium erra menos e demora mais). O estilo: <b>clássica</b>, uma linha em karaokê, ou <b>destaques</b>, até 4 palavras com cores e a frase de efeito numa pílula amarela. Dá para levar a legenda à parte em .srt e .vtt.',
        },
      },
      {
        element: '#passo-saida',
        popover: {
          side: 'right',
          align: 'start',
          title: '4. Saída',
          description: 'Formato (MP4, MOV, WebM, MKV, GIF), codec, resolução, quadros por segundo e qualidade. Só aparece o que este computador grava.',
        },
      },
      {
        element: '#passo-thumb',
        popover: {
          side: 'right',
          align: 'start',
          title: '5. Thumbnail e Gemini',
          description: 'Uma capa separada, com a pessoa recortada, a chamada e a palavra em destaque, no formato de cada plataforma; o botão Baixar entrega a capa como está. Aqui também fica a <b>chave do Gemini</b> (grátis, opcional): com ela, a IA sugere 3 capas e escreve o roteiro da montagem (as cenas, os cartões e as cores da legenda).',
        },
      },
      {
        element: '#botao-editar',
        popover: {
          side: 'left',
          align: 'start',
          title: '6. Editar',
          description: 'Começa a edição. A barra mostra cada etapa e quanto falta. Marque "só os primeiros 15 s" para testar o estilo rapidinho.',
        },
      },
      {
        element: '#passo-resultado',
        popover: {
          side: 'left',
          align: 'start',
          title: '7. Resultado',
          description: 'Assista, baixe o vídeo, as legendas e as thumbnails, ou abra a pasta onde tudo foi salvo. Com o roteiro do Gemini, ele diz quantas cenas e cartões vieram e quantos pedidos da cota foram usados.',
        },
      },
    ],
    onDestroyed: () => {
      try {
        localStorage.setItem(VISTO, '1');
      } catch {
        /* sem armazenamento: o tour só volta pelo botão */
      }
    },
  });
  tour.drive();
}

export function tourJaVisto(): boolean {
  try {
    return localStorage.getItem(VISTO) === '1';
  } catch {
    return true;
  }
}
