#!/usr/bin/env python3
"""
yolo_server.py

Substituto do kumiko_server.py (e do magi_server.py) que usa um modelo
YOLOv12x fine-tuned especificamente pra detectar quadros de quadrinho
(https://huggingface.co/mosesb/best-comic-panel-detection).

Mesmo contrato de API dos outros dois (GET /ping, POST /detect), na MESMA
porta (8990 por padrão), servindo o app inteiro também -- o app web não
muda NADA, só troca qual processo Python está rodando por trás.

Por que este em vez do Magi:
  - Bem mais leve (~120MB de modelo, contra ~2GB do Magi)
  - Dependências simples (só ultralytics, sem parafuso de versões)
  - Licença Apache-2.0 (o Magi é "uso acadêmico/pesquisa" apenas)
  - Nos testes, teve resultado mais preciso em quadrinhos ocidentais
    coloridos (o Magi foi treinado majoritariamente em mangá)

Uma peculiaridade que este script já corrige: o modelo às vezes gera
detecções "fantasma" que cobrem DOIS quadros reais ao mesmo tempo (o NMS
padrão do YOLO não pega esse caso). Filtramos isso por conta própria antes
de responder.

## Instalar as dependências

    pip install ultralytics huggingface_hub pillow numpy

## Rodar

    python3 yolo_server.py --port 8990

Na primeira vez baixa o modelo (~120MB) do Hugging Face.
"""

import argparse
import http.server
import io
import json
import os
import socketserver
import sys
from urllib.parse import urlparse, parse_qs

MODEL_REPO = "mosesb/best-comic-panel-detection"
MODEL_FILENAME = "best.pt"


def clip(value, lo, hi):
    return max(lo, min(hi, value))


def box_area(b):
    return max(0.0, b["w"]) * max(0.0, b["h"])


def box_intersection(a, b):
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    x1, y1 = max(ax1, bx1), max(ay1, by1)
    x2, y2 = min(ax2, bx2), min(ay2, by2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1)


def remove_ghost_detections(boxes, overlap_threshold=0.5):
    """Remove caixas que sobrepõem muito (>overlap_threshold da área da
    menor) uma caixa já aceita de confiança maior. Resolve o caso de uma
    detecção "fantasma" que cobre dois quadros reais ao mesmo tempo -- o
    NMS padrão do YOLO não pega isso porque a sobreposição com cada quadro
    individualmente fica abaixo do limiar normal de IoU."""
    ordered = sorted(boxes, key=lambda b: -b["confidence"])
    kept = []
    for b in ordered:
        overlaps_kept = False
        for k in kept:
            inter = box_intersection(b, k)
            smaller = min(box_area(b), box_area(k))
            if smaller > 0 and (inter / smaller) > overlap_threshold:
                overlaps_kept = True
                break
        if not overlaps_kept:
            kept.append(b)
    return kept


def sort_reading_order(boxes, rtl=False):
    """Calcula a ordem de leitura via cortes recursivos (guillotine cuts):
    procura uma linha -- horizontal primeiro, depois vertical -- que separe
    os quadros em dois grupos sem cortar nenhum quadro ao meio, e repete
    recursivamente em cada grupo. Isso lida corretamente com layouts em L
    (ex: um quadro alto à esquerda ao lado de dois quadros empilhados à
    direita), onde um agrupamento simples "por linha" erra a ordem entre
    os dois quadros empilhados."""
    if len(boxes) <= 1:
        return boxes[:]

    def right(b):
        return b["x"] + b["w"]

    def bottom(b):
        return b["y"] + b["h"]

    def try_split(boxes, horizontal):
        if horizontal:
            edges = sorted(set([b["y"] for b in boxes] + [bottom(b) for b in boxes]))
        else:
            edges = sorted(set([b["x"] for b in boxes] + [right(b) for b in boxes]))
        # tolerância pra pequenas imprecisões de detecção (ex: 2 painéis
        # vizinhos com alguns pixels de sobreposição nas caixas da IA,
        # mesmo sem se sobreporem de verdade na página)
        span = edges[-1] - edges[0] if edges else 0
        tolerance = max(span * 0.01, 1e-6)
        for edge in edges:
            group_a, group_b = [], []
            valid = True
            for b in boxes:
                b_start, b_end = (b["y"], bottom(b)) if horizontal else (b["x"], right(b))
                if b_end <= edge + tolerance:
                    group_a.append(b)
                elif b_start >= edge - tolerance:
                    group_b.append(b)
                else:
                    valid = False
                    break
            if valid and group_a and group_b:
                return group_a, group_b
        return None

    # 1) tenta separar em cima/baixo primeiro (mais comum em quadrinhos)
    split = try_split(boxes, horizontal=True)
    if split:
        top, bottom_group = split
        return sort_reading_order(top, rtl) + sort_reading_order(bottom_group, rtl)

    # 2) tenta separar em esquerda/direita
    split = try_split(boxes, horizontal=False)
    if split:
        left, right_group = split
        if rtl:
            left, right_group = right_group, left
        return sort_reading_order(left, rtl) + sort_reading_order(right_group, rtl)

    # 3) não dá pra separar de forma limpa (quadros sobrepostos/atravessados)
    # -- cai pro critério simples de topo->baixo, esquerda->direita
    return sorted(boxes, key=lambda b: (round(b["y"], 1), -b["x"] if rtl else b["x"]))


