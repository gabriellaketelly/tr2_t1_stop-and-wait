"""Compilação da fonte LaTeX e verificação do limite de páginas."""

import shutil
import subprocess


def compilar_pdf(fonte, limite_paginas=15):
    """Compila duas vezes para resolver referências e retorna PDF e páginas."""
    if shutil.which("pdflatex") is None:
        raise RuntimeError("pdflatex não encontrado; fonte e anexos foram preservados")
    for _ in range(2):
        processo = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", fonte.name],
            cwd=fonte.parent, capture_output=True, text=True, errors="replace",
        )
        if processo.returncode:
            raise RuntimeError("pdflatex falhou; consulte " + str(fonte.with_suffix(".log")))
    pdf = fonte.with_suffix(".pdf")
    paginas = None
    if shutil.which("pdfinfo"):
        informacoes = subprocess.run(
            ["pdfinfo", str(pdf)], check=True, capture_output=True, text=True,
        )
        paginas = next(int(linha.split(":", 1)[1])
                       for linha in informacoes.stdout.splitlines()
                       if linha.startswith("Pages:"))
        if paginas > limite_paginas:
            raise RuntimeError(
                f"PDF tem {paginas} páginas; revise a seleção para respeitar "
                f"o limite de {limite_paginas}"
            )
    return pdf, paginas
