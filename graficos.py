"""Gráficos por segmento, eventos de timeout e comparação entre arquivos."""
import argparse
import csv
import json
from pathlib import Path


def media_movel(values, window):
    import numpy as np
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values)
    kernel = np.ones(window)
    total = np.convolve(np.where(valid, values, 0), kernel, mode='valid')
    count = np.convolve(valid.astype(float), kernel, mode='valid')
    return np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)


def salvar(fig, path):
    fig.savefig(path.with_suffix('.png'), dpi=220, facecolor='white')
    fig.savefig(path.with_suffix('.pdf'), facecolor='white')


def grafico_segmentos(directory, summary, rows, requested_window):
    import numpy as np
    import matplotlib.pyplot as plt
    seqs = np.array([int(row['seq']) for row in rows])
    rates = np.array([float(row['throughput_bps']) / 1000 for row in rows])
    rtts = np.array([float(row['rtt_ms']) if row['rtt_ms'] else np.nan for row in rows])
    loss = np.array([bool(int(row['timeout_ocorrido'])) for row in rows])
    elapsed = np.array([float(row['tempo_segmento_ms']) / 1000 for row in rows])
    window = min(requested_window, len(rows))
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 8.2), sharex=True,
                             height_ratios=[3, 3, 1.6], layout='constrained')
    fig.suptitle(f"Stop-and-Wait · {summary['grupo']} · {summary['arquivo']}", fontsize=17, fontweight='bold')
    fig.supxlabel('Número do segmento (seq)')
    fig.text(.5, .94, f"{len(rows):,} segmentos · {summary['segment_size']} bytes/segmento · "
             f"{summary['retransmissoes']} retransmissões", ha='center', fontsize=10, color='#475569')
    for ax, values, color, label in zip(axes[:2], (rates, rtts), ('#2563eb', '#0f766e'),
                                       ('Throughput (kbit/s)', 'RTT sem retransmissão (ms)')):
        ax.scatter(seqs, values, s=2, alpha=.18, color=color, edgecolors='none',
                   rasterized=True, label='Cada segmento')
        ax.plot(seqs[window - 1:], media_movel(values, window), color=color,
                linewidth=1.6, label=f'Média móvel: {window} segmentos')
        ax.set_ylabel(label)
        ax.set_ylim(bottom=0)
        ax.legend(loc='upper right', fontsize=8, ncols=2)
    theoretical = summary.get('throughput_teorico_bps')
    if theoretical is not None:
        axes[0].axhline(theoretical / 1000, color='#7c3aed', linestyle='--', linewidth=1,
                       label=f'Teórico: {theoretical / 1000:.1f} kbit/s')
    measured = summary['throughput_medido_bps'] / 1000
    axes[0].axhline(measured, color='#334155', linestyle=':', linewidth=1.2,
                   label=f'Medido agregado: {measured:.1f} kbit/s')
    axes[0].legend(loc='upper right', fontsize=8, ncols=2)
    axes[2].set_ylabel('Tempo com\ntimeout (s)')
    if loss.any():
        axes[0].scatter(seqs[loss], rates[loss], color='#dc2626', s=22, zorder=4)
        axes[2].vlines(seqs[loss], 0, elapsed[loss], color='#dc2626', linewidth=1)
        axes[2].scatter(seqs[loss], elapsed[loss], color='#dc2626', s=24, zorder=4)
        axes[2].set_ylim(0, max(elapsed[loss]) * 1.35)
        axes[2].text(.01, .88, f'{loss.sum()} segmentos com timeout · tempo total do segmento, não RTT',
                     transform=axes[2].transAxes, fontsize=8, color='#991b1b')
    else:
        axes[2].set_ylim(0, 1)
        axes[2].text(.5, .5, 'Nenhum timeout nesta transferência', ha='center', va='center',
                     transform=axes[2].transAxes, color='#475569')
    for ax in axes:
        ax.grid(axis='y', alpha=.2)
        ax.spines[['top', 'right']].set_visible(False)
        ax.tick_params(labelsize=9)
        ax.set_xlim(seqs[0] - 1, max(seqs[-1] + 1, seqs[0] + 1))
    # Reserva espaço para o subtítulo sem sobrepor o primeiro painel.
    fig.get_layout_engine().set(rect=(0, 0, 1, .92))
    salvar(fig, directory / 'graficos')
    plt.close(fig)


def grafico_comparativo(root, summaries):
    import numpy as np
    import matplotlib.pyplot as plt
    positions = np.arange(len(summaries))
    fig, ax = plt.subplots(figsize=(8.5, 4.5), layout='constrained')
    for offset, field, label, color in ((-.18, 'throughput_teorico_bps', 'Teórico', '#a78bfa'),
                                       (.18, 'throughput_medido_bps', 'Medido agregado', '#2563eb')):
        values = [s[field] / 1000 if s.get(field) is not None else float('nan') for s in summaries]
        bars = ax.bar(positions + offset, values, .34, label=label, color=color)
        ax.bar_label(bars, labels=[f'{v:.1f}' if np.isfinite(v) else 'N/D' for v in values], padding=4, fontsize=10)
    ax.set_xticks(positions, [s['arquivo'] for s in summaries])
    ax.set_ylabel('Throughput (kbit/s)')
    ax.set_title('Stop-and-Wait · throughput teórico e medido', pad=18)
    ax.set_ylim(bottom=0, top=ax.get_ylim()[1] * 1.15)
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='y', alpha=.2)
    ax.set_axisbelow(True)
    ax.legend(loc='upper center', bbox_to_anchor=(.5, 1.02), ncols=2, frameon=False)
    salvar(fig, root / 'comparativo')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resultados', type=Path, default=Path('resultados'))
    parser.add_argument('--janela', type=int, default=100, help='janela da média móvel em segmentos')
    args = parser.parse_args()
    if args.janela < 1:
        parser.error('--janela deve ser positiva')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.titleweight': 'bold'})
    summaries = []
    for name in ('small', 'medium', 'large'):
        directory = args.resultados / name
        if not (directory / 'resumo.json').exists():
            print(f'{name}: sem resultados')
            continue
        summary = json.loads((directory / 'resumo.json').read_text())
        if not summary['checksum_ok'] or not summary['done_ok']:
            print(f'{name}: integridade não confirmada')
            continue
        with (directory / 'metricas.csv').open(newline='') as source:
            rows = list(csv.DictReader(source))
        if not rows:
            print(f'{name}: CSV vazio')
            continue
        grafico_segmentos(directory, summary, rows, args.janela)
        summaries.append(summary)
    if not summaries:
        return 1
    columns = ('arquivo', 'grupo', 'file_size', 'segment_size', 'md5_recebido', 'rtt_medio_s',
               'throughput_teorico_bps', 'throughput_medido_bps', 'duracao_s', 'retransmissoes', 'segmentos_com_timeout')
    with (args.resultados / 'comparativo.csv').open('w', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(summaries)
    grafico_comparativo(args.resultados, summaries)
    print(f'Gráficos PNG/PDF e comparativo gerados em {args.resultados}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