def make_handler(model, Image, app_root):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=app_root, **kwargs)

        def _cors_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        def do_GET(self):
            if self.path == "/ping":
                self._respond_json(200, {"ok": True, "service": "yolo-server"})
                return
            super().do_GET()

        def end_headers(self):
            self._cors_headers()
            super().end_headers()

        def do_POST(self):
            if not self.path.startswith("/detect"):
                self.send_response(404)
                self._cors_headers()
                self.end_headers()
                return

            query = parse_qs(urlparse(self.path).query)
            rtl = query.get("rtl", ["0"])[0] in ("1", "true")
            try:
                min_conf = float(query.get("min_conf", ["0.25"])[0])
            except ValueError:
                min_conf = 0.25
            try:
                overlap_threshold = float(query.get("overlap_threshold", ["0.5"])[0])
            except ValueError:
                overlap_threshold = 0.5
            try:
                min_panel_size_ratio = float(query.get("min_panel_size_ratio", ["0.05"])[0])
            except ValueError:
                min_panel_size_ratio = 0.05

            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                self._error(400, "Corpo da requisição vazio (esperava os bytes da imagem).")
                return
            body = self.rfile.read(length)

            try:
                pil_img = Image.open(io.BytesIO(body)).convert("RGB")
                width, height = pil_img.size

                results = model.predict(source=pil_img, conf=min_conf, verbose=False)
                result = results[0]

                boxes = []
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf.item())
                    x1c, y1c = clip(x1, 0, width), clip(y1, 0, height)
                    x2c, y2c = clip(x2, 0, width), clip(y2, 0, height)
                    w, h = x2c - x1c, y2c - y1c
                    if w > 0 and h > 0:
                        boxes.append({"x": x1c, "y": y1c, "w": w, "h": h, "confidence": conf})

                boxes = remove_ghost_detections(boxes, overlap_threshold)

                min_side_px = min(width, height) * min_panel_size_ratio
                min_area = min_side_px * min_side_px
                boxes = [b for b in boxes if box_area(b) >= min_area]

                ordered = sort_reading_order(boxes, rtl=rtl)
                frames = [
                    {"x": b["x"] / width, "y": b["y"] / height, "w": b["w"] / width, "h": b["h"] / height}
                    for b in ordered
                ]

                self._respond_json(200, {"frames": frames})
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc(file=sys.stderr)
                self._error(500, f"Falha ao detectar quadros: {e}")

        def _respond_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message):
            self._respond_json(status, {"error": message})

        def log_message(self, fmt, *args):
            sys.stderr.write("[yolo-server] " + (fmt % args) + "\n")

    return Handler


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    app_root_default = os.path.dirname(script_dir)  # a pasta do index.html, um nível acima de kumiko-tools/

    parser = argparse.ArgumentParser(description="Servidor local do YOLOv12x para o Leitor de HQs.")
    parser.add_argument("--port", type=int, default=8990)
    parser.add_argument("--app-root", default=app_root_default,
                         help=f"Pasta com o index.html do Leitor de HQs. Padrão: {app_root_default}")
    parser.add_argument("--model-path", default=None,
                         help="Caminho local pro best.pt, se já tiver baixado. Se omitido, baixa do Hugging Face.")
    args = parser.parse_args()

    index_path = os.path.join(args.app_root, "index.html")
    if not os.path.isfile(index_path):
        print(f"[erro] Não encontrei index.html em '{args.app_root}'.", file=sys.stderr)
        print("       Use --app-root pra apontar pra pasta certa.", file=sys.stderr)
        sys.exit(1)

    print("Importando bibliotecas...", file=sys.stderr)
    from PIL import Image
    from ultralytics import YOLO

    if args.model_path:
        model_path = args.model_path
    else:
        print("Baixando/carregando o modelo do cache (só baixa de verdade na primeira vez)...", file=sys.stderr)
        from huggingface_hub import hf_hub_download
        model_path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILENAME)

    model = YOLO(model_path)
    print("Modelo carregado.", file=sys.stderr)

    handler = make_handler(model, Image, args.app_root)
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Leitor de HQs (com auto-detecção via YOLOv12x) rodando em {url}", file=sys.stderr)
        print("Abra esse endereço no navegador. Deixe esta janela aberta enquanto usa o app.", file=sys.stderr)
        print("Ctrl+C pra parar.", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nEncerrando…", file=sys.stderr)


if __name__ == "__main__":
    main()
