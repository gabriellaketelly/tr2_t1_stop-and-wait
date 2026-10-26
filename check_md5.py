"""Compara o MD5 do arquivo original com todos os arquivos recebidos."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--received-dir", type=Path, default=Path("resultados_experimentos"))
    args = parser.parse_args()
    if not args.original.is_file():
        parser.error(f"arquivo original não encontrado: {args.original}")
    original_hash = md5(args.original)
    received = sorted(
        path for path in args.received_dir.rglob("arquivo.bin")
        if path.is_file()
    )
    print("| Arquivo | MD5 | Igual ao original |")
    print("|---|---|---|")
    print(f"| original: `{args.original}` | `{original_hash}` | — |")
    for path in received:
        digest = md5(path)
        print(f"| `{path}` | `{digest}` | {'SIM' if digest == original_hash else 'NÃO'} |")
    if not received:
        print(f"Nenhum arquivo recebido encontrado em {args.received_dir}")
        return 1
    return 0 if all(md5(path) == original_hash for path in received) else 2


if __name__ == "__main__":
    raise SystemExit(main())
