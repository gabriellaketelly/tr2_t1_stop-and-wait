import argparse
import csv
import hashlib
import json
import math 
import random
import socket
import time
from pathlib import Path

from cliente import (
    ProtocolError,
    identifier,
    handshake,
    parse_data,
    ack_nao_suportado,
    finalizar,
)

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="137.131.178.229")
    parser.add_argument("--port", type=int, default = 8080)
    parser.add_argument("--group", required=True, type=identifier)
    parser.add_argument("--file", choices=("small", "medium", "large"), default="small")
    parser.add_argument("--segment-size", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--max-retries", type=int, default=10)
    parser.add_argument("--window-size", type=int, choices=(4,8,16), default =4)
    parser.add_argument("--loss-rate", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path, default=Path("resultados"))

    args = parser.parse_args(argv)

    if not 1 <= args.segment_size <= 512:
        parser.error("--segment-size deve estar entre 1 e 512")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout deve ser positivo")
    if args.max_retries < 0:
        parser.error("--max-retries não pode ser negativo")
    if not 1 <= args.port <= 65535:
        parser.error("porta inválida")
    if not 0 <= args.loss_rate <= 1:
        parser.error("--loss-rate deve estar entre 0 e 1")

    return args

def tamanho_segmento(seq, info):
    restante = info["file_size"] - seq * info["segment_size"]
    return min(info["segment_size"], restante)

def baixar_gbn(sock, args, info):
    total = info["total_segments"]
    janela = args.window_size

    directory = args.output_dir / "gbn" / args.file
    directory.mkdir(parents=True, exist_ok=True)

    for name in ("arquivo.bin", "arquivo.part", "metricas.csv", "resumo.json"):
        (directory/name).unlink(missing_ok=True)

    # Estado da janela
    base = 0
    next_seq = 0

    # Número de envios de cada segmento, incluindo o envio inicial

    tentativas = {seq: 0 for seq in range(total)}
    primeiro_envio = {}
    perdas_simuladas = {seq: 0 for seq in range(total)}

    digest = hashlib.md5()
    avisos = set()
    rtts = []
    retransmissoes_total = 0
    timeouts_total = 0
    bytes_recebidos = 0

    colunas = (
        "seq",
        "bytes",
        "rtt_ms",
        "tempo_segmento_ms",
        "throughput_bps",
        "retransmissoes",
        "timeout_ocorrido",
        "simulated_loss",
    )

    def enviar_req(seq):
        agora = time.perf_counter()

        if tentativas[seq] == 0:
            primeiro_envio[seq] = agora

        tentativas[seq] += 1
        sock.send(f"REQ|seq={seq}".encode("ascii"))

    inicio = time.perf_counter()
    base_timer = inicio

    partial = directory / "arquivo.part"

    with partial.open("wb") as output, (
        directory / "metricas.csv"
    ).open("w", newline="", encoding = "utf-8") as metrics:

        writer = csv.DictWriter(metrics, fieldnames = colunas)
        writer.writeheader()

        # Envio inicial: preenche a janela

        while next_seq < total and next_seq < base + janela:
            enviar_req(next_seq)
            next_seq += 1

        while base < total:
            restante = args.timeout - (time.perf_counter() - base_timer)
            sock.settimeout(max(restante, 0.001))

            try:
                packet = sock.recv(65507)
            except socket.timeout:
                pendentes = range(base, next_seq)

                for seq in pendentes:
                    if tentativas[seq] - 1 >= args.max_retries:
                        raise TimeoutError(
                            f"Segmento {seq}: limite de retransmissões atingido"
                        )

                print(
                    f"Timeout em {base}; retransmitindo "
                    f"os segmentos {base} até {next_seq - 1}",
                    flush=True,
                )

                for seq in pendentes:
                    enviar_req(seq)

                retransmissoes_total += len(pendentes)
                timeouts_total += 1
                base_timer = time.perf_counter()
                continue


            if packet.startswith(b"ERROR"):
                if ack_nao_suportado(packet, avisos):
                    continue
                raise ProtocolError(
                    packet.decode("ascii", errors="replace")
                )
            
            try: 
                seq, tamanho_total, payload = parse_data(packet)

            except ProtocolError:
                continue

            if not 0 <= seq < total:
                continue

            tamanho_esperado = tamanho_segmento(seq, info)

            if len(payload) != tamanho_esperado:
                continue

            if tamanho_total not in (tamanho_esperado, info["file_size"]):
                continue

            if seq != base:
                continue
             # Simula perda de DATA no cliente, antes de processá-lo.
            if random.random() < args.loss_rate:
                perdas_simuladas[seq] += 1
                continue

            # GBN aceita somente o segmento esperado.
        

            agora = time.perf_counter()
            tempo_segmento = agora - primeiro_envio[seq]
            numero_retransmissoes = tentativas[seq] - 1

            output.write(payload)
            digest.update(payload)
            bytes_recebidos += len(payload)

            # Mantém o ACK previsto no enunciado.
            # O servidor real pode responder com ERROR para esse ACK.
            sock.send(f"ACK|seq={seq}".encode("ascii"))

            row = {
                "seq": seq,
                "bytes": len(payload),
                "rtt_ms": (
                    tempo_segmento * 1000
                    if tentativas[seq] == 1
                    else ""
                ),
                "tempo_segmento_ms": tempo_segmento * 1000,
                "throughput_bps": (
                    len(payload) * 8 / tempo_segmento
                    if tempo_segmento > 0
                    else 0
                ),
                "retransmissoes": numero_retransmissoes,
                "timeout_ocorrido": int(numero_retransmissoes > 0),
                "simulated_loss": perdas_simuladas[seq],
            }
            writer.writerow(row)

            if row["rtt_ms"] != "":
                rtts.append(row["rtt_ms"] / 1000)

            base += 1

            # A janela avança e novos REQs podem ser enviados.
            while next_seq < total and next_seq < base + janela:
                enviar_req(next_seq)
                next_seq += 1

            # Reinicia o temporizador do segmento mais antigo pendente.
            base_timer = time.perf_counter()

            if base % 100 == 0 or base == total:
                print(f"GBN: {base}/{total} segmentos", flush=True)

    duracao = time.perf_counter() - inicio
    checksum = digest.hexdigest()
    checksum_ok = (
        bytes_recebidos == info["file_size"]
        and checksum == info["checksum"]
    )

    done = finalizar(sock, checksum, args, avisos)

    resumo = {
        "protocolo": "GBN",
        "grupo": args.group,
        "arquivo": args.file,
        "servidor": args.server,
        "porta": args.port,
        "janela": janela,
        "loss_rate": args.loss_rate,
        "file_size": bytes_recebidos,
        "segment_size": info["segment_size"],
        "total_segments": total,
        "md5_esperado": info["checksum"],
        "md5_recebido": checksum,
        "checksum_ok": checksum_ok,
        "done_ok": done,
        "duracao_s": duracao,
        "rtt_medio_s": sum(rtts) / len(rtts) if rtts else None,
        "throughput_medido_bps": (
            bytes_recebidos * 8 / duracao if duracao > 0 else 0
        ),
        "retransmissoes": retransmissoes_total,
        "timeouts": timeouts_total,
        "timeout_s": args.timeout,
        "avisos_servidor": sorted(avisos),
    }

    (directory / "resumo.json").write_text(
        json.dumps(resumo, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if not checksum_ok or not done:
        raise ProtocolError(
            "Integridade não confirmada; consulte resultados/gbn."
        )

    partial.replace(directory / "arquivo.bin")
    return resumo


def main(argv=None):
    args = parse_args(argv)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((args.server, args.port))
            info = handshake(sock, args)

            print(
                f"Arquivo: {info['file_size']} bytes | "
                f"Segmentos: {info['total_segments']} | "
                f"Janela: {args.window_size}"
            )

            resumo = baixar_gbn(sock, args, info)

            print(f"MD5: {resumo['md5_recebido']}")
            print(
                f"Throughput: "
                f"{resumo['throughput_medido_bps']:.2f} bit/s"
            )

        return 0

    except (OSError, ProtocolError, TimeoutError, UnicodeError) as exc:
        print(f"Erro: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


            