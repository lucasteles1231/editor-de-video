# Terceiros

O código do editor-de-video é MIT (veja o [LICENSE](LICENSE)). Ele também usa
projetos de outras pessoas: alguns vão junto neste repositório, e outros são baixados
na instalação. A lista completa está aqui, com a licença de cada um.

## Vai junto neste repositório e no pacote

| O quê | Onde | Licença |
|---|---|---|
| Fonte **DejaVu Sans Bold** | `editor/recursos/DejaVuSans-Bold.ttf` | Bitstream Vera e domínio público: [`licencas/DejaVu-Fonts.txt`](licencas/DejaVu-Fonts.txt) |
| Fonte **Anton**, a da chamada da thumbnail | `editor/recursos/Anton-Regular.ttf` | SIL Open Font License 1.1: [`licencas/Anton-OFL.txt`](licencas/Anton-OFL.txt) |
| Fonte **Inter Black**, a da legenda em destaques (a instância de peso 900 do Google Fonts) | `editor/recursos/Inter-Black.ttf` | SIL Open Font License 1.1: [`licencas/Inter-OFL.txt`](licencas/Inter-OFL.txt) |
| 122 ícones do **Tabler Icons** 3.48.0 (e os da tabela do README) | `editor/recursos/icones.json` e `docs/img/funcoes/` | MIT: [`licencas/Tabler-Icons-MIT.txt`](licencas/Tabler-Icons-MIT.txt) |
| **React**, React DOM e scheduler | dentro da página montada (`editor/interface/estatico/`) | MIT: [`licencas/React-MIT.txt`](licencas/React-MIT.txt) |
| **driver.js** 1.9, o tour | dentro da página montada | MIT: [`licencas/driver.js-MIT.txt`](licencas/driver.js-MIT.txt) |
| **roughjs** 4.6, a seta e o círculo de caneta da thumbnail | dentro da página montada | MIT: [`licencas/roughjs-MIT.txt`](licencas/roughjs-MIT.txt) |
| **Remotion** 4 e `@remotion/player`, a prévia da thumbnail | dentro da página montada | Remotion License: [`licencas/Remotion-License.md`](licencas/Remotion-License.md) |
| 61 efeitos sonoros da **Kenney** (*Interface Sounds*, *Impact Sounds*, *UI Audio*, *Digital Audio*, *RPG Audio* e *Music Jingles*) | `editor/recursos/sons/` | Domínio público, CC0: [`licencas/Kenney-CC0.txt`](licencas/Kenney-CC0.txt) |
| 3 efeitos sonoros da biblioteca do **Remotion** (`remotion.media`): *Woosh*, de 1bob; *Mouse Click Sound*, de Pixeliota; e *DSLR Shutter fast 006*, de ristooooo1, todos do freesound.org | `editor/recursos/sons/remotion-*.wav` | Domínio público, CC0: [`licencas/Remotion-SFX-CC0.txt`](licencas/Remotion-SFX-CC0.txt) |
| A mão apontando do **Fluent UI Emoji**, da Microsoft (*backhand index pointing right*, em 3D e em vetor, nos seis tons) | `editor/recursos/maos/` | MIT: [`licencas/FluentUI-Emoji-MIT.txt`](licencas/FluentUI-Emoji-MIT.txt) |

### Sobre a licença do Remotion

O Remotion **não é MIT**. A licença dele é grátis para:

- pessoas físicas;
- empresas com até 3 funcionários;
- organizações sem fins lucrativos;
- quem ainda está avaliando, sem uso comercial.

