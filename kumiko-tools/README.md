# Kumiko → Leitor de HQs

Ferramentas pra gerar marcações de quadros automaticamente usando o
[Kumiko](https://github.com/njean42/kumiko) (o de verdade, em Python).

O Kumiko já vem incluso dentro de `kumiko-tools/kumiko/` — não precisa
clonar nada à parte.

> **Nota sobre licença:** o Kumiko é licenciado em AGPL-3.0 (arquivo
> `kumiko-tools/kumiko/LICENSE`). Ele foi incluído aqui como código-fonte
> completo, com uma única correção pontual de compatibilidade documentada
> em `kumiko-tools/kumiko/PATCHES.md`. Ele roda como um processo à parte
> (biblioteca Python chamada localmente, ou servidor HTTP em 127.0.0.1) —
> não foi integrado/misturado ao código do app em si.

## Instalar as dependências do Kumiko

```bash
pip install opencv-python numpy requests
```

Tem dois jeitos de usar o Kumiko com o Leitor de HQs:

## Opção 1 — Botão "✨ Auto-detectar" dentro do app (recomendado)

Um único servidor local serve o próprio app (`index.html`) **e** embrulha
o Kumiko — não precisa mais abrir o `index.html` separado nem rodar dois
processos.

1. Num terminal, rode:
   ```bash
   cd kumiko-tools
   python3 kumiko_server.py
   ```
   Ele imprime um endereço, normalmente `http://127.0.0.1:8990/`. Deixe
   esse terminal aberto enquanto usa o Leitor de HQs (`Ctrl+C` pra parar
   quando terminar).

2. Abra esse endereço no navegador (em vez de dar duplo-clique no
   `index.html`) e importe suas páginas normalmente.

3. Clique em **"✨ Auto-detectar"** na barra de ferramentas. Dá pra escolher
   entre "nesta página" ou "todas as páginas", e marcar "mangá" pra ordem
   de leitura direita→esquerda.

4. As marcações aparecem automaticamente — ajuste manualmente (mover,
   redimensionar, apagar, reordenar) o que precisar, do jeito que já
   funcionava antes.

Se por algum motivo você abrir o `index.html` direto (sem passar pelo
servidor), o app ainda funciona pra leitura e marcação manual — só o botão
"Auto-detectar" não vai achar o servidor, e avisa com uma mensagem clara.

**Sobre privacidade:** a imagem da página sai do navegador e vai até o
`kumiko_server.py` — mas só até `127.0.0.1` (sua própria máquina), nunca
pra internet. É equivalente a rodar qualquer programa local no seu
computador.

## Opção 2 — Script de linha de comando (sem precisar deixar um servidor no ar)

Útil se você quer gerar as marcações de um lote de páginas de uma vez,
sem depender do app estar aberto.

```bash
cd kumiko-tools
python3 kumiko_to_frames.py \
  --input /caminho/para/suas-paginas \
  --output marcacoes-de-quadros.json
```

`--input` aceita uma **pasta** de imagens, um **.cbz**/**.zip**, ou uma
**imagem única**. Para mangá, adicione `--rtl`.

Depois:
1. Abra o `index.html` e importe **as mesmas imagens, na mesma ordem**
   que você usou no `--input`.
2. Clique em **"Carregar marcações"** e selecione o JSON gerado.

⚠️ O app casa as páginas do JSON com as páginas carregadas **por posição**
(1ª página do JSON → 1ª página carregada, e assim por diante), não por
nome de arquivo. Por isso a ordem de importação precisa ser a mesma.

## Limitações conhecidas

- O Kumiko é bom com quadros retangulares bem definidos (bordas ou gutters
  claros). Painéis muito irregulares, sobrepostos, ou sem borda nenhuma
  tendem a sair errados ou incompletos — revise sempre antes de salvar.
- No botão do app, o "tamanho mínimo de painel" fica fixo em 10% da menor
  dimensão da página (padrão do Kumiko). Pra ajustar isso, use a Opção 2
  com `--min-panel-size-ratio`.
- `kumiko_server.py` só aceita conexões vindas de `127.0.0.1` (sua própria
  máquina) — não é pra deixar exposto na rede.

## Se der erro "invalid index to scalar variable"

Esse era um bug de compatibilidade entre versões do OpenCV, já corrigido
no Kumiko incluído neste pacote (ver `kumiko-tools/kumiko/PATCHES.md`).
Se ainda assim aparecer, confira se não há uma cópia antiga da pasta
`kumiko/` sobrando em outro lugar do seu sistema sendo usada no lugar
desta.
