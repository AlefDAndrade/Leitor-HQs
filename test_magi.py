#!/usr/bin/env python3
"""
test_magi.py — script de INVESTIGAÇÃO (não é a integração final ainda).

Isso NÃO baixa nem roda nada aqui no ambiente do Claude — o Hugging Face
está bloqueado ali. Você precisa rodar isso na sua própria máquina, que
tem acesso liberado, e me mandar o que aparecer no terminal.

O que esse script faz:
  1. Baixa o modelo Magi (v1) do Hugging Face na primeira vez que rodar
     (~2GB, pode demorar dependendo da internet)
  2. Roda ele numa imagem de teste sua
  3. Imprime a ESTRUTURA COMPLETA da resposta (quais chaves existem, que
     tipo de dado cada uma tem) -- isso é o que eu preciso ver pra saber
     como converter a saída dele pro formato de marcações do Leitor de HQs
  4. Salva uma imagem com a visualização (painéis/textos desenhados por
     cima), se o modelo tiver essa função
  5. Mede quanto tempo demorou, pra sabermos se é viável usar isso no dia
     a dia (modelos de IA desse tipo costumam ser bem mais lentos que o
     Kumiko, especialmente sem GPU)

## Instalar as dependências

    pip install transformers torch numpy pillow

(Se tiver uma GPU NVIDIA com CUDA instalado, o script já detecta e usa
sozinho -- vai ser MUITO mais rápido. Sem GPU, roda no processador mesmo,
só que mais devagar.)

## Rodar

    python3 test_magi.py caminho/para/uma/pagina.png

## Sobre a licença

O modelo (segundo o repositório oficial no GitHub) é liberado apenas pra
"uso acadêmico e de pesquisa" -- rodar aqui pra AVALIAR se vale a pena
usar é razoável, mas antes de colocar isso de vez no app pra outras
pessoas usarem, vale a pena revisar essa licença com mais calma (ou
falar com o autor, como o card do modelo sugere).
"""

import sys
import time
import json


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 test_magi.py caminho/para/pagina.png", file=sys.stderr)
        sys.exit(1)

    image_path = sys.argv[1]

    print("Importando bibliotecas...")
    import numpy as np
    from PIL import Image
    import torch
    from transformers import AutoModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Usando dispositivo: {device}" + (" (sem GPU, vai ser mais lento)" if device == "cpu" else ""))

    print("Carregando o modelo (baixa na primeira vez, pode demorar bastante)...")
    t0 = time.time()
    model = AutoModel.from_pretrained("ragavsachdeva/magi", trust_remote_code=True)
    model = model.to(device)
    model.eval()
    print(f"Modelo carregado em {time.time() - t0:.1f}s")

    def read_image_as_np_array(path):
        with open(path, "rb") as f:
            img = Image.open(f).convert("L").convert("RGB")
            return np.array(img)

    print(f"Lendo imagem: {image_path}")
    image = read_image_as_np_array(image_path)

    print("Rodando a detecção (isso é o que queremos medir/avaliar)...")
    t0 = time.time()
    with torch.no_grad():
        results = model.predict_detections_and_associations([image])
    elapsed = time.time() - t0
    print(f"\nDetecção concluída em {elapsed:.2f}s")

    result = results[0]

    print("\n" + "=" * 60)
    print("ESTRUTURA DA RESPOSTA (isso é o que preciso ver)")
    print("=" * 60)
    for key, value in result.items():
        type_name = type(value).__name__
        if hasattr(value, "__len__"):
            print(f"  '{key}': {type_name}, tamanho={len(value)}")
            if len(value) > 0:
                first = value[0]
                print(f"      primeiro item: {first!r} (tipo: {type(first).__name__})")
        else:
            print(f"  '{key}': {type_name} = {value!r}")

    print("\n" + "=" * 60)
    print("JSON completo (pra eu analisar com calma):")
    print("=" * 60)

    def to_jsonable(obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, list):
            return [to_jsonable(x) for x in obj]
        if isinstance(obj, dict):
            return {k: to_jsonable(v) for k, v in obj.items()}
        return obj

    jsonable = to_jsonable(result)
    output_json_path = "magi_result_debug.json"
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(jsonable, f, indent=2, ensure_ascii=False)
    print(f"(salvo em {output_json_path} -- me manda esse arquivo)")

    # tenta salvar uma visualização, se o modelo suportar
    try:
        model.visualise_single_image_prediction(image, result, filename="magi_visualizacao.png")
        print("\nVisualização salva em magi_visualizacao.png -- dá uma olhada nela também!")
    except Exception as e:
        print(f"\n(não consegui gerar a visualização automática: {e})")

    print(f"\n--- Resumo ---")
    print(f"Tempo de detecção: {elapsed:.2f}s (dispositivo: {device})")
    print("Me manda: esse resumo, o conteúdo de magi_result_debug.json (ou o arquivo),")
    print("e a imagem magi_visualizacao.png se ela foi gerada.")


if __name__ == "__main__":
    main()