Empresas maiores precisam de uma [Company License](https://www.remotion.pro/license).
Como o Remotion vai dentro da página do editor, isso vale para quem usa o editor numa
empresa desse tamanho.

O editor usa só o Player do Remotion, que mostra a prévia ao vivo da thumbnail. O PNG
é desenhado pelo próprio editor, no navegador, sem os servidores de render do
Remotion, e a página não faz nenhuma chamada para fora do seu computador.

## Baixado no primeiro uso do tema de sons "Notícia" (não vem neste repositório)

Quatro sons da biblioteca do Remotion não têm licença livre. O editor baixa de
`remotion.media` na primeira vez que um vídeo do tema "Notícia" precisa de um deles e
guarda na pasta de dados do seu usuário. Sem internet, toca um parecido da Kenney. Para
não usá-los, escolha outro tema de sons.

| Som | Endereço | Origem e licença |
|---|---|---|
| *vine boom* | `https://remotion.media/vine-boom.wav` | myinstants.com. Sem licença livre: o Remotion diz que, de tão usado, "provavelmente" pode ser usado, e que não se responsabiliza pelo uso |
| *erro do Windows XP* | `https://remotion.media/windows-xp-error.wav` | o mesmo |
| *disco arranhado* | `https://remotion.media/record-scratch.wav` | o mesmo |
| *ding* | `https://remotion.media/ding.wav` | o mesmo |

## Baixado na instalação (não vem neste repositório)

| Pacote | Para quê | Licença |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) e CTranslate2 | transcrever a fala | MIT |
| Modelos [Whisper](https://github.com/openai/whisper), convertidos pela [Systran](https://huggingface.co/Systran) | o modelo baixado no primeiro uso | MIT |
| [MODNet](https://github.com/ZHKKKe/MODNet), em ONNX ([`Xenova/modnet`](https://huggingface.co/Xenova/modnet)) | o recorte da pessoa na thumbnail, baixado no primeiro uso (26 MB) | Apache-2.0, código **e** pesos: [`licencas/MODNet-Apache-2.0.txt`](licencas/MODNet-Apache-2.0.txt) |
| ONNX Runtime | roda o MODNet | MIT |
| [PyAV](https://github.com/PyAV-Org/PyAV) | ler e gravar vídeo | BSD-3-Clause (veja abaixo) |
| NumPy | as contas do áudio e dos quadros | BSD-3-Clause, entre outras |
| Pillow | desenhar legenda, adesivos e ícones | MIT-CMU |
| [rough](https://pypi.org/project/rough/) | o traço tremido dos ícones | MIT |
| FastAPI, Starlette e Uvicorn | o servidor local da interface | MIT e BSD-3-Clause |
| httpx | a conversa com o Gemini, quando a IA está ligada | BSD-3-Clause |
| python-multipart | receber o vídeo enviado pela página | Apache-2.0 |
| platformdirs | achar as pastas de cada sistema | MIT |

**PyAV e FFmpeg.** As rodas do PyAV no PyPI trazem o FFmpeg compilado com o x264 e o
x265, que são GPL. É isso que deixa o editor gravar H.264 e H.265 sem instalar nada no
sistema. Essas bibliotecas são baixadas do PyPI na instalação, e este repositório não
as redistribui.

## Instalado à parte, só com a Minha voz (não vem neste repositório)

O botão **Instalar a voz sintetizada** (ou `editar --instalar-voz`) cria um ambiente só
para a voz, em `motor-de-voz`, na pasta de dados do editor, e baixa o modelo para dentro
dele. Quem não usa a Minha voz não baixa nada disto.

| Pacote | Para quê | Licença |
|---|---|---|
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) (`qwen-tts` 0.1.1), da equipe Qwen, da Alibaba | sintetizar a voz | Apache-2.0 |
| O modelo [Qwen3-TTS-12Hz-0.6B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base) (2,3 GB) | a voz, a partir da referência gravada | Apache-2.0 |
| [PyTorch](https://pytorch.org/) | roda o modelo, na placa do Mac, na NVIDIA ou no processador | BSD-3-Clause, com partes em Apache-2.0, BSD-2-Clause, BSL-1.0 e MIT |
| Transformers, Accelerate e huggingface-hub | carregam o modelo | Apache-2.0 |
| librosa, soundfile, einops e o resto do que o qwen-tts pede | o áudio e as contas do modelo | ISC, BSD-3-Clause e MIT, entre outras |

A gravação da pessoa, a voz salva e as narrações ficam no computador. O motor não fala
com a internet depois de instalado.

## Serviços opcionais

Nenhum deles é chamado sem uma chave de quem usa o editor. As chaves ficam no
`config.json` da pasta de configuração, com leitura só para o próprio usuário, e nunca
voltam para a página.

### O Gemini

A thumbnail com IA usa a [API do Gemini](https://ai.google.dev/), do Google, sob os
[termos da API](https://ai.google.dev/gemini-api/terms).

- **As ideias:** só são pedidas com a opção ligada. O Gemini recebe o texto da fala e 8
  quadros pequenos do vídeo. Na cota gratuita, o Google pode usar o que recebe para
  melhorar os produtos dele.
- **O fundo gerado** (`gemini-2.5-flash-image`): só sai com um clique, e precisa de
  faturamento ativo no Google, uns US$ 0,04 por imagem. O Gemini recebe só a descrição
  da cena. O editor gera no máximo 10 imagens por sessão e anota cada uma num
  `gastos.jsonl`, na pasta de dados dele.

### O Pexels

As fotos de banco vêm da [API do Pexels](https://www.pexels.com/api/), com uma chave
grátis, sob as [regras da API](https://www.pexels.com/api/documentation/#guidelines) e a
[licença do Pexels](https://www.pexels.com/license/), que permite uso livre. O Pexels
recebe só o texto da busca. O próprio editor baixa as fotos, e a página mostra o link do
Pexels e o nome de cada fotógrafo, como as regras pedem.

## As imagens do README

Os quadros, o "antes e depois" e o banner saem de
["Man doing podcast"](https://www.pexels.com/video/man-doing-podcast-6892735/), de
**cottonbro studio**, publicado no Pexels (licença do Pexels: uso livre, sem
atribuição obrigatória). O vídeo foi recortado em 9:16, recebeu uma narração de teste
feita por voz sintética, e depois foi editado pelo próprio editor
([`docs/gerar_imagens.py`](docs/gerar_imagens.py)).
