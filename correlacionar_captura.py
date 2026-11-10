"""Exporta evidências reais de uma captura UDP usando o TShark do Wireshark.

Não produz screenshots: abra o PCAP no Wireshark e anote as imagens pedidas
no enunciado. As tabelas apontam os frames exatos para essa inspeção.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess


def localizar_tshark(caminho_explicito=None):
    executavel = caminho_explicito or shutil.which("tshark")
    if not executavel:
        executavel = "/Applications/Wireshark.app/Contents/MacOS/tshark"
    if not Path(executavel).is_file():
        raise FileNotFoundError("TShark não encontrado; informe --tshark")
    return str(executavel)


def ler_captura(caminho, servidor, caminho_tshark=None):
    campos_tshark = ["frame.number", "frame.time_epoch", "ip.src", "ip.dst",
                     "udp.srcport", "udp.dstport", "udp.payload"]
    comando = [localizar_tshark(caminho_tshark), "-n", "-r", str(caminho),
               "-Y", f"udp && ip.addr == {servidor}", "-T", "fields"]
    for campo in campos_tshark:
        comando.extend(["-e", campo])
    resultado = subprocess.run(comando, capture_output=True, text=True, check=True)
    pacotes = []
    for linha in resultado.stdout.splitlines():
        valores = linha.split("\t")
        if len(valores) != len(campos_tshark) or not valores[-1]:
            continue
        mensagem_bruta = bytes.fromhex(valores[-1].replace(":", ""))
        tipo = mensagem_bruta.split(b"|", 1)[0].decode("ascii", errors="replace")
        sequencia = ""
        if tipo in ("REQ", "DATA", "ACK"):
            try:
                sequencia = int(mensagem_bruta.split(b"|", 2)[1].split(b"=", 1)[1])
            except (ValueError, IndexError):
                continue
        pacotes.append({
            "frame": int(valores[0]), "timestamp_epoch": float(valores[1]),
            "src": valores[2], "dst": valores[3],
            "srcport": int(valores[4]), "dstport": int(valores[5]),
            "event": tipo, "seq": sequencia,
            "client_port": int(valores[5] if valores[2] == servidor else valores[4]),
            "detail": mensagem_bruta[:160].decode("ascii", errors="replace") if tipo != "DATA" else "",
        })
    return pacotes


def escrever_csv(caminho, linhas, campos):
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(linhas)


def correlacionar_medicoes(pacotes, metricas):
    """Associa somente amostras válidas, usando seq e os dois timestamps.

    O limite de 100 ms detecta CSV de outra sessão/relógio sem alegar uma
    correspondência. Diferenças menores são registradas para análise.
    """
    requisicoes, respostas = {}, {}
    for pacote in pacotes:
        if pacote["event"] == "REQ":
            requisicoes.setdefault(pacote["seq"], []).append(pacote)
        elif pacote["event"] == "DATA":
            respostas.setdefault(pacote["seq"], []).append(pacote)
    correlacoes, ausentes = [], []
    for linha in metricas:
        if not linha.get("rtt_ms") or linha.get("rtt_sample_valid", "1") != "1":
            continue
        sequencia = int(linha["seq"])
        if not linha.get("req_timestamp_epoch") or not linha.get("data_timestamp_epoch"):
            ausentes.append(sequencia)
            continue
        tempo_req = float(linha["req_timestamp_epoch"])
        tempo_data = float(linha["data_timestamp_epoch"])
        if sequencia not in requisicoes or sequencia not in respostas:
            ausentes.append(sequencia)
            continue
        requisicao = min(requisicoes[sequencia], key=lambda pacote: abs(pacote["timestamp_epoch"] - tempo_req))
        resposta = min(respostas[sequencia], key=lambda pacote: abs(pacote["timestamp_epoch"] - tempo_data))
        if (abs(requisicao["timestamp_epoch"] - tempo_req) > .1
                or abs(resposta["timestamp_epoch"] - tempo_data) > .1
                or resposta["frame"] <= requisicao["frame"]):
            ausentes.append(sequencia)
            continue
        rtt_captura = (resposta["timestamp_epoch"] - requisicao["timestamp_epoch"]) * 1000
        rtt_cliente = float(linha["rtt_ms"])
        correlacoes.append({
            "seq": sequencia, "req_frame": requisicao["frame"], "data_frame": resposta["frame"],
            "req_timestamp_epoch": requisicao["timestamp_epoch"],
            "data_timestamp_epoch": resposta["timestamp_epoch"],
            "rtt_wireshark_ms": rtt_captura, "rtt_cliente_ms": rtt_cliente,
            "diferenca_ms": rtt_cliente - rtt_captura,
        })
    return correlacoes, ausentes


def identificar_retransmissoes(pacotes):
    primeira, ultima, linhas = {}, {}, []
    for pacote in pacotes:
        if pacote["event"] != "REQ":
            continue
        sequencia = pacote["seq"]
        if sequencia in primeira:
            linhas.append({
                "seq": sequencia, "original_frame": primeira[sequencia]["frame"],
                "previous_frame": ultima[sequencia]["frame"], "retransmitted_frame": pacote["frame"],
                "original_timestamp_epoch": primeira[sequencia]["timestamp_epoch"],
                "retransmitted_timestamp_epoch": pacote["timestamp_epoch"],
                "delta_original_ms": (pacote["timestamp_epoch"] - primeira[sequencia]["timestamp_epoch"]) * 1000,
                "delta_previous_ms": (pacote["timestamp_epoch"] - ultima[sequencia]["timestamp_epoch"]) * 1000,
            })
        primeira.setdefault(sequencia, pacote)
        ultima[sequencia] = pacote
    return linhas


def validar_sessao_unica(pacotes):
    """Recusa reúso de porta entre transferências, que confundiria os seqs."""
    requisitada = False
    for pacote in pacotes:
        if pacote["event"] == "HELLO" and requisitada:
            raise ValueError("há mais de uma sessão na mesma porta UDP; "
                             "selecione uma sessão com --frame-start e --frame-end")
        if pacote["event"] == "REQ":
            requisitada = True


def principal(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", dest="captura", required=True, type=Path)
    parser.add_argument("--metrics", dest="metricas", type=Path)
    parser.add_argument("--output-dir", dest="diretorio_saida", type=Path, default=Path("entrega-3/wireshark"))
    parser.add_argument("--server", dest="servidor", default="137.131.178.229")
    parser.add_argument("--client-port", dest="porta_cliente", type=int)
    parser.add_argument("--frame-start", dest="quadro_inicial", type=int, default=1)
    parser.add_argument("--frame-end", dest="quadro_final", type=int)
    parser.add_argument("--tshark", dest="caminho_tshark")
    argumentos = parser.parse_args(argv)
    if argumentos.quadro_inicial < 1 or (argumentos.quadro_final is not None and argumentos.quadro_final < argumentos.quadro_inicial):
        parser.error("intervalo de frames inválido")
    try:
        pacotes = ler_captura(argumentos.captura, argumentos.servidor, argumentos.caminho_tshark)
        pacotes = [pacote for pacote in pacotes if pacote["frame"] >= argumentos.quadro_inicial
                   and (argumentos.quadro_final is None or pacote["frame"] <= argumentos.quadro_final)]
        portas = sorted({pacote["client_port"] for pacote in pacotes})
        if argumentos.porta_cliente is None and len(portas) > 1:
            parser.error(f"captura contém múltiplas portas de cliente {portas}; selecione --client-port")
        if argumentos.porta_cliente is not None:
            pacotes = [pacote for pacote in pacotes if pacote["client_port"] == argumentos.porta_cliente]
        validar_sessao_unica(pacotes)
        argumentos.diretorio_saida.mkdir(parents=True, exist_ok=True)
        escrever_csv(argumentos.diretorio_saida / "pacotes.csv", pacotes,
                  ["frame", "timestamp_epoch", "src", "dst", "srcport", "dstport", "event", "seq", "detail"])
        retransmissoes = identificar_retransmissoes(pacotes)
        escrever_csv(argumentos.diretorio_saida / "retransmissoes.csv", retransmissoes,
                  ["seq", "original_frame", "previous_frame", "retransmitted_frame",
                   "original_timestamp_epoch", "retransmitted_timestamp_epoch",
                   "delta_original_ms", "delta_previous_ms"])
        correlacoes, ausentes = [], []
        if argumentos.metricas:
            with argumentos.metricas.open(newline="", encoding="utf-8") as origem:
                correlacoes, ausentes = correlacionar_medicoes(pacotes, list(csv.DictReader(origem)))
        escrever_csv(argumentos.diretorio_saida / "correlacao.csv", correlacoes,
                  ["seq", "req_frame", "data_frame", "req_timestamp_epoch", "data_timestamp_epoch",
                   "rtt_wireshark_ms", "rtt_cliente_ms", "diferenca_ms"])
        eventos = {pacote["event"] for pacote in pacotes}
        sessao = {
            "capture": str(argumentos.captura), "metrics": str(argumentos.metricas) if argumentos.metricas else None,
            "client_ports": sorted({pacote["client_port"] for pacote in pacotes}),
            "packet_count": len(pacotes), "events": sorted(eventos),
            "session_complete": {"HELLO", "OK", "REQ", "DATA", "FIN", "DONE"} <= eventos,
            "done_ok": any(pacote["event"] == "DONE" and "ok=1" in pacote["detail"] for pacote in pacotes),
            "large_requested": any(pacote["event"] == "HELLO" and "file=large" in pacote["detail"] for pacote in pacotes),
            "retransmissions": len(retransmissoes), "correlated_samples": len(correlacoes),
            "uncorrelated_valid_sequences": ausentes,
            "mean_absolute_difference_ms": (sum(abs(linha["diferenca_ms"]) for linha in correlacoes)
                                             / len(correlacoes) if correlacoes else None),
            "screenshots": "Capturar e anotar manualmente no Wireshark; tabelas não substituem screenshots.",
        }
        (argumentos.diretorio_saida / "captura_resumo.json").write_text(
            json.dumps(sessao, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(sessao, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as erro:
        parser.exit(1, f"Erro ao analisar captura: {erro}\n")


if __name__ == "__main__":
    raise SystemExit(principal())
