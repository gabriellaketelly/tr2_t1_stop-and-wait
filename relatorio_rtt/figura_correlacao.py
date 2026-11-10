"""Monta a evidência visual da correlação Wireshark/CSV sem alterar a captura."""

import csv
from pathlib import Path
import subprocess


def _tempos_relativos(pcap, quadros):
    comando = ["/Applications/Wireshark.app/Contents/MacOS/tshark", "-r", str(pcap),
               "-Y", " or ".join(f"frame.number == {quadro}" for quadro in quadros),
               "-T", "fields", "-e", "frame.number", "-e", "frame.time_relative"]
    try:
        saida = subprocess.run(comando, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.SubprocessError) as erro:
        raise RuntimeError("Não foi possível obter timestamps relativos do PCAP com tshark.") from erro
    tempos = {}
    for linha in saida.splitlines():
        quadro, tempo = linha.split("\t", 1)
        tempos[int(quadro)] = float(tempo)
    if any(quadro not in tempos for quadro in quadros):
        raise ValueError("Quadro REQ/DATA não encontrado no PCAP.")
    return tempos


def gerar_figura_correlacao(captura, csv_correlacao, pcap, destino):
    """Exibe a captura original ao lado da linha CSV correspondente à sequência 0."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec
    from matplotlib.ticker import NullLocator
    import matplotlib.image as mpimg

    with Path(csv_correlacao).open(newline="", encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    linha = next((item for item in linhas
                  if item.get("seq") == "0" and item.get("req_frame") == "5"
                  and item.get("data_frame") == "21"), None)
    if linha is None:
        raise ValueError("A correlação seq=0, REQ 5, DATA 21 não está no CSV.")

    tempos = _tempos_relativos(pcap, (int(linha["req_frame"]), int(linha["data_frame"])))
    tempo_req = tempos[int(linha["req_frame"])]
    tempo_data = tempos[int(linha["data_frame"])]
    figura = plt.figure(figsize=(14, 4.15), layout="constrained")
    grade = GridSpec(1, 2, figure=figura, width_ratios=(3.25, 1.35), wspace=0.08)
    eixo_captura = figura.add_subplot(grade[0, 0])
    eixo_captura.imshow(mpimg.imread(captura))
    eixo_captura.set_title("Captura direta do Wireshark — quadros 5 e 21", fontsize=11, pad=5)
    eixo_captura.set_axis_off()

    eixo_csv = figura.add_subplot(grade[0, 1])
    eixo_csv.set_axis_off()
    eixo_csv.set_title("Linha correspondente em correlacao.csv", fontsize=11, pad=9, weight="bold")
    linhas_tabela = [
        ("seq / REQ / DATA", f"{linha['seq']} / {linha['req_frame']} / {linha['data_frame']}"),
        ("Timestamp REQ", f"{tempo_req:.6f} s".replace(".", ",")),
        ("Timestamp DATA", f"{tempo_data:.6f} s".replace(".", ",")),
        ("RTT Wireshark", f"{float(linha['rtt_wireshark_ms']):.3f} ms".replace(".", ",")),
        ("RTT cliente no CSV", f"{float(linha['rtt_cliente_ms']):.3f} ms".replace(".", ",")),
        ("Diferença", f"{float(linha['diferenca_ms']):.3f} ms".replace(".", ",")),
    ]
    tabela = eixo_csv.table(cellText=linhas_tabela, colLabels=("Campo", "Valor"),
                           cellLoc="left", colLoc="left", loc="center",
                           colWidths=(.48, .48))
    tabela.auto_set_font_size(False)
    tabela.set_fontsize(8)
    tabela.scale(1.0, 1.65)
    for (linha_idx, _), celula in tabela.get_celld().items():
        if linha_idx == 0:
            celula.set_facecolor("#E8EEF5")
            celula.set_text_props(weight="bold")
        celula.set_edgecolor("#B8C4D1")
    eixo_csv.xaxis.set_major_locator(NullLocator())

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    figura.savefig(destino, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(figura)
    return destino
