# Modificações aplicadas a este Kumiko vendorizado

Este diretório contém o código-fonte do [Kumiko](https://github.com/njean42/kumiko)
(AGPL-3.0, ver `LICENSE`) com **uma modificação pontual**, documentada aqui
por transparência (e porque a AGPL exige indicar mudanças em relação ao
original quando o código é redistribuído).

## Correção: `lib/page.py`, função `get_segments`

**Problema:** em algumas combinações de versão/plataforma do OpenCV, o
detector de segmentos de linha (`cv.createLineSegmentDetector`) devolve as
linhas detectadas em um formato de array ligeiramente diferente do que o
código original esperava — uma dimensão "achatada" a menos. Isso fazia o
Kumiko quebrar com:

```
IndexError: invalid index to scalar variable.
```

em qualquer página onde a detecção de segmentos encontrasse pelo menos uma
linha (ou seja, na prática, na maioria das páginas reais).

**Correção:** em vez de indexar `dline[0][0]`, `dline[0][1]` etc. assumindo
um formato fixo, o código agora normaliza cada item pra uma lista simples
de 4 números com `np.asarray(dline).reshape(-1)`, que funciona
independentemente de qual das duas variações de formato o OpenCV
instalado devolve.

Reproduzido e validado com um teste que simula as duas variações de
formato conhecidas — ambas passam a funcionar sem alterar o resultado da
detecção (mesmas coordenadas de painéis).

Nenhuma outra parte do Kumiko foi alterada.
