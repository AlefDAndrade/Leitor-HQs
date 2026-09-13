#!/usr/bin/env python3
"""
test_yolo_panels.py — script de INVESTIGAÇÃO pro modelo YOLOv12x de
detecção de quadros (mosesb/best-comic-panel-detection).

Assim como o test_magi.py, isso não roda aqui no ambiente do Claude (o
Hugging Face está bloqueado ali) -- rode na sua máquina.

Vantagem em relação ao Magi: as dependências são bem mais simples (só
`ultralytics`, que já traz o torch junto se precisar), sem aquele parafuso
de versões de transformers/tokenizers.

## Instalar

    pip install ultralytics huggingface_hub pillow

## Rodar

    python3 test_yolo_panels.py caminho\\para\\uma\\pagina.png

Na primeira vez baixa o modelo (~85MB, bem mais leve que o Magi) do
Hugging Face.
"""

import sys
import time
import json


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 test_yolo_panels.py caminho/para/pagina.png [confianca_minima]", file=sys.stderr)
        print("  confianca_minima (opcional, padrão 0.25): use um valor bem baixo, tipo 0.03,", file=sys.stderr)
        print("  pra ver se o modelo 'quase' detectou algo que ficou de fora.", file=sys.stderr)
        sys.exit(1)

    image_path = sys.argv[1]
    min_conf = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25

    print("Importando bibliotecas...")
    from huggingface_hub import hf_hub_download
    from ultralytics import YOLO
    from PIL import Image

    print("Baixando o modelo (só na primeira vez)...")
    t0 = time.time()
    model_path = hf_hub_download(
        repo_id="mosesb/best-comic-panel-detection",
        filename="best.pt",
    )
    model = YOLO(model_path)
    print(f"Modelo pronto em {time.time() - t0:.1f}s")
    print(f"Classes do modelo: {model.names}")

    img = Image.open(image_path)
    width, height = img.size
    print(f"\nImagem: {image_path} ({width}x{height})")

    print("Rodando a detecção...")
    t0 = time.time()
    results = model.predict(source=image_path, conf=min_conf, verbose=False)
    elapsed = time.time() - t0
    print(f"Detecção concluída em {elapsed:.2f}s (confiança mínima usada: {min_conf})")

    result = results[0]
    boxes_data = []
    for box in result.boxes:
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        conf = float(box.conf.item())
        cls_name = model.names[int(box.cls)]
        boxes_data.append({"class": cls_name, "confidence": conf, "xyxy": [x1, y1, x2, y2]})

    print(f"\n{len(boxes_data)} quadro(s) detectado(s) (antes do filtro de sobreposição):")
    for i, b in enumerate(boxes_data):
        print(f"  {i+1}: confiança={b['confidence']:.3f} caixa={[round(v,1) for v in b['xyxy']]}")

    # ---- remove detecções "fantasma" que sobrepõem muito uma detecção já
    # aceita de confiança maior (o NMS padrão do YOLO não pega esse caso
    # quando a caixa fantasma cobre DOIS quadros reais ao mesmo tempo,
    # porque a sobreposição com cada um individualmente fica abaixo do
    # limiar de IoU padrão) ----
    def area(b):
        x1, y1, x2, y2 = b["xyxy"]
        return max(0, x2-x1) * max(0, y2-y1)

    def intersection(a, b):
        ax1, ay1, ax2, ay2 = a["xyxy"]
        bx1, by1, bx2, by2 = b["xyxy"]
        x1, y1 = max(ax1, bx1), max(ay1, by1)
        x2, y2 = min(ax2, bx2), min(ay2, by2)
        if x2 <= x1 or y2 <= y1:
            return 0
        return (x2-x1) * (y2-y1)

    def overlap_ratio(a, b):
        inter = intersection(a, b)
        smaller = min(area(a), area(b))
        return inter / smaller if smaller > 0 else 0

    ordered_by_conf = sorted(boxes_data, key=lambda b: -b["confidence"])
    kept = []
    for b in ordered_by_conf:
        if not any(overlap_ratio(b, k) > 0.5 for k in kept):
            kept.append(b)
    boxes_data = kept

    print(f"\n{len(boxes_data)} quadro(s) depois do filtro de sobreposição:")
    for i, b in enumerate(boxes_data):
        print(f"  {i+1}: confiança={b['confidence']:.3f} caixa={[round(v,1) for v in b['xyxy']]}")

    # ---- calcula a ordem de leitura (mesma lógica usada com o Magi) ----
    def sort_reading_order(boxes, rtl=False):
        boxes = sorted(boxes, key=lambda b: b["y"])
        rows = []
        for b in boxes:
            placed = False
            for row in rows:
                overlap = min(row["y2"], b["y"] + b["h"]) - max(row["y1"], b["y"])
                min_h = min(row["y2"] - row["y1"], b["h"])
                if overlap > min_h * 0.5:
                    row["items"].append(b)
                    row["y1"] = min(row["y1"], b["y"])
                    row["y2"] = max(row["y2"], b["y"] + b["h"])
                    placed = True
                    break
            if not placed:
                rows.append({"y1": b["y"], "y2": b["y"] + b["h"], "items": [b]})
        rows.sort(key=lambda r: r["y1"])
        out = []
        for row in rows:
            row["items"].sort(key=lambda b: b["x"])
            out.extend(row["items"])
        return out

    boxes_xywh = [
        {"x": b["xyxy"][0], "y": b["xyxy"][1], "w": b["xyxy"][2]-b["xyxy"][0], "h": b["xyxy"][3]-b["xyxy"][1],
         "confidence": b["confidence"]}
        for b in boxes_data
    ]
    ordered = sort_reading_order(boxes_xywh)

    print("\nOrdem de leitura calculada:")
    for i, b in enumerate(ordered):
        fx, fy = b["x"]/width, b["y"]/height
        fw, fh = b["w"]/width, b["h"]/height
        print(f"  #{i+1}: x={fx:.3f} y={fy:.3f} w={fw:.3f} h={fh:.3f} (confiança={b['confidence']:.3f})")

    # salva os dados brutos e a visualização
    with open("yolo_result_debug.json", "w", encoding="utf-8") as f:
        json.dump({"boxes": boxes_data, "image_size": [width, height]}, f, indent=2)
    print("\n(dados salvos em yolo_result_debug.json)")

    im_array = result.plot(boxes=False)  # imagem sem as caixas do ultralytics (vamos desenhar as nossas)
    from PIL import Image as PILImage, ImageDraw
    im = PILImage.fromarray(im_array[..., ::-1])  # BGR -> RGB
    draw = ImageDraw.Draw(im)
    for i, b in enumerate(ordered):
        x1, y1 = b["x"], b["y"]
        x2, y2 = b["x"]+b["w"], b["y"]+b["h"]
        draw.rectangle([x1, y1, x2, y2], outline="lime", width=4)
        draw.text((x1+6, y1+6), f"#{i+1} ({b['confidence']:.2f})", fill="lime")
    im.save("yolo_visualizacao.png")
    print("Visualização salva em yolo_visualizacao.png (já com o filtro aplicado e numerado por ordem de leitura)")

    print(f"\n--- Resumo ---")
    print(f"Quadros detectados: {len(boxes_data)}")
    print(f"Tempo de detecção: {elapsed:.2f}s")
    print("Me manda: esse resumo, yolo_result_debug.json e yolo_visualizacao.png")


if __name__ == "__main__":
    main()
