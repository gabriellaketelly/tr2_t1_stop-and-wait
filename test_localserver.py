"""Servidor UDP local mínimo para testar os clientes da Entrega 2.

Uso:
    python test_localserver.py
    python test_localserver.py --files-dir resultados --host 127.0.0.1 --port 8080

Os arquivos esperados são small/arquivo.bin, medium/arquivo.bin e
large/arquivo.bin dentro de --files-dir. Também é possível informar um
arquivo diretamente com --file.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import socket
from pathlib import Path


def locate_file(root: Path, name: str) -> Path:
    direct = root / name / "arquivo.bin"
    if direct.is_file():
        return direct
    nested = sorted(
        path for path in root.rglob("arquivo.bin")
        if name in path.parts
    )
    if nested:
        return nested[0]
    matches = sorted(root.rglob(f"{name}.bin"))
    if matches:
        return matches[0]
    raise FileNotFoundError(
        f"não encontrei o arquivo '{name}/arquivo.bin' em {root}"
    )


def parse_fields(packet: bytes, kind: str) -> dict[str, str]:
    parts = packet.decode("ascii").split("|")
    if parts[0] != kind:
        raise ValueError(f"mensagem esperada: {kind}")
    fields = {}
    for part in parts[1:]:
        key, value = part.split("=", 1)
        fields[key] = value
    return fields


def load_files(root: Path, requested: Path | None) -> dict[str, bytes]:
    if requested is not None:
        return {requested.stem: requested.read_bytes()}
    files = {}
    for name in ("small", "medium", "large"):
        try:
            files[name] = locate_file(root, name).read_bytes()
        except FileNotFoundError:
            continue
    if not files:
        raise FileNotFoundError(f"nenhum arquivo arquivo.bin encontrado em {root}")
    return files


def serve(host: str, port: int, files: dict[str, bytes], segment_size: int) -> None:
    checksums = {name: hashlib.md5(data).hexdigest() for name, data in files.items()}
    sessions: dict[tuple[str, int], dict[str, object]] = {}
    print(f"Servidor UDP local em {host}:{port}", flush=True)
    print(f"Arquivos disponíveis: {', '.join(sorted(files))}", flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((host, port))
        while True:
            packet, peer = sock.recvfrom(65507)
            try:
                if packet.startswith(b"HELLO|"):
                    fields = parse_fields(packet, "HELLO")
                    name = fields.get("file", "")
                    if name not in files:
                        sock.sendto(b"ERROR|msg=arquivo_inexistente", peer)
                        continue
                    data = files[name]
                    size = min(int(fields.get("segment_size", segment_size)), 512)
                    size = max(size, 1)
                    sessions[peer] = {
                        "file": name,
                        "segment_size": size,
                        "checksum": checksums[name],
                    }
                    total = math.ceil(len(data) / size)
                    response = (
                        f"OK|file_size={len(data)}|checksum={checksums[name]}"
                        f"|seed=local|total_segments={total}|segment_size={size}"
                    )
                    sock.sendto(response.encode("ascii"), peer)
                elif packet.startswith(b"REQ|"):
                    session = sessions.get(peer)
                    if session is None:
                        sock.sendto(b"ERROR|msg=sessao_invalida", peer)
                        continue
                    fields = parse_fields(packet, "REQ")
                    sequence = int(fields["seq"])
                    data = files[str(session["file"])]
                    size = int(session["segment_size"])
                    start = sequence * size
                    payload = data[start:start + size]
                    if not payload:
                        sock.sendto(b"ERROR|msg=sequencia_invalida", peer)
                        continue
                    sock.sendto(
                        f"DATA|seq={sequence}|total={len(data)}|".encode("ascii") + payload,
                        peer,
                    )
                elif packet.startswith(b"FIN|"):
                    session = sessions.get(peer)
                    if session is None:
                        sock.sendto(b"ERROR|msg=sessao_invalida", peer)
                        continue
                    fields = parse_fields(packet, "FIN")
                    ok = fields.get("checksum") == session["checksum"]
                    sock.sendto(f"DONE|ok={int(ok)}".encode("ascii"), peer)
                    sessions.pop(peer, None)
            except (UnicodeError, ValueError, KeyError) as exc:
                sock.sendto(f"ERROR|msg=mensagem_invalida:{exc}".encode("ascii"), peer)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--files-dir", type=Path, default=Path("resultados"))
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--segment-size", type=int, default=512)
    args = parser.parse_args()
    if not 1 <= args.segment_size <= 512:
        parser.error("--segment-size deve estar entre 1 e 512")
    try:
        files = load_files(args.files_dir, args.file)
        serve(args.host, args.port, files, args.segment_size)
    except (FileNotFoundError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
