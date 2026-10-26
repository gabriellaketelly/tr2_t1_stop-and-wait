"""Gera a tabela, a análise e os gráficos da Entrega 2."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


NAME_RE = re.compile(r"^(saw|gbn|sr)-w(1|4|8|16)-loss(00|05|10)$", re.I)
EXPECTED = [
    (protocol, window, loss)
    for protocol, windows in (("SAW", (1,)), ("GBN", (4, 8, 16)),
                              ("SR", (4, 8, 16)))
    for window in windows
    for loss in (0, 5, 10)
]


def find_result(directory: Path) -> tuple[Path, Path] | None:
    csv_path = next(directory.rglob("metricas.csv"), None)
    summary_path = next(directory.rglob("resumo.json"), None)
    return (csv_path, summary_path) if csv_path and summary_path else None


def collect(root: Path) -> dict[tuple[str, int, int], tuple[Path, dict]]:
    records = {}
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        match = NAME_RE.fullmatch(directory.name)
        result = find_result(directory)
        if not match or result is None:
            continue
        protocol, window, loss = match.group(1).upper(), int(match.group(2)), int(match.group(3))
        summary = json.loads(result[1].read_text(encoding="utf-8"))
        records[(protocol, window, loss)] = (result[0], summary)
    return records


def rows_for_table(records):
    rows = []
    for protocol, window, loss in EXPECTED:
        item = records.get((protocol, window, loss))
        summary = item[1] if item else {}
        rows.append({
            "protocolo": protocol,
            "janela": window,
            "perda_percentual": loss,
            "throughput_medio_bps": summary.get("throughput_medido_bps"),
            "retransmissoes": summary.get("retransmissoes"),
            "tempo_total_s": summary.get("duracao_s"),
            "checksum_ok": summary.get("checksum_ok"),
            "done_ok": summary.get("done_ok"),
            "simulated_loss_total": summary.get("simulated_loss_total"),
        })
    return rows


def write_table(root: Path, rows) -> None:
    path = root / "comparativo.csv"
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plot_segments(root: Path, records) -> None:
    output = root / "graficos"
    output.mkdir(exist_ok=True)
    selected = {}
    for protocol in ("GBN", "SR"):
        item = records.get((protocol, 16, 10))
        if item:
            with item[0].open(newline="", encoding="utf-8") as source:
                selected[protocol] = list(csv.DictReader(source))
    if len(selected) != 2:
        return

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                             constrained_layout=True)
    for protocol, data in selected.items():
        seq = [int(row["seq"]) for row in data]
        throughput = [float(row["throughput_bps"]) for row in data]
        retrans = [int(row["retransmissoes"]) for row in data]
        axes[0].plot(seq, throughput, linewidth=.7, label=protocol)
        cumulative = []
        total = 0
        for value in retrans:
            total += value
            cumulative.append(total)
        axes[1].plot(seq, cumulative, linewidth=1, label=protocol)
    axes[0].set_ylabel("Throughput (bit/s)")
    axes[1].set_ylabel("Retransmissões acumuladas")
    axes[1].set_xlabel("Segmento")
    for axis in axes:
        axis.grid(alpha=.25)
        axis.legend()
    fig.suptitle("GBN × SR — janela 16, perda 10%")
    fig.savefig(output / "grafico_throughput_gbn_sr_w16_loss10.png", dpi=180)
    plt.close(fig)


def print_analysis(records) -> None:
    print("\nImpacto da janela sem perda:")
    for protocol in ("GBN", "SR"):
        values = []
        for window in (4, 8, 16):
            item = records.get((protocol, window, 0))
            value = item[1].get("throughput_medido_bps") if item else None
            values.append(f"w{window}={value if value is not None else 'N/D'}")
        print(f"{protocol}: " + ", ".join(values))

    print("\nRetransmissões por perda simulada, janela 16, perda 10%:")
    for protocol in ("GBN", "SR"):
        item = records.get((protocol, 16, 10))
        if not item:
            print(f"{protocol}: N/D")
            continue
        summary = item[1]
        losses = summary.get("simulated_loss_total", 0)
        retrans = summary.get("retransmissoes", 0)
        ratio = retrans / losses if losses else float("nan")
        print(f"{protocol}: {retrans} / {losses} = {ratio:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("entrega-2-v2"))
    args = parser.parse_args()
    records = collect(args.input_dir)
    rows = rows_for_table(records)
    write_table(args.input_dir, rows)
    plot_segments(args.input_dir, records)
    print_analysis(records)
    missing = [key for key in EXPECTED if key not in records]
    if missing:
        print(f"\nResultados ausentes: {len(missing)} de {len(EXPECTED)}")
        return 1
    if not all(row["checksum_ok"] and row["done_ok"] for row in rows):
        print("\nFalha de integridade em pelo menos um resultado.")
        return 1
    print(f"\nTabela completa salva em {args.input_dir / 'comparativo.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
