#!/usr/bin/env python3
"""
magi_server.py

Substituto do kumiko_server.py que usa o Magi (modelo de IA / deep
learning, https://github.com/ragavsachdeva/magi) em vez do Kumiko clássico
pra detectar os quadros de uma página de quadrinho.

Mesmo contrato de API do kumiko_server.py (POST /detect, GET /ping), na
MESMA porta (8990 por padrão) -- o app web não muda NADA, só troca qual
processo Python está rodando por trás.

⚠️ Diferenças importantes em relação ao Kumiko:
  - Precisa de MUITO mais espaço em disco e dependências (PyTorch,
    transformers, ~2GB de pesos do modelo) -- isso NÃO é leve como o
    Kumiko (que é só OpenCV).
  - O modelo não devolve os quadros em ordem de leitura -- este script
    calcula isso por fora, agrupando por linha (mesma lógica já usada no
    fallback em JavaScript do projeto).
  - Licença do modelo: uso acadêmico/pesquisa, segundo o repositório
    oficial no GitHub -- adequado pra testar e avaliar, mas vale revisar
    com calma antes de distribuir isso pra outras pessoas usarem.

## Instalar as dependências

    pip install torch "transformers==4.46.0" "tokenizers==0.20.3" \
        einops timm matplotlib shapely sentencepiece numpy pillow

(Essas versões específicas de transformers/tokenizers foram as que
funcionaram nos testes -- versões mais novas quebram o carregamento do
tokenizador do Magi.)

## Rodar

    python3 magi_server.py --port 8990

Na primeira vez, baixa o modelo (~2GB) do Hugging Face -- pode demorar.
Depois disso, abra o Leitor de HQs normalmente (mesmo app, sem mudança
nenhuma) e use o botão "Auto-detectar" -- ele vai falar com este servidor
em vez do kumiko_server.py.
"""

import argparse
import http.server
import io
import json
import os
import socketserver
import sys
from urllib.parse import urlparse, parse_qs

CONTENT_TYPE_TO_PIL_OK = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/bmp",
}


def clip(value, lo, hi):
    return max(lo, min(hi, value))


def sort_reading_order(boxes, rtl=False):
    """Agrupa por linha (sobreposição vertical) e ordena esquerda->direita
    (ou o contrário, pra mangá) dentro de cada linha. Mesma lógica usada no
    panel-detect.js do projeto, só que em Python."""
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
        row["items"].sort(key=lambda b: -b["x"] if rtl else b["x"])
        out.extend(row["items"])
    return out


def make_handler(model, device, np, Image, torch, app_root):
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
                self._respond_json(200, {"ok": True, "service": "magi-server"})
                return
            # qualquer outra rota GET é um arquivo estático do app (index.html,
            # app.js, style.css, libarchive/*, etc.) -- deixa o handler padrão cuidar
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
                min_score = float(query.get("min_score", ["0.3"])[0])
            except ValueError:
                min_score = 0.3
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
                pil_img = Image.open(io.BytesIO(body)).convert("L").convert("RGB")
                width, height = pil_img.size
                image_np = np.array(pil_img)

                with torch.no_grad():
                    results = model.predict_detections_and_associations([image_np])
                result = results[0]

                panels = result.get("panels", [])
                scores = result.get("panel_scores", [1.0] * len(panels))

                min_side_px = min(width, height) * min_panel_size_ratio
                min_area = min_side_px * min_side_px

                boxes = []
                for (x1, y1, x2, y2), score in zip(panels, scores):
                    if score < min_score:
                        continue
                    # o modelo às vezes extrapola um pouco pra fora da
                    # imagem (coordenadas negativas ou maiores que a
                    # página) -- cortamos pros limites reais
                    x1c = clip(x1, 0, width)
                    y1c = clip(y1, 0, height)
                    x2c = clip(x2, 0, width)
                    y2c = clip(y2, 0, height)
                    w, h = x2c - x1c, y2c - y1c
                    if w <= 0 or h <= 0 or (w * h) < min_area:
                        continue
                    boxes.append({"x": x1c, "y": y1c, "w": w, "h": h, "score": float(score)})

                ordered = sort_reading_order(boxes, rtl=rtl)
                frames = [
                    {"x": b["x"] / width, "y": b["y"] / height, "w": b["w"] / width, "h": b["h"] / height}
                    for b in ordered
                ]

                self._respond_json(200, {"frames": frames})
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc(file=sys.stderr)
                self._error(500, f"Falha ao detectar quadros com o Magi: {e}")

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
            sys.stderr.write("[magi-server] " + (fmt % args) + "\n")

    return Handler


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    app_root_default = os.path.dirname(script_dir)  # a pasta do index.html, um nível acima de kumiko-tools/

    parser = argparse.ArgumentParser(description="Servidor local do Magi para o Leitor de HQs.")
    parser.add_argument("--port", type=int, default=8990)
    parser.add_argument("--app-root", default=app_root_default,
                         help=f"Pasta com o index.html do Leitor de HQs. Padrão: {app_root_default}")
    parser.add_argument("--model", default="ragavsachdeva/magi",
                         help="Nome do modelo no Hugging Face (padrão: ragavsachdeva/magi, a v1).")
    args = parser.parse_args()

    index_path = os.path.join(args.app_root, "index.html")
    if not os.path.isfile(index_path):
        print(f"[erro] Não encontrei index.html em '{args.app_root}'.", file=sys.stderr)
        print("       Use --app-root pra apontar pra pasta certa.", file=sys.stderr)
        sys.exit(1)

    print("Importando bibliotecas (torch, transformers)...", file=sys.stderr)
    import numpy as np
    from PIL import Image
    import torch
    from transformers import AutoModel

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Usando dispositivo: {device}", file=sys.stderr)

    print(f"Carregando o modelo '{args.model}' (baixa na primeira vez, pode demorar bastante)...", file=sys.stderr)
    model = AutoModel.from_pretrained(args.model, trust_remote_code=True)
    model = model.to(device)
    model.eval()
    print("Modelo carregado.", file=sys.stderr)

    handler = make_handler(model, device, np, Image, torch, args.app_root)
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Leitor de HQs (com auto-detecção via Magi) rodando em {url}", file=sys.stderr)
        print("Abra esse endereço no navegador. Deixe esta janela aberta enquanto usa o app.", file=sys.stderr)
        print("Ctrl+C pra parar.", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nEncerrando…", file=sys.stderr)


if __name__ == "__main__":
    main()
