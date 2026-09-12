#!/usr/bin/env python3
"""
kumiko_server.py

Servidor HTTP local que expõe o Kumiko (o de verdade, Python) pro Leitor de
HQs chamar via fetch() do navegador, com um clique no botão "Auto-detectar".

Por que um servidor à parte, e não integrado direto no app?
O Kumiko é Python; navegadores não deixam uma página web rodar um programa
local diretamente (bloqueio de segurança). Este servidor faz a ponte: fica
escutando em 127.0.0.1, e só responde pedidos vindos da própria página do
Leitor de HQs enquanto esta janela/processo ficar aberto.

Uso:
    python3 kumiko_server.py
    (ou python3 kumiko_server.py --port 8990 --kumiko-dir ./kumiko)

Depois, deixe esse terminal aberto e use o Leitor de HQs normalmente — o
botão "Auto-detectar" vai chamar http://127.0.0.1:8990/detect sozinho.

Dependências: opencv-python, numpy (as mesmas do Kumiko).
"""

import argparse
import http.server
import json
import os
import socketserver
import sys
import tempfile
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KUMIKO_DIR_DEFAULT = os.path.join(SCRIPT_DIR, "kumiko")

CONTENT_TYPE_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def make_handler(Kumiko):
    class Handler(http.server.BaseHTTPRequestHandler):
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
                self._respond_json(200, {"ok": True, "service": "kumiko-server"})
                return
            self.send_response(404)
            self._cors_headers()
            self.end_headers()

        def do_POST(self):
            if not self.path.startswith("/detect"):
                self.send_response(404)
                self._cors_headers()
                self.end_headers()
                return

            query = parse_qs(urlparse(self.path).query)
            rtl = query.get("rtl", ["0"])[0] in ("1", "true")
            try:
                min_ratio = float(query.get("min_panel_size_ratio", ["0.1"])[0])
            except ValueError:
                min_ratio = 0.1

            length = int(self.headers.get("Content-Length", 0) or 0)
            if length <= 0:
                self._error(400, "Corpo da requisição vazio (esperava os bytes da imagem).")
                return
            body = self.rfile.read(length)

            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            ext = CONTENT_TYPE_TO_EXT.get(content_type, ".png")

            try:
                with tempfile.TemporaryDirectory(prefix="kumiko_srv_") as tmp:
                    img_path = os.path.join(tmp, "page" + ext)
                    with open(img_path, "wb") as f:
                        f.write(body)

                    k = Kumiko({"rtl": rtl, "min_panel_size_ratio": min_ratio})
                    k.parse_image(img_path)
                    infos = k.get_infos()[0]

                    width, height = infos["size"]
                    frames = [
                        {"x": x / width, "y": y / height, "w": w / width, "h": h / height}
                        for (x, y, w, h) in infos["panels"]
                    ]

                self._respond_json(200, {"frames": frames})
            except Exception as e:  # noqa: BLE001 - queremos reportar qualquer falha ao navegador
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
            sys.stderr.write("[kumiko-server] " + (fmt % args) + "\n")

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Servidor local do Kumiko para o Leitor de HQs.")
    parser.add_argument("--port", type=int, default=8990)
    parser.add_argument("--kumiko-dir", default=KUMIKO_DIR_DEFAULT,
                         help=f"Pasta com o código-fonte do Kumiko (kumikolib.py). Padrão: {KUMIKO_DIR_DEFAULT}")
    args = parser.parse_args()

    kumikolib_path = os.path.join(args.kumiko_dir, "kumikolib.py")
    if not os.path.isfile(kumikolib_path):
        print(f"[erro] Não encontrei kumikolib.py em '{args.kumiko_dir}'.", file=sys.stderr)
        print("       Use --kumiko-dir pra apontar pra pasta certa.", file=sys.stderr)
        sys.exit(1)

    sys.path.insert(0, args.kumiko_dir)
    try:
        from kumikolib import Kumiko
    except ImportError as e:
        print(f"[erro] Não consegui importar o Kumiko: {e}", file=sys.stderr)
        print("       Rode: pip install opencv-python numpy requests", file=sys.stderr)
        sys.exit(1)

    handler = make_handler(Kumiko)
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"Servidor do Kumiko rodando em http://127.0.0.1:{args.port}")
        print("Deixe esta janela aberta enquanto usa o Leitor de HQs. Ctrl+C pra parar.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nEncerrando…")


if __name__ == "__main__":
    main()
