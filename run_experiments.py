"""Executa a matriz de testes"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shlex
import shutil
import subprocess
import sys
import socket
import threading
import time
from pathlib import Path

# None indica que o servidor já está ativo remotamente e não deve ser iniciado.
SERVER_COMMAND = None
CLIENT_COMMANDS = {
    "SAW": [sys.executable, "cliente.py"],
    "GBN": [sys.executable, "cliente_gbn.py"],
    "SR": [sys.executable, "cliente_sr.py"],
}
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080
GROUP = "grupo08"
FILE_NAME = "small"
SEGMENT_SIZE = 512
LOCAL_FILE_SIZE = 64 * 1024
TIMEOUT = 0.2
MAX_RETRIES = 10
STARTUP_DELAY_SECONDS = 0.5
USE_LOSS_PROXY = True

TESTS = [
    ("SAW", 1),
    *[("GBN", window) for window in (4, 8, 16)],
    *[("SR", window) for window in (4, 8, 16)],
]
LOSS_RATES = (0, 5, 10)


def command_with_arguments(command: list[str], protocol: str, window: int,
                           loss_percent: int, output_dir: Path) -> list[str]:
    """Monta a linha do cliente, preservando a possibilidade de usar comandos próprios."""
    result = list(command)
    result += [
        "--server", SERVER_HOST, "--port", str(SERVER_PORT),
        "--group", GROUP, "--file", FILE_NAME,
        "--segment-size", str(SEGMENT_SIZE), "--timeout", str(TIMEOUT),
        "--max-retries", str(MAX_RETRIES), "--output-dir", str(output_dir),
    ]
    if protocol != "SAW":
        result += [
            "--window-size", str(window),
            "--loss-rate", "0",
        ]
    return result


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_local_source(root: Path) -> Path:
    source = root / "_servidor-local" / "small" / "arquivo.bin"
    if not source.is_file() or source.stat().st_size != LOCAL_FILE_SIZE:
        source.parent.mkdir(parents=True, exist_ok=True)
        data = bytes(index % 251 for index in range(LOCAL_FILE_SIZE))
        source.write_bytes(data)
    return source.parent.parent


class LossProxy:
    """Encaminha UDP e descarta DATA de forma uniforme para todos os clientes."""

    def __init__(self, host: str, port: int, loss_rate: float) -> None:
        self.server = (host, port)
        self.loss_rate = loss_rate
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.address = self.sock.getsockname()
        self.client = None
        self.drops: dict[int, int] = {}
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _serve(self) -> None:
        self.sock.settimeout(0.2)
        while not self.stop_event.is_set():
            try:
                packet, peer = self.sock.recvfrom(65507)
            except socket.timeout:
                continue
            if self.client is None:
                self.client = peer
            if peer == self.client:
                self.sock.sendto(packet, self.server)
                continue
            if peer != self.server:
                continue
            if packet.startswith(b"DATA|") and random.random() < self.loss_rate:
                try:
                    fields = packet.split(b"|", 3)
                    seq = int(fields[1].split(b"=", 1)[1])
                    self.drops[seq] = self.drops.get(seq, 0) + 1
                except (IndexError, ValueError):
                    pass
                continue
            if self.client is not None:
                self.sock.sendto(packet, self.client)

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1)
        self.sock.close()


def annotate_result(work_dir: Path, protocol: str, window: int,
                    loss_percent: int, drops: dict[int, int]) -> None:
    """Adiciona metadados uniformes e registra perdas do proxy no CSV."""
    csv_path = next(work_dir.rglob("metricas.csv"), None)
    summary_path = next(work_dir.rglob("resumo.json"), None)
    if csv_path is None or summary_path is None:
        raise FileNotFoundError(f"resultado incompleto em {work_dir}")

    with csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    fields = list(rows[0]) if rows else [
        "seq", "bytes", "rtt_ms", "tempo_segmento_ms", "throughput_bps",
        "retransmissoes", "timeout_ocorrido",
    ]
    if "simulated_loss" not in fields:
        fields.append("simulated_loss")
    for row in rows:
        seq = int(row["seq"])
        row["simulated_loss"] = str(drops.get(seq, 0))
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update({
        "protocolo": protocol,
        "janela": window,
        "loss_rate": loss_percent / 100,
        "simulated_loss_total": sum(drops.values()),
    })
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def stop_process(process: subprocess.Popen) -> None:
    """Encerra o servidor, incluindo fallback para processos que não terminam."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def find_csv(directory: Path) -> Path | None:
    candidates = sorted(directory.rglob("metricas.csv"))
    return candidates[0] if candidates else None


def run_one(protocol: str, window: int, loss_percent: int, root: Path) -> None:
    name = f"resultado_{protocol}_w{window}_loss{loss_percent}.csv"
    work_dir = root / f"{protocol.lower()}-w{window}-loss{loss_percent:02d}"
    work_dir.mkdir(parents=True, exist_ok=True)
    server = None
    proxy = None
    server_host = SERVER_HOST
    server_port = SERVER_PORT
    if SERVER_COMMAND is None:
        server_port = free_port()
        local_files_dir = ensure_local_source(root)
        server_command = [
            sys.executable, "test_localserver.py",
            "--host", server_host, "--port", str(server_port),
            "--files-dir", str(local_files_dir),
        ]
    else:
        server_command = SERVER_COMMAND
    if server_command is not None:
        server = subprocess.Popen(
            server_command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    try:
        if server is not None:
            time.sleep(STARTUP_DELAY_SECONDS)
        if server is not None and server.poll() is not None:
            raise RuntimeError("o servidor terminou antes do cliente iniciar")
        if USE_LOSS_PROXY:
            proxy = LossProxy(server_host, server_port, loss_percent / 100)
            proxy.start()
            client_server, client_port = proxy.address
        else:
            client_server, client_port = server_host, server_port
        client = command_with_arguments(
            CLIENT_COMMANDS[protocol], protocol, window, loss_percent, work_dir
        )
        client[client.index("--server") + 1] = client_server
        client[client.index("--port") + 1] = str(client_port)
        print("$", " ".join(shlex.quote(part) for part in client))
        completed = subprocess.run(client, check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"cliente terminou com código {completed.returncode}")
    finally:
        if proxy is not None:
            proxy.stop()
        if server is not None:
            stop_process(server)

    source = find_csv(work_dir)
    if source is None:
        raise FileNotFoundError(f"nenhum metricas.csv encontrado em {work_dir}")
    annotate_result(
        work_dir, protocol, window, loss_percent,
        proxy.drops if proxy is not None else {},
    )
    organized_csv = work_dir / name
    shutil.copy2(source, organized_csv)
    print(f"CSV salvo em {organized_csv}")


def main() -> int:
    global STARTUP_DELAY_SECONDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("entrega-2-v2"))
    parser.add_argument("--delay", type=float, default=STARTUP_DELAY_SECONDS)
    args = parser.parse_args()
    if any(not command for command in CLIENT_COMMANDS.values()):
        parser.error("configure CLIENT_COMMANDS no início do arquivo")
    if args.delay < 0:
        parser.error("--delay deve ser não negativo")
    STARTUP_DELAY_SECONDS = args.delay
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for protocol, window in TESTS:
        for loss_percent in LOSS_RATES:
            print(f"\n=== {protocol}, janela {window}, perda {loss_percent}% ===")
            run_one(protocol, window, loss_percent, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
