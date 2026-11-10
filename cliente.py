"""Cliente Stop-and-Wait do protocolo RDT-UnB v1.0 (somente UDP)."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import socket
import time

from registro_metricas import COLUNAS_METRICAS, campos_csv_enunciado, nomear_csv_metricas
from simulacao_perdas import SimuladorPerdas
from protocolo_rdt import (
    ErroProtocolo,
    confirmacao_nao_suportada,
    finalizar,
    interpretar_dados,
    negociar_sessao,
    trocar_mensagem,
    validar_identificador,
)


def analisar_argumentos(lista_argumentos=None):
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--server", default="137.131.178.229")
    analisador.add_argument("--port", type=int, default=8080)
    analisador.add_argument("--group", required=True, type=validar_identificador)
    analisador.add_argument("--file", choices=("small", "medium", "large"), default="small")
    analisador.add_argument("--segment-size", type=int, default=512)
    analisador.add_argument(
        "--timeout", type=float, default=0.5,
        help="timeout fixo em segundos (padrão 0.5, cerca de 4× o p99 RTT medido no servidor)",
    )
    analisador.add_argument("--max-retries", type=int, default=10)
    analisador.add_argument("--loss-rate", type=float, default=0.0,
                            help="probabilidade de descartar DATA no receptor, entre 0 e 1")
    analisador.add_argument("--loss-seed", type=int,
                            help="semente opcional para repetir os descartes simulados")
    analisador.add_argument("--output-dir", type=Path, default=Path("resultados"))
    argumentos = analisador.parse_args(lista_argumentos)
    if not 1 <= argumentos.segment_size <= 512:
        analisador.error("--segment-size deve estar entre 1 e 512")
    if (not math.isfinite(argumentos.timeout) or argumentos.timeout <= 0
            or argumentos.max_retries < 0):
        analisador.error("timeout deve ser positivo e max-retries não negativo")
    if not math.isfinite(argumentos.loss_rate) or not 0 <= argumentos.loss_rate <= 1:
        analisador.error("--loss-rate deve estar entre 0 e 1")
    if not 1 <= argumentos.port <= 65535:
        analisador.error("porta inválida")
    return argumentos


def receber_segmento(conexao, sequencia, tamanho_esperado, tamanho_arquivo,
                     timeout_segundos, max_retransmissoes, avisos=None,
                     metadados=None, inicio_transferencia=None, perdas=None):
    inicio = time.perf_counter()
    req_timestamp_epoch = ""
    perdas_simuladas = 0
    for tentativa in range(max_retransmissoes + 1):
        req_timestamp_epoch = f"{time.time():.9f}"
        conexao.send(f"REQ|seq={sequencia}".encode("ascii"))
        prazo = time.perf_counter() + timeout_segundos
        while True:
            tempo_restante = prazo - time.perf_counter()
            if tempo_restante <= 0:
                break
            conexao.settimeout(tempo_restante)
            try:
                pacote = conexao.recv(65507)
            except socket.timeout:
                break
            if pacote.startswith(b"ERROR"):
                if confirmacao_nao_suportada(pacote, avisos):
                    continue
                raise ErroProtocolo(pacote.decode("ascii", errors="replace"))
            try:
                sequencia_recebida, tamanho_total, conteudo = interpretar_dados(pacote)
            except ErroProtocolo:
                continue
            # A especificação não esclarece se total é o tamanho do arquivo
            # ou do payload. Aceitamos ambos, validando o payload pelo OK.
            if sequencia_recebida != sequencia or len(conteudo) != tamanho_esperado:
                continue
            if tamanho_total not in (tamanho_esperado, tamanho_arquivo):
                continue
            if perdas is not None and perdas.descartar(sequencia, tentativa):
                perdas_simuladas += 1
                continue
            tempo_decorrido = time.perf_counter() - inicio
            recebido_timestamp_epoch = f"{time.time():.9f}"
            linha = {
                **(metadados or {}),
                "seq": sequencia, "bytes": len(conteudo),
                "rtt_ms": tempo_decorrido * 1000 if tentativa == 0 else "",
                "tempo_segmento_ms": tempo_decorrido * 1000,
                "throughput_bps": len(conteudo) * 8 / tempo_decorrido,
                "retransmissoes": tentativa, "timeout_ocorrido": int(tentativa > 0),
                "simulated_loss": perdas_simuladas,
                "req_timestamp_epoch": req_timestamp_epoch,
                "data_timestamp_epoch": recebido_timestamp_epoch,
                "received_elapsed_s": (time.perf_counter() - inicio_transferencia
                                        if inicio_transferencia is not None else ""),
                "rtt_est_ms": "", "dev_rtt_ms": "", "timeout_ms": timeout_segundos * 1000,
                "timeout_usado_ms": timeout_segundos * 1000,
                "rtt_sample_valid": int(tentativa == 0),
                **campos_csv_enunciado(
                    sequencia, recebido_timestamp_epoch, len(conteudo), "",
                    len(conteudo) * 8 / tempo_decorrido, tentativa, 1, "SAW",
                ),
            }
            return conteudo, linha
    raise TimeoutError(f"Segmento {sequencia}: limite de retransmissões atingido")


def baixar_com_stop_and_wait(conexao, argumentos, informacoes):
    diretorio = argumentos.output_dir / argumentos.file
    diretorio.mkdir(parents=True, exist_ok=True)
    # Evita apresentar um resumo de execução anterior como resultado atual.
    for nome in ("resumo.json", "graficos.png", "graficos.pdf", "arquivo.bin"):
        (diretorio / nome).unlink(missing_ok=True)
    calculador_md5 = hashlib.md5()
    amostras_rtt = []
    retransmissoes = expiracoes = bytes_recebidos = perdas_simuladas_total = 0
    avisos = set()
    perdas = SimuladorPerdas(argumentos.loss_rate, argumentos.loss_seed)
    inicio = time.perf_counter()
    inicio_epoch = time.time()
    metadados = {"grupo": argumentos.group, "servidor": argumentos.server,
                 "porta": argumentos.port, "arquivo": argumentos.file, "protocolo": "SAW"}
    arquivo_parcial = diretorio / "arquivo.part"
    with arquivo_parcial.open("wb") as arquivo_saida, (diretorio / "metricas.csv").open(
        "w", newline="", encoding="utf-8"
    ) as arquivo_metricas:
        escritor = csv.DictWriter(arquivo_metricas, fieldnames=COLUNAS_METRICAS)
        escritor.writeheader()
        for sequencia in range(informacoes["total_segments"]):
            tamanho_esperado = min(
                informacoes["segment_size"], informacoes["file_size"] - bytes_recebidos,
            )
            conteudo, linha = receber_segmento(
                conexao, sequencia, tamanho_esperado, informacoes["file_size"],
                argumentos.timeout, argumentos.max_retries, avisos,
                metadados=metadados, inicio_transferencia=inicio, perdas=perdas,
            )
            arquivo_saida.write(conteudo)
            calculador_md5.update(conteudo)
            bytes_recebidos += len(conteudo)
            conexao.send(f"ACK|seq={sequencia}".encode("ascii"))
            escritor.writerow(linha)
            if linha["rtt_ms"] != "":
                amostras_rtt.append(linha["rtt_ms"] / 1000)
            retransmissoes += linha["retransmissoes"]
            expiracoes += linha["timeout_ocorrido"]
            perdas_simuladas_total += linha["simulated_loss"]
            if (sequencia + 1) % 100 == 0 or sequencia + 1 == informacoes["total_segments"]:
                print(f"{argumentos.file}: {sequencia + 1}/{informacoes['total_segments']} segmentos", flush=True)
    duracao = time.perf_counter() - inicio
    checksum = calculador_md5.hexdigest()
    checksum_valido = bytes_recebidos == informacoes["file_size"] and checksum == informacoes["checksum"]
    confirmado = finalizar(conexao, checksum, argumentos, avisos)
    rtt_medio = sum(amostras_rtt) / len(amostras_rtt) if amostras_rtt else None
    resumo = {
        "grupo": argumentos.group, "arquivo": argumentos.file, "servidor": argumentos.server,
        "porta": argumentos.port, "file_size": bytes_recebidos, "segment_size": informacoes["segment_size"],
        "total_segments": informacoes["total_segments"], "seed": informacoes["seed"],
        "md5_esperado": informacoes["checksum"], "md5_recebido": checksum,
        "checksum_ok": checksum_valido, "done_ok": confirmado, "duracao_s": duracao,
        "rtt_medio_s": rtt_medio, "amostras_rtt": len(amostras_rtt),
        "throughput_medido_bps": bytes_recebidos * 8 / duracao,
        "throughput_teorico_bps": informacoes["segment_size"] * 8 / rtt_medio if rtt_medio else None,
        "retransmissoes": retransmissoes, "segmentos_com_timeout": expiracoes,
        "timeout_s": argumentos.timeout,
        "loss_rate": argumentos.loss_rate, "loss_seed": argumentos.loss_seed,
        "simulated_loss_total": perdas_simuladas_total,
        "metrics_file": nomear_csv_metricas(
            diretorio / "metricas.csv", argumentos.group, "saw", inicio_epoch,
        ),
        "avisos_servidor": sorted(avisos),
    }
    (diretorio / "resumo.json").write_text(
        json.dumps(resumo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    if not checksum_valido or not confirmado:
        raise ErroProtocolo("Integridade não confirmada; consulte resumo.json")
    arquivo_parcial.replace(diretorio / "arquivo.bin")
    return resumo


def principal(lista_argumentos=None):
    argumentos = analisar_argumentos(lista_argumentos)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
            # connect em UDP fixa o peer; não cria uma conexão TCP.
            conexao.connect((argumentos.server, argumentos.port))
            informacoes = negociar_sessao(conexao, argumentos)
            print(f"Sessão: {informacoes['file_size']} bytes, segmento {informacoes['segment_size']} bytes")
            resumo = baixar_com_stop_and_wait(conexao, argumentos, informacoes)
            print(f"MD5: {resumo['md5_recebido']} — DONE|ok=1")
            print(f"Throughput: {resumo['throughput_medido_bps']:.2f} bit/s")
        return 0
    except (OSError, ErroProtocolo, TimeoutError, UnicodeError) as erro:
        print(f"Erro: {erro}")
        return 1


if __name__ == "__main__":
    raise SystemExit(principal())
