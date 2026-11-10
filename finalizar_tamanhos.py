"""Atualiza análise, relatório e pacote portátil após a coleta dos três tamanhos."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from zoneinfo import ZoneInfo


RAIZ = Path(__file__).resolve().parent


def empacotar(relatorio: Path, analise: Path, capturas: Path, destino: Path) -> Path:
    """Gera pacote isolado, preservando as planilhas e entregas anteriores."""
    estado = json.loads((relatorio / "status.json").read_text(encoding="utf-8"))
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pacote-tamanhos-") as temporario:
        pasta = Path(temporario)
        fonte = (relatorio / "relatorio_final.tex").read_text(encoding="utf-8")
        referencias = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{\\detokenize\{([^}]+)\}\}", fonte)
        for referencia in referencias:
            original = Path(referencia)
            if not original.is_absolute():
                original = relatorio / original
            nome = original.name
            copia = pasta / nome
            if copia.exists() and copia.read_bytes() != original.read_bytes():
                raise ValueError(f"Figuras distintas têm o mesmo nome: {nome}")
            shutil.copy2(original, copia)
            fonte = fonte.replace(r"\detokenize{" + referencia + "}", r"\detokenize{" + nome + "}")
        (pasta / "relatorio_final.tex").write_text(fonte, encoding="utf-8")
        for nome in ("relatorio_final.pdf", "status.json"):
            shutil.copy2(relatorio / nome, pasta / nome)
        for original in sorted((relatorio / "anexos").rglob("*.csv")):
            relativo = original.relative_to(relatorio)
            (pasta / relativo).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, pasta / relativo)
        for original in sorted(analise.glob("integrados_*.csv")):
            shutil.copy2(original, pasta / original.name)
        pasta_graficos_discussao = analise / "graficos_discussao"
        if pasta_graficos_discussao.is_dir():
            (pasta / "graficos_discussao").mkdir(parents=True, exist_ok=True)
            for original in sorted(pasta_graficos_discussao.iterdir()):
                if original.is_file():
                    shutil.copy2(original, pasta / "graficos_discussao" / original.name)
        for nome in ("correlacao.csv", "retransmissoes.csv"):
            original = capturas / nome
            if original.is_file():
                shutil.copy2(original, pasta / nome)
        pendencias = estado.get("pendencias", [])
        texto = (
            f"{estado['titulo']} — Grupo 08.\n"
            "Requisito: small, medium e large nas três entregas.\n"
            "Compile relatorio_final.tex com pdflatex; as figuras usam caminhos locais.\n"
            "Os CSVs em anexos documentam os dados medidos e a cobertura por tamanho.\n"
            "As coletas originais e os pacotes anteriores foram preservados.\n"
        )
        if pendencias:
            texto += "\nPACOTE PARCIAL: ainda não atende a todos os requisitos.\n"
            texto += "\n".join("- " + item for item in pendencias) + "\n"
        else:
            texto += f"\nCobertura validada. PDF com {estado.get('paginas', '?')} páginas.\n"
        (pasta / "LEIA-ME.txt").write_text(texto, encoding="utf-8")
        arquivo_zip = destino / "relatorio_latex_pdf_figuras.zip"
        temporario_zip = arquivo_zip.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporario_zip, "w", zipfile.ZIP_DEFLATED) as arquivo:
            for original in sorted(pasta.rglob("*")):
                if original.is_file():
                    arquivo.write(original, original.relative_to(pasta))
        temporario_zip.replace(arquivo_zip)
        for nome in ("relatorio_final.pdf", "status.json", "LEIA-ME.txt"):
            shutil.copy2(pasta / nome, destino / nome)
    return arquivo_zip


def principal(argumentos_cli=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=RAIZ / "entrega-3")
    parser.add_argument("--package-dir", type=Path)
    args = parser.parse_args(argumentos_cli)
    entrada = args.input_dir.resolve()
    analise, relatorio, capturas = (entrada / nome for nome in ("analise", "relatorio", "wireshark"))
    destino = (args.package_dir or entrada / "para_upload" / "tres_tamanhos").resolve()
    estado = {"inicio": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(), "status": "running"}
    caminho_estado = entrada / "status_atualizacao_tamanhos.json"
    caminho_estado.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n")
    try:
        subprocess.run([sys.executable, str(RAIZ / "analisar_rtt.py"),
                        "--input-dir", str(entrada), "--output-dir", str(analise)], check=True, cwd=RAIZ)
        subprocess.run([sys.executable, str(RAIZ / "gerar_relatorio_rtt.py"),
                        "--input-dir", str(entrada), "--analysis-dir", str(analise),
                        "--output-dir", str(relatorio)], check=True, cwd=RAIZ)
        arquivo_zip = empacotar(relatorio, analise, capturas, destino)
        situacao = json.loads((relatorio / "status.json").read_text())
        estado.update(status="partial" if situacao["pendencias"] else "complete",
                      pendencias=situacao["pendencias"], pacote=str(arquivo_zip))
        print(f"{situacao['titulo']}: {arquivo_zip}", flush=True)
        return 0 if not situacao["pendencias"] else 2
    except Exception as erro:
        estado.update(status="failed", erro=str(erro))
        raise
    finally:
        estado["fim"] = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
        caminho_estado.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(principal())
