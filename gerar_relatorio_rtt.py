"""Gera relatório PDF auditável (até 15 páginas), fonte LaTeX e anexos.

Não substitui medições ou screenshots ausentes por resultados sintéticos.
Requer pdflatex; pdfinfo, quando disponível, verifica o limite de páginas.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from relatorio_rtt.compilacao import compilar_pdf
from relatorio_rtt.conteudo import gerar_documento


def analisar_argumentos(argumentos_cli=None):
    interpretador = argparse.ArgumentParser(description=__doc__)
    interpretador.add_argument("--input-dir", dest="diretorio_entrada", type=Path,
                              default=Path("entrega-3"))
    interpretador.add_argument("--analysis-dir", dest="diretorio_analise", type=Path)
    interpretador.add_argument("--wireshark-dir", dest="diretorio_wireshark", type=Path)
    interpretador.add_argument("--output-dir", dest="diretorio_saida", type=Path)
    interpretador.add_argument("--tex-only", dest="somente_latex", action="store_true")
    argumentos = interpretador.parse_args(argumentos_cli)
    argumentos.diretorio_entrada = argumentos.diretorio_entrada.resolve()
    argumentos.diretorio_analise = (
        argumentos.diretorio_analise or argumentos.diretorio_entrada / "analise"
    ).resolve()
    argumentos.diretorio_wireshark = (
        argumentos.diretorio_wireshark or argumentos.diretorio_entrada / "wireshark"
    ).resolve()
    argumentos.diretorio_saida = (
        argumentos.diretorio_saida or argumentos.diretorio_entrada / "relatorio"
    ).resolve()
    return argumentos


def principal(argumentos_cli=None):
    argumentos = analisar_argumentos(argumentos_cli)
    try:
        fonte, situacao = gerar_documento(argumentos)
        if not argumentos.somente_latex:
            pdf, paginas = compilar_pdf(fonte)
            if paginas is not None:
                situacao["paginas"] = paginas
            print(pdf)
        (argumentos.diretorio_saida / "status.json").write_text(
            json.dumps(situacao, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        print(f"{situacao['titulo']}: {len(situacao['pendencias'])} pendências; "
              f"{situacao['csvs_anexados']} CSVs anexados.")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(principal())
