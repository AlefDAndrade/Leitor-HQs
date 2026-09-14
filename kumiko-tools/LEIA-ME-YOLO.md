# YOLOv12x → Leitor de HQs (drop-in no lugar do Kumiko/Magi)

Mesma porta (8990), mesmo formato de resposta dos outros dois servidores.
**O app web não muda nada** — só troca qual processo Python fica rodando.

## 1. Instalar as dependências

```bash
pip install ultralytics huggingface_hub pillow numpy
```

Bem mais simples que o Magi — sem precisar fixar versões específicas de
`transformers`/`tokenizers`.

## 2. Rodar

```bash
python3 yolo_server.py --port 8990
```

Na primeira vez baixa o modelo (~120MB) do Hugging Face. Nas próximas já
usa o cache local.

## 3. Usar

Abra `http://127.0.0.1:8990/` no navegador (o próprio servidor já serve o
app inteiro) e use o "Auto-detectar" normalmente.

## Parâmetros ajustáveis (na URL, ex: `/detect?min_conf=0.3`)

- `min_conf` (padrão 0.25): confiança mínima do YOLO pra considerar uma
  detecção. Baixar isso pode trazer mais "lixo"; subir pode perder quadros
  reais.
- `overlap_threshold` (padrão 0.5): usado no filtro de detecções
  "fantasma" (caixas que cobrem dois quadros reais ao mesmo tempo). Se
  ainda aparecerem fantasmas, tente baixar esse valor (ex: 0.35).
- `min_panel_size_ratio` (padrão 0.05): tamanho mínimo de um quadro, como
  fração da menor dimensão da página.
- `fill_gaps` (padrão 1, ligado): tenta recuperar quadros que o modelo não
  viu, procurando áreas grandes da página sem nenhuma detecção por cima.
  Passe `fill_gaps=0` pra desligar essa recuperação.
- `rtl=1`: ordem de leitura direita→esquerda (mangá).

## Como funciona a recuperação de quadros perdidos ("fill_gaps")

O YOLO às vezes simplesmente não detecta um painel (formato incomum, sem
moldura clara, etc. -- visto em testes com painéis bem finos de efeito
sonoro). Pra compensar isso, depois de aceitar as detecções do modelo, o
servidor calcula quais áreas da página **sobraram sem nenhum quadro por
cima**. Como as frestas normais entre painéis (gutters) conectariam essas
áreas todas numa "sobra" do tamanho da página inteira, aplicamos uma
erosão morfológica (encolhe as áreas vazias por uns pixels antes de
procurar blobs conectados, o que quebra frestas finas mas preserva buracos
realmente grandes) antes de decidir o que é um "quadro esquecido" de
verdade.

Se dois ou mais quadros perdidos estiverem coladinhos um no outro, essa
técnica pode juntar os dois numa marcação só (em vez de duas separadas) --
ainda assim, é bem mais rápido ajustar/dividir manualmente uma marcação
já no lugar certo do que ter que notar e desenhar do zero.

## Por que esse filtro de "detecções fantasma"?

O modelo, sozinho, às vezes gera uma caixa extra que cobre DOIS quadros
reais ao mesmo tempo (ex: uma caixa que abrange os quadros 2 e 3 juntos,
além das caixas corretas de cada um). O NMS (supressão de não-máximos)
padrão do YOLO não remove isso, porque a sobreposição dessa caixa fantasma
com cada quadro individual fica abaixo do limiar normal.

Resolvemos isso à parte: ordenamos as detecções por confiança e
descartamos qualquer uma que sobreponha mais de 50% da área de uma
detecção já aceita (e de confiança maior). Validado com dados reais —
resolveu 100% dos casos de fantasma nos testes.

## Testado até agora

- ✅ 6 de 6 quadros detectados corretamente numa página de teste real
  (quadrinho ocidental colorido), com confiança 0.82–0.95
- ✅ Filtro de detecções fantasma funcionando (removeu as 3 espúrias sem
  afetar as 6 reais)
- ✅ ~2.9 segundos por página, sem GPU
- ✅ Ordem de leitura calculada bate com a leitura real
- ✅ Licença Apache-2.0 (sem restrição de "uso acadêmico" como o Magi)
