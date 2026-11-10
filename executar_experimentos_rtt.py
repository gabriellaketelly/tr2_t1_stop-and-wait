"""Coleta sequencial da Entrega 3 exclusivamente no servidor UDP remoto.

Não inicia servidor nem proxy local. As perdas artificiais são descartes de
DATA no cliente; a transferência continua sendo feita pela rede real.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import random
import shlex
import shutil
import socket
import subprocess
import sys
import time

from protocolo_rdt import ErroProtocolo, negociar_sessao, validar_identificador
from validacao_metricas import validar_csv_metricas


SERVIDOR_REMOTO = "137.131.178.229"
RAIZ_PROJETO = Path(__file__).resolve().parent
CLIENTES = {"SAW": "cliente.py", "GBN": "cliente_gbn.py", "SR": "cliente_sr.py"}


def agora_em_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def validar_positivo(valor: str) -> float:
    numero = float(valor)
    if not math.isfinite(numero) or numero <= 0:
        raise argparse.ArgumentTypeError("valor deve ser finito e positivo")
    return numero


def validar_taxa_perda(valor: str) -> float:
    numero = float(valor)
    if not math.isfinite(numero) or not 0 <= numero < 1:
        raise argparse.ArgumentTypeError("perda deve estar entre 0 (inclusive) e 1 (exclusive)")
    return numero


def interpretar_par_parametros(valor: str) -> tuple[float, float]:
    try:
        alfa, beta = (float(parte) for parte in valor.split(":"))
    except ValueError as erro:
        raise argparse.ArgumentTypeError("use alpha:beta, por exemplo 0.125:0.25") from erro
    if not all(math.isfinite(valor) and 0 < valor <= 1 for valor in (alfa, beta)):
        raise argparse.ArgumentTypeError("alpha e beta devem pertencer a (0, 1]")
    return alfa, beta


def analisar_argumentos(argumentos_cli=None):
    interpretador = argparse.ArgumentParser(description=__doc__)
    interpretador.add_argument("--server", choices=(SERVIDOR_REMOTO,), default=SERVIDOR_REMOTO,
                        help="servidor remoto obrigatório; não há modo local")
    interpretador.add_argument("--port", type=int, default=8080)
    interpretador.add_argument("--group", type=validar_identificador, default="grupo08")
    interpretador.add_argument("--protocols", choices=("SAW", "GBN", "SR"), nargs="+", default=["SR"])
    interpretador.add_argument("--file", choices=("small", "medium", "large"), default="large")
    interpretador.add_argument("--window-size", type=int, choices=(4, 8, 16), default=16)
    interpretador.add_argument("--segment-size", type=int, default=512)
    interpretador.add_argument("--timeout", type=validar_positivo, default=0.2,
                        help="timeout fixo e RTO inicial em segundos")
    interpretador.add_argument("--rto-min", type=validar_positivo, default=0.01)
    interpretador.add_argument("--rto-max", type=validar_positivo, default=60.0)
    interpretador.add_argument("--max-retries", type=int, default=30)
    interpretador.add_argument("--loss-rates", type=validar_taxa_perda, nargs="+", default=[0.05, 0.10])
    interpretador.add_argument("--parameter-pairs", type=interpretar_par_parametros, nargs="+",
                        default=[(0.125, 0.25), (0.0625, 0.125), (0.25, 0.5)])
    interpretador.add_argument("--modes", choices=("fixed", "adaptive"), nargs="+",
                        default=["fixed", "adaptive"])
    interpretador.add_argument("--repetitions", type=int, default=3)
    interpretador.add_argument("--seed", type=int, default=20261109,
                        help="semente inicial; repetição r usa seed + r - 1")
    interpretador.add_argument("--baseline", action="store_true",
                        help="inclui referências com timeout fixo e perda 0%%")
    interpretador.add_argument("--baseline-protocols", choices=("SAW", "GBN", "SR"), nargs="+",
                        default=["SAW", "GBN", "SR"],
                        help="protocolos de referência sem perda quando --baseline é usado")
    interpretador.add_argument("--baseline-only", action="store_true",
                        help="somente SAW, GBN e SR fixos sem perda")
    interpretador.add_argument("--output-dir", type=Path, default=Path("entrega-3"))
    interpretador.add_argument("--run-timeout", type=validar_positivo, default=7200,
                        help="limite de segundos por transferência; falhas ficam no manifesto")
    interpretador.add_argument("--interval", type=float, default=1.0,
                        help="intervalo entre sessões em segundos")
    interpretador.add_argument("--resume", action="store_true",
                        help="retoma a mesma matriz e não repete execuções válidas")
    interpretador.add_argument("--continue-on-error", action="store_true")
    interpretador.add_argument("--skip-preflight", action="store_true",
                        help="omite a verificação HELLO/OK anterior à matriz")
    interpretador.add_argument("--preflight", action="store_true",
                        help="faz apenas o diagnóstico HELLO/OK e salva o manifesto")
    interpretador.add_argument("--preflight-timeout", type=validar_positivo, default=2.0,
                        help="timeout de cada uma das três tentativas HELLO de diagnóstico")
    interpretador.add_argument("--dry-run", action="store_true",
                        help="mostra comandos sem criar arquivos nem usar a rede")
    argumentos = interpretador.parse_args(argumentos_cli)
    if not 1 <= argumentos.port <= 65535 or not 1 <= argumentos.segment_size <= 512:
        interpretador.error("porta ou tamanho do segmento inválido")
    if argumentos.repetitions < 1 or argumentos.max_retries < 0:
        interpretador.error("repetitions deve ser positivo e max-retries não negativo")
    if argumentos.rto_min > argumentos.rto_max:
        interpretador.error("rto-min não pode exceder rto-max")
    if not math.isfinite(argumentos.interval) or argumentos.interval < 0:
        interpretador.error("interval deve ser finito e não negativo")
    if argumentos.preflight and argumentos.skip_preflight:
        interpretador.error("--preflight e --skip-preflight são mutuamente exclusivos")
    return argumentos


def formatar_numero(valor: float) -> str:
    """Representação que preserva o float, sem o sufixo .0 dos inteiros."""
    texto_numero = str(float(valor))
    return texto_numero[:-2] if texto_numero.endswith(".0") else texto_numero


def formatar_percentual_perda(taxa: float) -> str:
    # Multiplicar em float pode arredondar probabilidades distintas para o mesmo
    # percentual. Decimal preserva a representação completa de cada entrada.
    texto_numero = format(Decimal(str(taxa)) * 100, "f")
    return texto_numero.rstrip("0").rstrip(".") if "." in texto_numero else texto_numero


def identificar_configuracao(configuracao: dict) -> str:
    perda = formatar_percentual_perda(configuracao["loss_rate"])
    sufixo = (f"_a{formatar_numero(configuracao['alpha'])}_b{formatar_numero(configuracao['beta'])}"
              if configuracao["timeout_mode"] == "adaptive" else "")
    return (f"{configuracao['protocolo'].lower()}-w{configuracao['janela']}-loss{perda}-"
            f"{configuracao['timeout_mode']}{sufixo}-rep{configuracao['repeticao']:02d}")


def nomear_csv(configuracao: dict) -> str:
    nome = (f"resultado_{configuracao['protocolo']}_w{configuracao['janela']}_"
             f"loss{formatar_percentual_perda(configuracao['loss_rate'])}_{configuracao['timeout_mode']}")
    if configuracao["timeout_mode"] == "adaptive":
        nome += f"_alpha{formatar_numero(configuracao['alpha'])}_beta{formatar_numero(configuracao['beta'])}"
    return nome + f"_rep{configuracao['repeticao']:02d}.csv"


def montar_cenarios(argumentos) -> list[dict]:
    """Alterna a ordem das configurações por repetição, com semente registrada."""
    configuracoes = []
    for repeticao in range(1, argumentos.repetitions + 1):
        bloco = []
        if argumentos.baseline or argumentos.baseline_only:
            bloco.extend({"protocolo": protocolo, "janela": 1 if protocolo == "SAW" else argumentos.window_size,
                          "timeout_mode": "fixed", "alpha": None, "beta": None,
                            "loss_rate": 0.0, "loss_seed": argumentos.seed + repeticao - 1}
                         for protocolo in dict.fromkeys(argumentos.baseline_protocols))
        if not argumentos.baseline_only:
            for protocolo in dict.fromkeys(argumentos.protocols):
                for perda in dict.fromkeys(argumentos.loss_rates):
                    modos = [modo for modo in dict.fromkeys(argumentos.modes)
                             if protocolo != "SAW" or modo == "fixed"]
                    for modo in modos:
                        pares = argumentos.parameter_pairs if modo == "adaptive" else [(None, None)]
                        for alfa, beta in dict.fromkeys(pares):
                            bloco.append({"protocolo": protocolo,
                                          "janela": 1 if protocolo == "SAW" else argumentos.window_size,
                                          "timeout_mode": modo, "alpha": alfa, "beta": beta,
                                          "loss_rate": perda})
        # Baseline e matriz podem incluir a mesma configuração fixed/loss0.
        unicas = {json.dumps(linha, sort_keys=True): linha for linha in bloco}
        bloco = list(unicas.values())
        random.Random(argumentos.seed + repeticao - 1).shuffle(bloco)
        for linha in bloco:
            linha.update(repeticao=repeticao, loss_seed=argumentos.seed + repeticao - 1,
                       servidor=argumentos.server, porta=argumentos.port, grupo=argumentos.group,
                       arquivo=argumentos.file, segment_size=argumentos.segment_size,
                       timeout_s=argumentos.timeout, rto_min_s=argumentos.rto_min, rto_max_s=argumentos.rto_max,
                       max_retries=argumentos.max_retries)
            linha["id"] = identificar_configuracao(linha)
        configuracoes.extend(bloco)
    return configuracoes


def montar_comando(configuracao: dict, destino: Path) -> list[str]:
    comando = [sys.executable, str(RAIZ_PROJETO / CLIENTES[configuracao["protocolo"]]),
               "--server", configuracao["servidor"], "--port", str(configuracao["porta"]),
               "--group", configuracao["grupo"], "--file", configuracao["arquivo"],
               "--segment-size", str(configuracao["segment_size"]),
               "--timeout", str(configuracao["timeout_s"]),
               "--max-retries", str(configuracao["max_retries"]), "--output-dir", str(destino)]
    comando += ["--loss-rate", str(configuracao["loss_rate"]),
                "--loss-seed", str(configuracao["loss_seed"])]
    if configuracao["protocolo"] != "SAW":
        comando += ["--window-size", str(configuracao["janela"]),
                    "--timeout-mode", configuracao["timeout_mode"],
                    "--rto-min", str(configuracao["rto_min_s"]),
                    "--rto-max", str(configuracao["rto_max_s"])]
        if configuracao["timeout_mode"] == "adaptive":
            comando += ["--alpha", str(configuracao["alpha"]), "--beta", str(configuracao["beta"])]
    return comando


def salvar_json(caminho: Path, dados: dict) -> None:
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporario.replace(caminho)


def verificar_servidor(argumentos, manifesto: dict, caminho: Path) -> bool:
    """Verifica HELLO/OK; nunca cria um resumo de desempenho dessa sondagem."""
    registro = {"started_utc": agora_em_utc(), "status": "running",
             "description": "Somente HELLO/OK, sem transferência de DATA"}
    manifesto.setdefault("preflights", []).append(registro)
    salvar_json(caminho, manifesto)
    configuracao_sessao = argparse.Namespace(server=argumentos.server, port=argumentos.port, group=argumentos.group,
                                  file=argumentos.file, segment_size=argumentos.segment_size,
                                  timeout=argumentos.preflight_timeout, max_retries=2)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
            conexao.connect((argumentos.server, argumentos.port))
            registro["server_info"] = negociar_sessao(conexao, configuracao_sessao)
        registro["status"] = "success"
        print("Preflight remoto: HELLO/OK confirmado.", flush=True)
    except (OSError, ErroProtocolo, TimeoutError) as erro:
        registro.update(status="failed", error=str(erro))
        print(f"Preflight remoto falhou: {erro}. Nenhuma coleta iniciada.", flush=True)
    finally:
        registro["finished_utc"] = agora_em_utc()
        salvar_json(caminho, manifesto)
    return registro["status"] == "success"


def validar_resultado(caminho_resumo: Path, configuracao: dict) -> dict:
    resumo = json.loads(caminho_resumo.read_text(encoding="utf-8"))
    if resumo.get("checksum_ok") is not True or resumo.get("done_ok") is not True:
        raise ValueError("MD5 ou DONE não confirmou a transferência")
    if resumo.get("servidor") != SERVIDOR_REMOTO:
        raise ValueError("resultado não foi coletado no servidor remoto exigido")
    recebido = caminho_resumo.parent / "arquivo.bin"
    if not recebido.is_file() or recebido.stat().st_size != resumo["file_size"]:
        raise ValueError("arquivo recebido ausente ou tamanho inconsistente")
    calculador_md5 = hashlib.md5()
    with recebido.open("rb") as arquivo_aberto:
        for trecho in iter(lambda: arquivo_aberto.read(1024 * 1024), b""):
            calculador_md5.update(trecho)
    if (calculador_md5.hexdigest() != resumo["md5_esperado"]
            or resumo.get("md5_recebido") != resumo["md5_esperado"]):
        raise ValueError("MD5 do arquivo recebido não confere com o servidor")
    validar_csv_metricas(caminho_resumo.parent / "metricas.csv", resumo)
    for chave in ("arquivo", "grupo", "porta", "segment_size"):
        if resumo.get(chave) != configuracao[chave]:
            raise ValueError(f"metadado divergente: {chave}")
    esperados = {"protocolo": configuracao["protocolo"], "janela": configuracao["janela"],
                "timeout_mode": configuracao["timeout_mode"], "loss_rate": configuracao["loss_rate"],
                "timeout_s": configuracao["timeout_s"]}
    padroes = {"protocolo": "SAW", "janela": 1, "timeout_mode": "fixed", "loss_rate": 0.0}
    esperados["loss_seed"] = configuracao["loss_seed"]
    if configuracao["timeout_mode"] == "adaptive":
        esperados.update({chave: configuracao[chave] for chave in ("alpha", "beta", "rto_min_s", "rto_max_s")})
    for chave, valor in esperados.items():
        if resumo.get(chave, padroes.get(chave)) != valor:
            raise ValueError(f"configuração divergente: {chave}")
    return resumo


def executar_cenario(argumentos, configuracao: dict, manifesto: dict, caminho_manifesto: Path) -> bool:
    raiz = argumentos.output_dir.resolve()
    tentativa = 1 + sum(linha["id"] == configuracao["id"] for linha in manifesto["runs"])
    pasta = raiz / configuracao["id"] / f"tentativa-{tentativa:02d}"
    pasta.mkdir(parents=True, exist_ok=False)
    comando = montar_comando(configuracao, pasta)
    registro = {"id": configuracao["id"], "attempt": tentativa, "config": configuracao,
             "output_dir": str(pasta.relative_to(raiz)), "command": comando,
             "started_utc": agora_em_utc(), "status": "running"}
    manifesto["runs"].append(registro)
    salvar_json(caminho_manifesto, manifesto)
    print(f"[{configuracao['id']}] " + shlex.join(comando), flush=True)
    inicio = time.monotonic()
    try:
        with (pasta / "cliente.log").open("w", encoding="utf-8") as registro_saida:
            concluido = subprocess.run(comando, cwd=RAIZ_PROJETO, stdout=registro_saida,
                                       stderr=subprocess.STDOUT, timeout=argumentos.run_timeout,
                                       check=False)
        registro["returncode"] = concluido.returncode
        if concluido.returncode:
            raise RuntimeError(f"cliente retornou {concluido.returncode}; consulte cliente.log")
        pasta_protocolo = pasta if configuracao["protocolo"] == "SAW" else pasta / configuracao["protocolo"].lower()
        caminho_resumo = pasta_protocolo / configuracao["arquivo"] / "resumo.json"
        resumo = validar_resultado(caminho_resumo, configuracao)
        resumo.update({"protocolo": configuracao["protocolo"], "janela": configuracao["janela"],
                        "loss_rate": configuracao["loss_rate"], "timeout_mode": configuracao["timeout_mode"],
                        "repeticao": configuracao["repeticao"], "loss_seed": configuracao["loss_seed"],
                        "coleta_ambiente": "remoto", "coleta_inicio_utc": registro["started_utc"],
                        "experimento_id": configuracao["id"]})
        if configuracao["timeout_mode"] == "fixed":
            resumo["alpha"] = resumo["beta"] = None
        salvar_json(caminho_resumo, resumo)
        nome = nomear_csv(configuracao)
        shutil.copy2(caminho_resumo.parent / "metricas.csv", pasta / nome)
        registro.update(status="success", summary=str(caminho_resumo.relative_to(raiz)),
                     csv=str((pasta / nome).relative_to(raiz)),
                     md5=resumo["md5_recebido"])
        print(f"  OK: {resumo['duracao_s']:.3f} s, "
              f"{resumo['throughput_medido_bps'] / 1e6:.3f} Mbit/s, "
              f"{resumo['retransmissoes']} retransmissões", flush=True)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as erro:
        registro.update(status="failed", error=str(erro))
        print(f"  FALHA: {erro}", flush=True)
    except KeyboardInterrupt:
        registro.update(status="interrupted", error="interrompido pelo operador")
        raise
    finally:
        registro.update(finished_utc=agora_em_utc(), wall_duration_s=time.monotonic() - inicio)
        salvar_json(caminho_manifesto, manifesto)
    return registro["status"] == "success"


def principal(argumentos_cli=None) -> int:
    argumentos = analisar_argumentos(argumentos_cli)
    configuracoes = montar_cenarios(argumentos)
    if argumentos.dry_run:
        for configuracao in configuracoes:
            print(shlex.join(montar_comando(configuracao, argumentos.output_dir / configuracao["id"] / "tentativa-01")))
        print(f"{len(configuracoes)} transferências remotas; nenhum comando executado.")
        return 0
    argumentos.output_dir.mkdir(parents=True, exist_ok=True)
    caminho = argumentos.output_dir / "manifesto.json"
    especificacao = {"version": 1, "server": SERVIDOR_REMOTO, "scenarios": configuracoes}
    if caminho.exists():
        if not argumentos.resume:
            raise SystemExit("Já existe manifesto; use --resume ou escolha outra pasta.")
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
        if manifesto["specification"] != especificacao:
            raise SystemExit("A matriz difere do manifesto. Retome com os mesmos argumentos ou use outra pasta.")
    else:
        manifesto = {"created_utc": agora_em_utc(), "specification": especificacao, "runs": [],
                    "method": "UDP remoto; descarte de DATA no cliente; sem proxy; sessões sequenciais"}
    for registro in manifesto["runs"]:
        if registro["status"] == "running":
            registro.update(status="interrupted", error="processo anterior não concluiu o manifesto")
    salvar_json(caminho, manifesto)
    if not argumentos.skip_preflight and not verificar_servidor(argumentos, manifesto, caminho):
        return 1
    if argumentos.preflight:
        return 0
    falhas = 0
    for indice, configuracao in enumerate(configuracoes):
        anteriores = [linha for linha in manifesto["runs"]
                    if linha["id"] == configuracao["id"] and linha["status"] == "success"]
        if anteriores:
            try:
                validar_resultado(argumentos.output_dir / anteriores[-1]["summary"], configuracao)
            except (OSError, ValueError, KeyError) as erro:
                anteriores[-1].update(status="invalidated", error=str(erro))
                salvar_json(caminho, manifesto)
            else:
                print(f"[{configuracao['id']}] já concluído; preservado.", flush=True)
                continue
        if not executar_cenario(argumentos, configuracao, manifesto, caminho):
            falhas += 1
            if not argumentos.continue_on_error:
                print("Matriz interrompida; retome com --resume após resolver a falha.")
                break
        if indice + 1 < len(configuracoes):
            time.sleep(argumentos.interval)
    ids_validos = {linha["id"] for linha in manifesto["runs"] if linha["status"] == "success"}
    concluido = all(configuracao["id"] in ids_validos for configuracao in configuracoes)
    print(f"{len(ids_validos)}/{len(configuracoes)} configurações concluídas. Manifesto: {caminho}")
    return 0 if concluido and falhas == 0 else 1


if __name__ == "__main__":
    raise SystemExit(principal())
