"""Gera figuras adicionais para discutir tamanho, janela, perda e custo.

As figuras são deliberadamente separadas do conjunto principal do relatório:
elas ajudam a discussão sem alterar a tabela integrada de 15 páginas.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import statistics


def carregar(raiz: Path):
    linhas = []
    for caminho in raiz.rglob("resumo.json"):
        try:
            dado = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if dado.get("checksum_ok") is not True or dado.get("done_ok") is not True:
            continue
        dado["origem"] = str(caminho)
        linhas.append(dado)
    return linhas


def media(linhas, campo):
    valores = [float(linha[campo]) for linha in linhas if linha.get(campo) is not None]
    return statistics.mean(valores) if valores else None


def gerar(entradas: list[Path], saida: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    registros = []
    for entrada in entradas:
        registros.extend(carregar(entrada))
    saida.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.titlesize": 13,
                         "axes.labelsize": 10, "figure.facecolor": "white"})
    criados = []

    def salvar(figura, nome):
        png = saida / f"{nome}.png"
        pdf = saida / f"{nome}.pdf"
        figura.savefig(png, dpi=180, bbox_inches="tight")
        figura.savefig(pdf, bbox_inches="tight")
        plt.close(figura)
        criados.extend((png, pdf))

    # Efeito do tamanho com GBN/SR fixos, sem perda, na campanha da Entrega 3.
    grupos = defaultdict(list)
    for linha in registros:
        if (linha.get("protocolo") in ("GBN", "SR") and linha.get("timeout_mode") == "fixed"
                and float(linha.get("loss_rate", 0)) == 0 and linha.get("arquivo") in ("small", "medium", "large")):
            grupos[(linha["arquivo"], linha["protocolo"])].append(linha)
    tamanhos = ["small", "medium", "large"]
    figura, eixos = plt.subplots(1, 2, figsize=(11, 4.2), layout="constrained")
    for protocolo, cor in (("GBN", "#2457A6"), ("SR", "#007F73")):
        vazao = [media(grupos[(tamanho, protocolo)], "throughput_medido_bps") / 1000
                 if grupos[(tamanho, protocolo)] else None for tamanho in tamanhos]
        tempo = [media(grupos[(tamanho, protocolo)], "duracao_s") for tamanho in tamanhos]
        eixos[0].plot(tamanhos, vazao, marker="o", linewidth=2, color=cor, label=protocolo)
        eixos[1].plot(tamanhos, tempo, marker="o", linewidth=2, color=cor, label=protocolo)
    eixos[0].set(ylabel="Vazão média (kbit/s)", title="Vazão por tamanho")
    eixos[1].set(ylabel="Tempo médio (s)", title="Tempo por tamanho")
    for eixo in eixos:
        eixo.grid(axis="y", alpha=.3)
        eixo.legend(frameon=False)
        eixo.set_xlabel("Arquivo (mesmo servidor e segmento)")
    figura.suptitle("Efeito do tamanho do arquivo — Entrega 3, perda 0%, timeout fixo", weight="bold")
    salvar(figura, "tamanho_arquivo_vazao_tempo_entrega3")

    # Janela deslizante em small: a Entrega 2 tem três janelas e três repetições.
    grupos = defaultdict(list)
    for linha in registros:
        if (linha.get("arquivo") == "small" and linha.get("protocolo") in ("GBN", "SR")
                and linha.get("timeout_mode") == "fixed" and float(linha.get("loss_rate", 0)) == 0
                and linha.get("janela") in (4, 8, 16) and "entrega-2" in linha["origem"]):
            grupos[(linha["protocolo"], int(linha["janela"]))].append(linha)
    figura, eixo = plt.subplots(figsize=(8.5, 4.5), layout="constrained")
    for protocolo, cor in (("GBN", "#2457A6"), ("SR", "#007F73")):
        vazoes = [media(grupos[(protocolo, w)], "throughput_medido_bps") / 1000 for w in (4, 8, 16)]
        desvios = []
        for w in (4, 8, 16):
            valores = [float(x["throughput_medido_bps"]) for x in grupos[(protocolo, w)]]
            desvios.append(statistics.stdev(valores) / 1000 if len(valores) > 1 else 0)
        eixo.errorbar([4, 8, 16], vazoes,
                      yerr=desvios,
                      marker="o", linewidth=2, capsize=4, color=cor, label=protocolo)
    eixo.set(xlabel="Janela (segmentos)", ylabel="Vazão média (kbit/s)",
             title="Efeito da janela — Entrega 2, small, sem perda")
    eixo.set_xticks((4, 8, 16)); eixo.grid(axis="y", alpha=.3); eixo.legend(frameon=False)
    salvar(figura, "janela_vazao_entrega2_small")

    # Custo da adaptação no large: relação entre vazão e retransmissões.
    grupos = defaultdict(list)
    for linha in registros:
        if (linha.get("arquivo") == "large" and linha.get("protocolo") == "SR"
                and linha.get("loss_rate") is not None and linha.get("timeout_mode") in ("fixed", "adaptive")):
            grupos[(linha["timeout_mode"], float(linha["loss_rate"]))].append(linha)
    figura, eixo = plt.subplots(figsize=(8.5, 4.8), layout="constrained")
    marcadores = {"fixed": ("o", "#2457A6", "Fixo"), "adaptive": ("s", "#C46B13", "Adaptativo")}
    for modo, (marcador, cor, nome) in marcadores.items():
        xs, ys = [], []
        for perda in (0.0, 0.05, 0.10):
            grupo = grupos.get((modo, perda), [])
            if grupo:
                xs.append(media(grupo, "retransmissoes")); ys.append(media(grupo, "throughput_medido_bps") / 1000)
                eixo.annotate(f"{perda:.0%}", (xs[-1], ys[-1]), xytext=(5, 5), textcoords="offset points", fontsize=9)
        eixo.plot(xs, ys, marker=marcador, color=cor, linewidth=2, label=nome)
    eixo.set(xlabel="Retransmissões médias", ylabel="Vazão média (kbit/s)",
             title="Custo de recuperação — SR, large")
    eixo.grid(alpha=.3); eixo.legend(frameon=False)
    salvar(figura, "tradeoff_vazao_retransmissoes_sr_large")

    # Tempo e retransmissões versus perda, uma leitura direta do impacto da perda.
    figura, eixos = plt.subplots(1, 2, figsize=(11, 4.2), layout="constrained")
    for modo, cor, nome in (("fixed", "#2457A6", "Fixo"), ("adaptive", "#C46B13", "Adaptativo")):
        tempos, reenvios = [], []
        perdas = (0.0, 0.05, 0.10)
        for perda in perdas:
            grupo = grupos.get((modo, perda), [])
            tempos.append(media(grupo, "duracao_s") if grupo else None)
            reenvios.append(media(grupo, "retransmissoes") if grupo else None)
        eixos[0].plot(perdas, tempos, marker="o", color=cor, linewidth=2, label=nome)
        eixos[1].plot(perdas, reenvios, marker="o", color=cor, linewidth=2, label=nome)
    eixos[0].set(ylabel="Tempo médio (s)", title="Tempo de conclusão")
    eixos[1].set(ylabel="Retransmissões médias", title="Tráfego de recuperação")
    for eixo in eixos:
        eixo.set_xlabel("Perda configurada"); eixo.set_xticks((0, .05, .10), ("0%", "5%", "10%")); eixo.grid(alpha=.3); eixo.legend(frameon=False)
    figura.suptitle("Sensibilidade à perda — SR, large", weight="bold")
    salvar(figura, "perda_tempo_retransmissoes_sr_large")
    return criados


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, nargs="+", default=[Path("entrega-3"), Path("entrega-2-remota")])
    parser.add_argument("--output-dir", type=Path, default=Path("entrega-3/analise/graficos_discussao"))
    args = parser.parse_args(argv)
    criados = gerar([entrada.resolve() for entrada in args.input_dir], args.output_dir.resolve())
    print(f"{len(criados)//2} figuras geradas em {args.output_dir}")
    for caminho in criados[::2]: print(caminho)


if __name__ == "__main__":
    main()
