import csv
import hashlib
import json
import random
import socket
import time

from cliente import (
    ProtocolError,
    identifier,
    handshake,
    parse_data,
    ack_nao_suportado,
    finalizar,
)

from cliente_gbn import parse_args, tamanho_segmento

def baixar_sr(sock, args, info):
    total = info["total_segments"]
    janela = args.window_size

    directory = args.output_dir / "sr" / args.file
    directory.mkdir(parents=True, exist_ok=True)

    for name in ("arquivo.bin", "arquivo.part", "metricas.csv", "resumo.json"):
        (directory / name).unlink(missing_ok=True)

    # base eh o primeiro segmento que ainda falta gravar no arquivo.
    # next_seq eh o proximo segmento que ainda n foi solicitado

    base = 0
    next_seq = 0

    tentativas = {seq: 0 for seq in range(total)}
    primeiro_envio = {}
    ultimo_envio = {}
    perdas_simuladas = {seq: 0 for seq in range(total)}

    #segmentos recebidos mas n gravados
    buffer = {}

    pendentes = set()
    segmentos_com_timeout = set()

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
        nonlocal retransmissoes_total

        agora = time.perf_counter()

        if tentativas[seq] == 0:
            primeiro_envio[seq] = agora
        else: 
            retransmissoes_total += 1

        tentativas[seq] += 1
        ultimo_envio[seq] = agora
        pendentes.add(seq)

        sock.send(f"REQ|seq={seq}".encode("ascii"))

    def preencher_janela():
        nonlocal next_seq

        while next_seq < total and next_seq < base + janela:
            enviar_req(next_seq)
            next_seq += 1

    inicio = time.perf_counter()
    partial = directory / "arquivo.part"

    with partial.open("wb") as output, (
        (directory / "metricas.csv").open(
            "w", newline = "", encoding="utf-8"
        )
    ) as metrics:

        writer = csv.DictWriter(metrics, fieldnames=colunas)
        writer.writeheader()

        preencher_janela()

        while base < total:
            #calcula quanto falta para o timeout mais proximo
            agora = time.perf_counter()

            if pendentes:
                tempo_restante = min (
                    args.timeout - (agora - ultimo_envio[seq])
                    for seq in pendentes
                )

            else:
                #o segmento faltante continua pendente.
                preencher_janela()
                continue

            sock.settimeout(max(tempo_restante, 0.001))

            try:
                packet = sock.recv(65507)
            except socket.timeout:
                agora = time.perf_counter()

                expirados = [
                    seq 
                    for seq in pendentes 
                    if agora - ultimo_envio[seq] >= args.timeout
                ]

                for seq in expirados:
                    if tentativas[seq] - 1 >= args.max_retries:
                        raise TimeoutError(
                            f"Segmento {seq}: limite de retransmissões atingido"
                        )

                for seq in expirados:
                    print(
                        f"Timeout no segmento {seq}; "
                        f"retransmitindo somente esse segmento.",
                        flush=True,
                    )
                    segmentos_com_timeout.add(seq)
                    enviar_req(seq)
                    timeouts_total += 1

                continue

            if packet.startswith(b"ERROR"):
                if ack_nao_suportado(packet, avisos):
                    continue
                raise ProtocolError(
                    packet.decode("ascii", errors = "replace")
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

            if tamanho_total not in(tamanho_esperado, info["file_size"],
            ):
                continue

            if seq < base or seq in buffer:
                sock.send(f"ACK|seq={seq}".encode("ascii"))
                continue

            if not base <= seq < min(total, base + janela):
                continue

            if random.random() < args.loss_rate:
                perdas_simuladas[seq] += 1
                continue

            recebido_em = time.perf_counter()

            buffer[seq] = {
                "payload": payload,
                "recebido_em": recebido_em,
            }
            pendentes.discard(seq)


            sock.send(f"ACK|seq={seq}".encode("ascii"))

            while base in buffer:
                item = buffer.pop(base)
                dados = item["payload"]

                tempo_segmento = (
                    item["recebido_em"] - primeiro_envio[base]
                )
                numero_retransmissoes = tentativas[base] - 1

                output.write(dados)
                digest.update(dados)
                bytes_recebidos += len(dados)

                row = {
                    "seq": base,
                    "bytes": len(dados),
                    "rtt_ms": (
                        tempo_segmento * 1000
                        if tentativas[base] == 1
                        else ""
                    ),
                    "tempo_segmento_ms": tempo_segmento * 1000,
                    "throughput_bps": (
                        len(dados) * 8 / tempo_segmento
                        if tempo_segmento > 0
                        else 0
                    ),
                    "retransmissoes": numero_retransmissoes,
                    "timeout_ocorrido": int(base in segmentos_com_timeout),
                    "simulated_loss": perdas_simuladas[base],
                }

                writer.writerow(row)

                if row["rtt_ms"] != "":
                    rtts.append(row["rtt_ms"] / 1000)

                base += 1

            preencher_janela()

            if base % 100 == 0 or base == total:
                print(
                    f"SR: {base}/{total} segmentos gravados",
                    flush=True,
                )

    duracao = time.perf_counter() - inicio
    checksum = digest.hexdigest()

    checksum_ok = (
        bytes_recebidos == info["file_size"]
        and checksum == info["checksum"]
    )

    print("Transferência concluída; iniciando finalização...", flush=True)
    done = finalizar(sock, checksum, args, avisos)

    resumo = {
        "protocolo": "SR",
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
            "Integridade não confirmada; consulte resultados/sr."
        )

    partial.replace(directory / "arquivo.bin")
    return resumo


def main(argv=None):
    args = parse_args(argv)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((args.server, args.port))
            print("Iniciando handshake...", flush=True)
            info = handshake(sock, args)
            print("Handshake concluído!", flush=True)
            print(
                f"Arquivo: {info['file_size']} bytes | "
                f"Segmentos: {info['total_segments']} | "
                f"Janela: {args.window_size}"
            )

            resumo = baixar_sr(sock, args, info)

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


                

    

                 