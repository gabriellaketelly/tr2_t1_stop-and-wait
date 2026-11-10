"""Esquema CSV e registro temporal dos eventos da transferência.

Os nomes das colunas são preservados para compatibilidade com as coletas.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path
import shutil
import time


COLUNAS_METRICAS = (
    "grupo", "servidor", "porta", "arquivo", "protocolo",
    "seq", "bytes", "rtt_ms", "tempo_segmento_ms", "throughput_bps",
    "retransmissoes", "timeout_ocorrido", "simulated_loss",
    "req_timestamp_epoch", "data_timestamp_epoch", "received_elapsed_s",
    "rtt_est_ms", "dev_rtt_ms", "timeout_ms", "timeout_usado_ms",
    "rtt_sample_valid",
    "segment", "timestamp", "size_bytes", "rtt_estimated_ms",
    "throughput_kbps", "retransmissions", "window_size", "protocol",
)


def campos_csv_enunciado(seq, recebido_epoch, bytes_payload, rtt_estimado_ms,
                         vazao_bps, retransmissoes, janela, protocolo):
    """Inclui no CSV os nomes pedidos no enunciado, preservando aliases legados."""
    instante = datetime.fromtimestamp(float(recebido_epoch), timezone.utc)
    return {
        "segment": seq,
        "timestamp": instante.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "size_bytes": bytes_payload,
        "rtt_estimated_ms": rtt_estimado_ms,
        "throughput_kbps": vazao_bps / 1000,
        "retransmissions": retransmissoes,
        "window_size": janela,
        "protocol": protocolo.lower(),
    }


def nomear_csv_metricas(caminho_csv, grupo, protocolo, inicio_epoch):
    """Cria uma cópia com o padrão metrics_<grupo>_<protocolo>_<timestamp>.csv."""
    instante = datetime.fromtimestamp(inicio_epoch).astimezone()
    sufixo = instante.strftime("%Y%m%d_%H%M%S")
    destino = Path(caminho_csv).with_name(
        f"metrics_{grupo}_{protocolo.lower()}_{sufixo}.csv"
    )
    shutil.copy2(caminho_csv, destino)
    return destino.name


class RegistroEventos:
    """Relógio monotônico para durações e epoch para correlação com pcap."""

    def __init__(self, arquivo, inicio):
        self.inicio = inicio
        self.escritor = csv.DictWriter(arquivo, fieldnames=(
            "timestamp_epoch", "elapsed_s", "event", "seq", "attempt",
            "timeout_ms", "detail",
        ))
        self.escritor.writeheader()

    def registrar(self, evento, sequencia="", tentativa="", timeout=None, detalhe="",
              agora=None, instante_unix=None):
        if agora is None:
            agora = time.perf_counter()
        if instante_unix is None:
            instante_unix = time.time()
        self.escritor.writerow({
            "timestamp_epoch": f"{instante_unix:.9f}", "elapsed_s": agora - self.inicio,
            "event": evento, "seq": sequencia, "attempt": tentativa,
            "timeout_ms": timeout * 1000 if timeout is not None else "",
            "detail": detalhe,
        })
