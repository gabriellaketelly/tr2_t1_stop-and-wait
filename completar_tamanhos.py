"""Executa, de forma retomável, as campanhas que faltam por tamanho.

Cada chamada ao executor tem manifesto próprio. Assim, uma interrupção permite
usar ``--resume`` sem repetir transferências já validadas.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def run(cmd: list[str], dry: bool) -> int:
    print("$", " ".join(cmd), flush=True)
    if dry:
        return 0
    return subprocess.run(cmd, cwd=ROOT).returncode


def campanha_e2(output: Path, tamanho: str, janela: int, dry: bool) -> int:
    # A pasta medium/w16 já foi iniciada manualmente e pode ser retomada.
    cmd = [sys.executable, str(ROOT / "executar_experimentos_rtt.py"),
           "--protocols", "GBN", "SR", "--file", tamanho,
           "--window-size", str(janela), "--modes", "fixed",
           "--loss-rates", "0", "0.05", "0.10", "--repetitions", "3",
           "--seed", "20261109", "--timeout", "0.2", "--max-retries", "30",
           "--output-dir", str(output), "--continue-on-error"]
    if (output / "manifesto.json").is_file():
        cmd.append("--resume")
    return run(cmd, dry)


def campanha_e3(output: Path, tamanho: str, dry: bool) -> int:
    # SAW é fixo; GBN/SR têm referência fixa e adaptação sem perda. As campanhas
    # de large já existem e são preservadas pelo --resume.
    cmd = [sys.executable, str(ROOT / "executar_experimentos_rtt.py"),
           "--protocols", "SAW", "GBN", "SR", "--file", tamanho,
           "--window-size", "16", "--modes", "fixed", "adaptive",
           "--loss-rates", "0", "--parameter-pairs", "0.0625:0.125",
           "--repetitions", "3", "--seed", "20261109", "--timeout", "0.2",
           "--max-retries", "30", "--baseline", "--baseline-protocols",
           "SAW", "GBN", "SR", "--output-dir", str(output),
           "--continue-on-error"]
    if (output / "manifesto.json").is_file():
        cmd.append("--resume")
    return run(cmd, dry)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=("e2", "e3", "all"), default="all")
    args = parser.parse_args(argv)
    jobs: list[tuple[str, Path, str, int | None]] = []
    if args.only in ("e2", "all"):
        for tamanho in ("medium", "large"):
            for janela in (4, 8, 16):
                jobs.append(("e2", ROOT / "entrega-2-remota" / "complemento-tamanhos" / tamanho / f"w{janela}", tamanho, janela))
    if args.only in ("e3", "all"):
        for tamanho in ("small", "medium"):
            jobs.append(("e3", ROOT / "entrega-3" / "complemento-tamanhos" / tamanho, tamanho, None))
    for tipo, destino, tamanho, janela in jobs:
        destino.mkdir(parents=True, exist_ok=True)
        codigo = campanha_e2(destino, tamanho, janela, args.dry_run) if tipo == "e2" else campanha_e3(destino, tamanho, args.dry_run)
        if codigo and not args.dry_run:
            print(f"Falha em {tipo}/{tamanho}/{janela}; o manifesto permite retomar.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
