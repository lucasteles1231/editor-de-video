# Segurança

## Como avisar de uma falha

**Não abra uma issue pública.** Use o
[aviso privado do GitHub](https://github.com/lucasteles1231/editor-de-video/security/advisories/new)
(**Report a vulnerability**, na aba Security do repositório). Só o dono do repositório
vê o aviso, e a conversa continua por ele.

Ajuda muito contar:

- o que acontece, e o que alguém de fora conseguiria fazer com isso;
- como reproduzir (o sistema, o navegador e os passos);
- a versão (`editar --versao`) ou o commit.

## O que vale

Vale a versão mais nova da branch `main`, que é a que o "Começo rápido" do README instala.

Entram:

- o editor (`editor/`);
- a página (`web/`);
- a instalação da Minha voz;
- os workflows do CI.

Ficam de fora:

- os serviços de terceiros: o Gemini, o Pexels e o Hugging Face;
- as falhas dos próprios modelos e bibliotecas, que vão para quem cuida deles. Avise
  aqui mesmo assim se o editor usa a biblioteca de um jeito que a falha alcança.

## O que já foi verificado

A seção [Segurança e privacidade](README.md#segurança-e-privacidade) do README diz:

- o que sai do computador;
- o que protege a página;
- como cada download é conferido;
- o que a última verificação achou.
