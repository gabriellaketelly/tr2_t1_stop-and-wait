"""Cliente Stop-and-Wait do protocolo RDT-UnB v1.0 (somente UDP)."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import socket
import time


class ProtocolError(Exception):
    pass


def identifier(value):
    if not value or not value.isascii() or any(c in value for c in "|=\r\n"):
        raise argparse.ArgumentTypeError("identificador vazio ou com delimitadores inválidos")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="137.131.178.229")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--group", required=True, type=identifier)
    parser.add_argument("--file", choices=("small", "medium", "large"), default="small")
    parser.add_argument("--segment-size", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--max-retries", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("resultados"))
    args = parser.parse_args(argv)
    if not 1 <= args.segment_size <= 512:
        parser.error("--segment-size deve estar entre 1 e 512")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.max_retries < 0:
        parser.error("timeout deve ser positivo e max-retries não negativo")
    if not 1 <= args.port <= 65535:
        parser.error("porta inválida")
    return args


def parse_fields(packet, kind):
    try:
        parts = packet.decode("ascii").split("|")
        if parts[0] != kind:
            raise ValueError("tipo inesperado")
        fields = {}
        for part in parts[1:]:
            key, value = part.split("=", 1)
            if key in fields:
                raise ValueError("campo duplicado")
            fields[key] = value
        return fields
    except (UnicodeError, ValueError) as exc:
        raise ProtocolError(f"{kind} inválido: {exc}") from exc


def ack_nao_suportado(packet, avisos):
    """Reconhece apenas a incompatibilidade de ACK observada no servidor."""
    if packet.rstrip() != b"ERROR|msg=tipo_desconhecido_ACK":
        return False
    if avisos is not None and "ack_nao_suportado" not in avisos:
        avisos.add("ack_nao_suportado")
        print("Aviso: servidor rejeita ACK; mantendo envio conforme o enunciado.", flush=True)
    return True


def exchange(sock, message, expected, timeout, max_retries, avisos=None):
    for attempt in range(max_retries + 1):
        sock.send(message)
        deadline = time.perf_counter() + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                packet = sock.recv(65507)
            except socket.timeout:
                break
            if packet.startswith(expected + b"|"):
                return parse_fields(packet, expected.decode("ascii"))
            if packet.startswith(b"ERROR"):
                if ack_nao_suportado(packet, avisos):
                    continue
                raise ProtocolError(packet.decode("ascii", errors="replace"))
    raise TimeoutError(f"Sem {expected.decode()} após {max_retries + 1} tentativas")


def handshake(sock, args):
    hello = (f"HELLO|grupo={args.group}|segment_size={args.segment_size}"
             f"|file={args.file}").encode("ascii")
    fields = exchange(sock, hello, b"OK", args.timeout, args.max_retries)
    try:
        info = {key: int(fields[key]) for key in
                ("file_size", "total_segments", "segment_size")}
        checksum = fields["checksum"].lower()
        if len(checksum) != 32 or any(c not in "0123456789abcdef" for c in checksum):
            raise ValueError("MD5 inválido")
        if info["file_size"] <= 0 or not 1 <= info["segment_size"] <= 512:
            raise ValueError("tamanho inválido")
        if info["total_segments"] != math.ceil(info["file_size"] / info["segment_size"]):
            raise ValueError("quantidade de segmentos inconsistente")
        info.update(checksum=checksum, seed=fields.get("seed"))
        return info
    except (KeyError, ValueError) as exc:
        raise ProtocolError(f"Parâmetros do OK inválidos: {exc}") from exc


def parse_data(packet):
    try:
        kind, sequence, total, payload = packet.split(b"|", 3)
        if kind != b"DATA" or not sequence.startswith(b"seq=") or not total.startswith(b"total="):
            raise ValueError("cabeçalho inesperado")
        seq = int(sequence[4:])
        size = int(total[6:])
        if seq < 0 or size < 0:
            raise ValueError("valor negativo")
        return seq, size, payload
    except ValueError as exc:
        raise ProtocolError(f"DATA inválido: {exc}") from exc


def receber_segmento(sock, seq, expected_size, file_size, timeout, max_retries, avisos=None):
    started = time.perf_counter()
    for attempt in range(max_retries + 1):
        sock.send(f"REQ|seq={seq}".encode("ascii"))
        deadline = time.perf_counter() + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                packet = sock.recv(65507)
            except socket.timeout:
                break
            if packet.startswith(b"ERROR"):
                if ack_nao_suportado(packet, avisos):
                    continue
                raise ProtocolError(packet.decode("ascii", errors="replace"))
            try:
                received_seq, total, payload = parse_data(packet)
            except ProtocolError:
                continue
            # A especificação não esclarece se total é o tamanho do arquivo
            # ou do payload. Aceitamos ambos, validando o payload pelo OK.
            if received_seq != seq or len(payload) != expected_size:
                continue
            if total not in (expected_size, file_size):
                continue
            elapsed = time.perf_counter() - started
            return payload, {
                "seq": seq, "bytes": len(payload),
                "rtt_ms": elapsed * 1000 if attempt == 0 else "",
                "tempo_segmento_ms": elapsed * 1000,
                "throughput_bps": len(payload) * 8 / elapsed,
                "retransmissoes": attempt, "timeout_ocorrido": int(attempt > 0),
            }
    raise TimeoutError(f"Segmento {seq}: limite de retransmissões atingido")


def finalizar(sock, checksum, args, avisos=None):
    fields = exchange(sock, f"FIN|checksum={checksum}".encode("ascii"),
                      b"DONE", args.timeout, args.max_retries, avisos)
    if fields.get("ok") not in ("0", "1"):
        raise ProtocolError("DONE sem campo ok válido")
    return fields["ok"] == "1"


def baixar_arquivo(sock, args, info):
    directory = args.output_dir / args.file
    directory.mkdir(parents=True, exist_ok=True)
    # Evita apresentar um resumo de execução anterior como resultado atual.
    for name in ("resumo.json", "graficos.png", "graficos.pdf", "arquivo.bin"):
        (directory / name).unlink(missing_ok=True)
    digest = hashlib.md5()
    rtts = []
    retries = timeouts = received = 0
    avisos = set()
    started = time.perf_counter()
    columns = ("seq", "bytes", "rtt_ms", "tempo_segmento_ms", "throughput_bps",
               "retransmissoes", "timeout_ocorrido")
    partial = directory / "arquivo.part"
    with partial.open("wb") as output, (directory / "metricas.csv").open("w", newline="") as metrics:
        writer = csv.DictWriter(metrics, fieldnames=columns)
        writer.writeheader()
        for seq in range(info["total_segments"]):
            expected = min(info["segment_size"], info["file_size"] - received)
            payload, row = receber_segmento(sock, seq, expected, info["file_size"],
                                            args.timeout, args.max_retries, avisos)
            output.write(payload)
            digest.update(payload)
            received += len(payload)
            sock.send(f"ACK|seq={seq}".encode("ascii"))
            writer.writerow(row)
            if row["rtt_ms"] != "":
                rtts.append(row["rtt_ms"] / 1000)
            retries += row["retransmissoes"]
            timeouts += row["timeout_ocorrido"]
            if (seq + 1) % 100 == 0 or seq + 1 == info["total_segments"]:
                print(f"{args.file}: {seq + 1}/{info['total_segments']} segmentos", flush=True)
    duration = time.perf_counter() - started
    checksum = digest.hexdigest()
    local_ok = received == info["file_size"] and checksum == info["checksum"]
    done = finalizar(sock, checksum, args, avisos)
    mean_rtt = sum(rtts) / len(rtts) if rtts else None
    summary = {
        "grupo": args.group, "arquivo": args.file, "servidor": args.server,
        "porta": args.port, "file_size": received, "segment_size": info["segment_size"],
        "total_segments": info["total_segments"], "seed": info["seed"],
        "md5_esperado": info["checksum"], "md5_recebido": checksum,
        "checksum_ok": local_ok, "done_ok": done, "duracao_s": duration,
        "rtt_medio_s": mean_rtt, "amostras_rtt": len(rtts),
        "throughput_medido_bps": received * 8 / duration,
        "throughput_teorico_bps": info["segment_size"] * 8 / mean_rtt if mean_rtt else None,
        "retransmissoes": retries, "segmentos_com_timeout": timeouts,
        "timeout_s": args.timeout,
        "avisos_servidor": sorted(avisos),
    }
    (directory / "resumo.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    if not local_ok or not done:
        raise ProtocolError("Integridade não confirmada; consulte resumo.json")
    partial.replace(directory / "arquivo.bin")
    return summary


def main(argv=None):
    args = parse_args(argv)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # connect em UDP fixa o peer; não cria uma conexão TCP.
            sock.connect((args.server, args.port))
            info = handshake(sock, args)
            print(f"Sessão: {info['file_size']} bytes, segmento {info['segment_size']} bytes")
            summary = baixar_arquivo(sock, args, info)
            print(f"MD5: {summary['md5_recebido']} — DONE|ok=1")
            print(f"Throughput: {summary['throughput_medido_bps']:.2f} bit/s")
        return 0
    except (OSError, ProtocolError, TimeoutError, UnicodeError) as exc:
        print(f"Erro: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
