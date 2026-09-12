#!/usr/bin/env python3
"""
kumiko_to_frames.py

Roda o Kumiko (https://github.com/njean42/kumiko) sobre um conjunto de páginas
de quadrinho e converte o resultado para o formato de "marcações" que o
Leitor de HQs (index.html / app.js) já sabe importar pelo botão
"Carregar marcações".

Por que um script separado em vez de integrar o Kumiko direto no app?
- O Kumiko é Python + OpenCV; o Leitor de HQs roda 100% no navegador (sem
  backend), então não dá pra "rodar" o Kumiko dentro do app sem reescrevê-lo.
- O Kumiko é licenciado em AGPL-3.0. Para não misturar essa licença com o
  código do seu app, este script trata o Kumiko como uma ferramenta externa
  (chamada via linha de comando), sem copiar nenhum código dele para cá.

Pré-requisitos:
    1) Clonar o Kumiko em algum lugar:
         git clone https://github.com/njean42/kumiko.git
    2) Instalar as dependências dele:
         pip install opencv-python numpy requests
    3) Ter o executável `kumiko` acessível (o script dentro do clone,
       ex: /caminho/para/kumiko/kumiko), ou informar o caminho com --kumiko-bin.

Uso básico:
    python3 kumiko_to_frames.py \
        --input /caminho/para/pasta-com-paginas \
        --output marcacoes-de-quadros.json \
        --kumiko-bin /caminho/para/kumiko/kumiko

Também aceita um arquivo .cbz/.zip como --input (ele extrai as imagens
para uma pasta temporária antes de processar).

O JSON gerado pode ser carregado direto no Leitor de HQs pelo botão
"Carregar marcações" — mas ATENÇÃO: a ordem das páginas no JSON precisa
bater com a ordem em que você importou as mesmas imagens no app (o app casa
as marcações por posição/índice, não por nome de arquivo). Por isso este
script ordena as páginas com o mesmo critério de "ordenação natural"
(numérica) que o app usa — não a ordenação alfabética simples que o Kumiko
usa internamente.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def natural_key(name):
    """Mesmo critério do naturalSort() do app.js (numeric-aware sort)."""
    return [int(chunk) if chunk.isdigit() else chunk.lower()
            for chunk in re.split(r"(\d+)", name)]


def collect_image_files(input_path, work_dir):
    """Retorna uma lista de caminhos de imagem, em ordem natural.

    Se input_path for um .cbz/.zip, extrai antes para work_dir.
    Se for uma pasta, lista as imagens direto dela.
    Se for um arquivo de imagem único, retorna só ele.
    """
    if os.path.isdir(input_path):
        names = [f for f in os.listdir(input_path)
                  if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS]
        names.sort(key=natural_key)
        return [os.path.join(input_path, n) for n in names]

    ext = os.path.splitext(input_path)[1].lower()
    if ext in (".cbz", ".zip"):
        extract_dir = os.path.join(work_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(input_path) as zf:
            names = [n for n in zf.namelist()
                      if os.path.splitext(n)[1].lower() in IMAGE_EXTENSIONS]
            names.sort(key=natural_key)
            extracted_paths = []
            for n in names:
                # achata subpastas para evitar problema de path
                target_name = os.path.basename(n)
                target_path = os.path.join(extract_dir, target_name)
                with zf.open(n) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted_paths.append(target_path)
            return extracted_paths

    if ext in IMAGE_EXTENSIONS:
        return [input_path]

    raise ValueError(f"Não sei processar '{input_path}': "
                      f"passe uma pasta de imagens, um .cbz/.zip, ou uma imagem única.")


def run_kumiko_on_page(kumiko_bin, image_path, rtl, min_panel_size_ratio, work_dir):
    """Roda o Kumiko numa única imagem e devolve o dict de infos daquela página.

    Rodar página por página (em vez de apontar o Kumiko pra pasta toda) evita
    depender da ordenação alfabética interna do Kumiko — nós já controlamos
    a ordem antes de chamar.
    """
    out_path = os.path.join(work_dir, "page_out.json")
    if os.path.exists(out_path):
        os.remove(out_path)

    cmd = [kumiko_bin, "-i", image_path, "-o", out_path]
    if rtl:
        cmd.append("--rtl")
    if min_panel_size_ratio is not None:
        cmd += ["--min-panel-size-ratio", str(min_panel_size_ratio)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(out_path):
        print(f"[aviso] Kumiko falhou em '{image_path}':\n{result.stderr}",
              file=sys.stderr)
        return None

    with open(out_path, encoding="utf-8") as f:
        pages = json.load(f)

    if not pages:
        return None
    return pages[0]


def panels_to_fractions(panel_infos):
    """Converte painéis [x,y,w,h] em pixels do Kumiko para frações 0..1,
    que é o que o app.js espera (f.x, f.y, f.w, f.h relativos à página)."""
    width, height = panel_infos["size"]
    frames = []
    for (x, y, w, h) in panel_infos["panels"]:
        frames.append({
            "x": x / width,
            "y": y / height,
            "w": w / width,
            "h": h / height,
        })
    return frames


def main():
    parser = argparse.ArgumentParser(
        description="Converte a detecção de quadros do Kumiko para o formato "
                     "de marcações do Leitor de HQs.")
    parser.add_argument("--input", required=True,
                         help="Pasta com as páginas, um arquivo .cbz/.zip, ou uma imagem única.")
    parser.add_argument("--output", required=True,
                         help="Caminho do JSON de saída (ex: marcacoes-de-quadros.json).")
    default_kumiko_bin = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "kumiko", "kumiko"
    )
    parser.add_argument("--kumiko-bin", default=default_kumiko_bin,
                         help="Caminho para o executável do Kumiko "
                              f"(padrão: '{default_kumiko_bin}', já incluso neste pacote).")
    parser.add_argument("--rtl", action="store_true",
                         help="Numerar/ordenar os quadros da direita pra esquerda (mangá).")
    parser.add_argument("--min-panel-size-ratio", type=float, default=None,
                         help="Repassado ao Kumiko: tamanho mínimo de um painel, "
                              "como fração da página (padrão do Kumiko: 0.1).")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="kumiko_to_frames_") as work_dir:
        try:
            image_files = collect_image_files(args.input, work_dir)
        except ValueError as e:
            print(f"[erro] {e}", file=sys.stderr)
            sys.exit(1)

        if not image_files:
            print("[erro] Nenhuma imagem encontrada em --input.", file=sys.stderr)
            sys.exit(1)

        pages_out = []
        for i, image_path in enumerate(image_files, start=1):
            name = os.path.basename(image_path)
            print(f"[{i}/{len(image_files)}] Detectando quadros em {name}…",
                  file=sys.stderr)

            infos = run_kumiko_on_page(
                args.kumiko_bin, image_path, args.rtl,
                args.min_panel_size_ratio, work_dir,
            )

            frames = panels_to_fractions(infos) if infos else []
            if infos is None:
                print(f"    -> nenhum quadro detectado (página ficará sem marcações).",
                      file=sys.stderr)
            else:
                print(f"    -> {len(frames)} quadro(s) detectado(s).", file=sys.stderr)

            pages_out.append({"name": name, "frames": frames})

    data = {"version": 1, "pages": pages_out}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total_frames = sum(len(p["frames"]) for p in pages_out)
    print(f"\nPronto! {len(pages_out)} página(s), {total_frames} quadro(s) no total.")
    print(f"Arquivo salvo em: {args.output}")
    print("Importe esse arquivo no Leitor de HQs pelo botão \"Carregar marcações\" "
          "— lembrando de importar as MESMAS imagens, na MESMA ordem, antes.")


if __name__ == "__main__":
    main()
