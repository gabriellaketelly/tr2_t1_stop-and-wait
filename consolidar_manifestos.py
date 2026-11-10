"""Consolida manifestos de campanhas remotas no pacote do relatório final."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def ler_json(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar_json(caminho: Path, dados: dict) -> None:
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporario.replace(caminho)


def tornar_caminho_relativo(caminho: str | None, pasta_origem: Path, raiz_saida: Path) -> str | None:
    if not caminho:
        return caminho
    return str((pasta_origem / caminho).resolve().relative_to(raiz_saida.resolve()))


def identificador_unico(configuracao: dict, pasta_origem: Path, usados: set[str]) -> str:
    identificador = configuracao["id"]
    if identificador in usados:
        identificador = f"{configuracao['protocolo'].lower()}-{configuracao['arquivo']}-{identificador}"
    if identificador in usados:
        raise ValueError(f"Identificador duplicado após qualificação: {identificador}")
    return identificador


def consolidar_manifestos(pastas: list[Path], destino: Path) -> dict:
    raiz = destino.resolve()
    cenarios, execucoes, preflights = [], [], []
    identificadores_cenarios: set[str] = set()
    for pasta in pastas:
        manifesto = ler_json(pasta / "manifesto.json")
        for cenario_original in manifesto.get("specification", {}).get("scenarios", []):
            cenario = dict(cenario_original)
            cenario["id"] = identificador_unico(cenario, pasta, identificadores_cenarios)
            identificadores_cenarios.add(cenario["id"])
            cenarios.append(cenario)
        for execucao_original in manifesto.get("runs", []):
            execucao = dict(execucao_original)
            configuracao = dict(execucao.get("config", {}))
            identificador_original = configuracao.get("id", execucao.get("id"))
            candidatos = [c for c in cenarios
                if c.get("id", "").endswith(identificador_original or "")
                and c.get("protocolo") == configuracao.get("protocolo")
                and c.get("arquivo") == configuracao.get("arquivo")
                and c.get("repeticao") == configuracao.get("repeticao")
                and c.get("loss_rate") == configuracao.get("loss_rate")
                and c.get("timeout_mode") == configuracao.get("timeout_mode")]
            correspondente = candidatos[-1] if candidatos else None
            if correspondente is not None:
                execucao["id"] = correspondente["id"]
                configuracao["id"] = correspondente["id"]
                execucao["config"] = configuracao
            for campo in ("output_dir", "summary", "csv"):
                execucao[campo] = tornar_caminho_relativo(execucao.get(campo), pasta, raiz)
            if execucao.get("status") == "success" and execucao.get("summary"):
                resumo_path = raiz / execucao["summary"]
                resumo = ler_json(resumo_path)
                resumo["experimento_id"] = execucao["id"]
                resumo["campanha"] = "relatorio-final"
                salvar_json(resumo_path, resumo)
            execucoes.append(execucao)
        preflights.extend(manifesto.get("preflights", []))
    resultado = {
        "created_utc": None,
        "specification": {"version": 1, "server": "137.131.178.229", "scenarios": cenarios},
        "runs": execucoes,
        "preflights": preflights,
        "method": "Campanha final; todas as transferências realizadas por UDP no servidor remoto; manifestos de cada entrega preservados nas pastas de execução.",
    }
    salvar_json(raiz / "manifesto.json", resultado)
    return resultado


def analisar_argumentos(argumentos_cli=None):
    interpretador = argparse.ArgumentParser(description=__doc__)
    interpretador.add_argument("--input-dirs", type=Path, nargs="+", required=True)
    interpretador.add_argument("--output-dir", type=Path, default=Path("relatorio-final"))
    argumentos = interpretador.parse_args(argumentos_cli)
    argumentos.input_dirs = [caminho.resolve() for caminho in argumentos.input_dirs]
    argumentos.output_dir = argumentos.output_dir.resolve()
    return argumentos


def principal(argumentos_cli=None) -> int:
    argumentos = analisar_argumentos(argumentos_cli)
    resultado = consolidar_manifestos(argumentos.input_dirs, argumentos.output_dir)
    print(f"{len(resultado['runs'])} execuções, {len(resultado['specification']['scenarios'])} cenários consolidados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
