#!/usr/bin/env python3
"""
kumiko_server.py

Servidor HTTP local único que serve o Leitor de HQs (index.html, app.js,
etc.) E expõe o Kumiko (o de verdade, Python) pro app chamar via fetch(),
com um clique no botão "Auto-detectar". Só precisa rodar isso e abrir UM
endereço no navegador — não precisa mais abrir o index.html separado.

Por que um servidor, e não integrar o Kumiko direto no app?
O Kumiko é Python; navegadores não deixam uma página web rodar um programa
local diretamente (bloqueio de segurança). Este servidor faz a ponte: fica
escutando em 127.0.0.1, serve os arquivos do app normalmente por HTTP, e
responde às chamadas de detecção enquanto esta janela/processo ficar
aberto.

Uso:
    python3 kumiko_server.py
    (ou python3 kumiko_server.py --port 8990 --kumiko-dir ./kumiko)

Depois, abra o endereço que aparece no terminal (por padrão
http://127.0.0.1:8990/) — é ali que o Leitor de HQs aparece, já com o
botão "Auto-detectar" funcionando. Deixe o terminal aberto enquanto usa o
app; Ctrl+C pra parar quando terminar.

Dependências: opencv-python, numpy (as mesmas do Kumiko).
"""

import argparse
import functools
import http.server
import json
import os
import socketserver
import sys
import tempfile
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT_DEFAULT = os.path.dirname(SCRIPT_DIR)  # a pasta do index.html, um nível acima de kumiko-tools/
KUMIKO_DIR_DEFAULT = os.path.join(SCRIPT_DIR, "kumiko")

CONTENT_TYPE_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def make_handler(Kumiko, app_root):
    # Herda de SimpleHTTPRequestHandler pra ganhar de graça a parte de servir
    # arquivos estáticos (index.html, app.js, style.css, libarchive/, etc.)
    # e só adiciona por cima as rotas /ping e /detect do Kumiko.
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
                self._respond_json(200, {"ok": True, "service": "kumiko-server"})
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
    parser = argparse.ArgumentParser(
        description="Servidor local único: serve o Leitor de HQs e expõe o Kumiko.")
    parser.add_argument("--port", type=int, default=8990)
    parser.add_argument("--app-root", default=APP_ROOT_DEFAULT,
                         help=f"Pasta com o index.html do Leitor de HQs. Padrão: {APP_ROOT_DEFAULT}")
    parser.add_argument("--kumiko-dir", default=KUMIKO_DIR_DEFAULT,
                         help=f"Pasta com o código-fonte do Kumiko (kumikolib.py). Padrão: {KUMIKO_DIR_DEFAULT}")
    args = parser.parse_args()

    index_path = os.path.join(args.app_root, "index.html")
    if not os.path.isfile(index_path):
        print(f"[erro] Não encontrei index.html em '{args.app_root}'.", file=sys.stderr)
        print("       Use --app-root pra apontar pra pasta certa.", file=sys.stderr)
        sys.exit(1)

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

    handler = make_handler(Kumiko, args.app_root)
    with socketserver.ThreadingTCPServer(("127.0.0.1", args.port), handler) as httpd:
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Leitor de HQs (com auto-detecção via Kumiko) rodando em {url}")
        print("Abra esse endereço no navegador. Deixe esta janela aberta enquanto usa o app.")
        print("Ctrl+C pra parar.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nEncerrando…")


if __name__ == "__main__":
    main()
