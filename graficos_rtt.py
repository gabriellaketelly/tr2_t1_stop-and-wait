"""Gráficos de RTT e comparação de protocolos a partir de resultados analisados."""

import csv
from pathlib import Path
import shutil
import subprocess
import html
import statistics


def tabelas_integradas_graficos(analise):
    """Mantém compatibilidade com análises antigas que só possuíam large."""
    tabelas = analise.get("integrados_por_arquivo")
    contextos = analise.get("contextos_integrados", {})
    if tabelas is None:
        tabelas = {"large": analise.get("integrados", [])}
        contextos = {"large": analise.get("contexto_integrado")}
    return [(arquivo, tabelas.get(arquivo, []), contextos.get(arquivo) or {})
            for arquivo in ("small", "medium", "large")]


def copiar_grafico_large(pasta):
    for extensao in ("png", "pdf", "svg"):
        caminho = pasta / f"throughput_integrado_large.{extensao}"
        if caminho.is_file():
            shutil.copyfile(caminho, pasta / f"throughput_integrado.{extensao}")


def gerar_graficos(destino: Path, analise: dict) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import MaxNLocator
    except ImportError:
        _gerar_graficos_svg(destino, analise)
        return

    pasta_graficos = destino / "graficos"
    pasta_graficos.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.size": 11, "axes.titlesize": 14, "axes.labelsize": 11,
        "xtick.labelsize": 10, "ytick.labelsize": 10,
        "legend.fontsize": 10, "axes.spines.top": False,
        "axes.spines.right": False, "figure.facecolor": "white",
        "axes.facecolor": "white",
    })

    def salvar_figura(figura, nome):
        figura.savefig(pasta_graficos / f"{nome}.png", dpi=180, bbox_inches="tight")
        figura.savefig(pasta_graficos / f"{nome}.pdf", bbox_inches="tight")
        plt.close(figura)

    def gerar_figura_sem_dados(nome, titulo, mensagem="Sem coleta remota válida"):
        figura, eixo = plt.subplots(figsize=(10, 4), layout="constrained")
        eixo.axis("off")
        eixo.set_title(titulo)
        eixo.text(.5, .5, mensagem, transform=eixo.transAxes, ha="center", va="center")
        salvar_figura(figura, nome)

    for arquivo, integrados, contexto in tabelas_integradas_graficos(analise):
        medidos = [registro for registro in integrados if registro["status"] == "medido"]
        if medidos:
            figura, eixo = plt.subplots(figsize=(12, 4), layout="constrained")
            cores = {"fixed": "#2457A6", "adaptive": "#007F73"}
            posicoes_medidas = []
            for indice, linha in enumerate(integrados):
                if linha["status"] == "medido":
                    valor = linha["throughput_medio_bps"] / 1e6
                    desvio = (linha["throughput_desvio_bps"] or 0) / 1e6
                    eixo.bar(indice, valor, yerr=desvio if linha["n"] > 1 else None,
                           capsize=5, width=.66,
                           color=cores[linha["timeout_mode"]], edgecolor="white", linewidth=.8,
                           error_kw={"elinewidth": 1.3, "capthick": 1.3})
                    posicoes_medidas.append(indice)
                    topo = valor + desvio
                    eixo.annotate(f"{valor:.3f}\nn={linha['n']}", (indice, topo),
                                xytext=(0, 7), textcoords="offset points", ha="center", va="bottom", fontsize=9)
                else:
                    eixo.text(indice, 0, "N/D", ha="center", va="bottom")
            rotulos = [f"{registro['protocolo']}\n{'Fixo' if registro['timeout_mode'] == 'fixed' else 'Adaptativo'}" for registro in integrados]
            eixo.set_xticks(range(len(integrados)))
            eixo.set_xticklabels(rotulos, linespacing=1.2)
            perda = contexto.get("loss_rate", medidos[0].get("loss_rate", 0.0))
            eixo.set_title(f"Vazão média em {arquivo} — perda configurada {perda:.0%}", pad=12, weight="bold")
            eixo.set_ylabel("Vazão média (Mbit/s)")
            maior = max((linha["throughput_medio_bps"] + (linha["throughput_desvio_bps"] or 0)) / 1e6 for linha in medidos)
            eixo.set_ylim(bottom=0, top=maior * 1.18)
            eixo.set_xlim(-.6, len(integrados)-.4)
            eixo.yaxis.set_major_locator(MaxNLocator(6))
            eixo.grid(axis="y", color="#D8E1EA", linewidth=.8)
            eixo.set_axisbelow(True)
            eixo.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=cores["fixed"], label="Timeout fixo"),
                                plt.Rectangle((0, 0), 1, 1, color=cores["adaptive"], label="Timeout adaptativo")],
                        frameon=False, ncols=2, loc="upper left")
            salvar_figura(figura, f"throughput_integrado_{arquivo}")


        else:
            gerar_figura_sem_dados(f"throughput_integrado_{arquivo}", f"Comparação integrada — arquivo {arquivo}")

    copiar_grafico_large(pasta_graficos)

    selecoes = [selecao for selecao in analise["selecao_parametros"] if selecao["escolhido"]]
    arquivos_contextos = {linha["contexto_id"]: linha["arquivo"] for linha in analise["execucoes"]}
    selecoes.sort(key=lambda linha: (arquivos_contextos.get(linha["contexto_id"]) != "large", linha["contexto_id"]))
    if selecoes:
        selecao = selecoes[0]
        classificacao = selecao["ranking"]
        perdas = sorted({linha["loss_rate"] for linha in analise["execucoes"]
            if linha["protocolo"] == selecao["protocolo"]
            and linha["timeout_mode"] == "adaptive"
            and linha["contexto_id"] == selecao["contexto_id"]})
        figura, eixo = plt.subplots(figsize=(10, 5.2), layout="constrained")
        cores_perda = ["#2457A6", "#00877D", "#C46B13"]
        largura = .22
        centros = list(range(len(classificacao)))
        topo_maximo = 0.0
        for indice_perda, perda in enumerate(perdas):
            valores, desvios, posicoes = [], [], []
            for indice_peso, registro in enumerate(classificacao):
                amostras = [linha["throughput_medido_bps"] / 1e6 for linha in analise["execucoes"]
                    if linha["protocolo"] == selecao["protocolo"]
                    and linha["timeout_mode"] == "adaptive"
                    and linha["contexto_id"] == selecao["contexto_id"]
                    and linha["alpha"] == registro["alpha"] and linha["beta"] == registro["beta"]
                    and linha["loss_rate"] == perda]
                valores.append(statistics.mean(amostras) if amostras else 0.0)
                desvios.append(statistics.stdev(amostras) if len(amostras) > 1 else 0.0)
                posicoes.append(centros[indice_peso] + (indice_perda - (len(perdas)-1)/2) * largura)
            eixo.bar(posicoes, valores, width=largura*.9, yerr=desvios, capsize=3,
                     color=cores_perda[indice_perda % len(cores_perda)], edgecolor="white",
                     linewidth=.7, error_kw={"elinewidth": 1.0},
                     label=f"Perda {perda:.0%} (n=3)")
            for x, valor, desvio in zip(posicoes, valores, desvios):
                if valor:
                    eixo.annotate(f"{valor:.2f}", (x, valor + desvio), xytext=(0, 3),
                                  textcoords="offset points", ha="center", va="bottom", fontsize=8)
                topo_maximo = max(topo_maximo, valor + desvio)
        eixo.set_xticks(centros)
        eixo.set_xticklabels([f"α={registro['alpha']:g}   β={registro['beta']:g}" for registro in classificacao])
        eixo.set_ylabel("Vazão média (Mbit/s)")
        eixo.set_title(f"{selecao['protocolo']} adaptativo — janela {selecao['janela']}, arquivo {arquivos_contextos[selecao['contexto_id']]}", pad=10, weight="bold")
        eixo.yaxis.set_major_locator(MaxNLocator(6))
        eixo.set_ylim(0, topo_maximo * 1.22)
        eixo.grid(axis="y", color="#D8E1EA", linewidth=.8)
        eixo.set_axisbelow(True)
        eixo.legend(frameon=False, ncols=len(perdas), loc="upper right")
        salvar_figura(figura, "parametros")
    else:
        gerar_figura_sem_dados("parametros", "Comparação de α e β", "Dados insuficientes para escolher parâmetros empiricamente")

    adaptativos = [registro for registro in analise["execucoes"] if registro["timeout_mode"] == "adaptive"]
    selecionado = None
    if adaptativos:
        preferido = selecoes[0] if selecoes else None
        if preferido:
            vencedor = preferido["escolhido"]
            adaptativos = [registro for registro in adaptativos if registro["contexto_id"] == preferido["contexto_id"]
                        and registro["protocolo"] == preferido["protocolo"]
                        and registro["alpha"] == vencedor["alpha"] and registro["beta"] == vencedor["beta"]]
        # Primeira repetição da maior perda disponível, seleção determinística.
        selecionado = max(adaptativos, key=lambda registro: (
            registro["loss_rate"], registro.get("coleta_inicio_utc") or "", registro["resumo_path"]))
    linhas = []
    if selecionado:
        with Path(selecionado["metricas_path"]).open(newline="", encoding="utf-8") as arquivo_aberto:
            linhas = list(csv.DictReader(arquivo_aberto))
        linhas = [linha for linha in linhas if linha.get("received_elapsed_s") and linha.get("rtt_est_ms")]
        linhas.sort(key=lambda linha: float(linha["received_elapsed_s"]))
    if not linhas:
        gerar_figura_sem_dados("rtt_estimado", "RTT medido e estimado por segmento")
        gerar_figura_sem_dados("timeout", "Evolução do timeout adaptativo")
    else:
        analise["amostra_graficos"] = selecionado["resumo_path"]
        instantes = [float(linha["received_elapsed_s"]) for linha in linhas]
        titulo = (f"{selecionado['protocolo']} — janela {selecionado['janela']}, {selecionado['arquivo']}, "
                 f"perda {selecionado['loss_rate']:.0%}; α={selecionado['alpha']:g}, β={selecionado['beta']:g}")
        figura, eixo = plt.subplots(figsize=(10, 5.4), layout="constrained")
        medidos = [registro for registro in linhas if registro.get("rtt_ms") and registro.get("rtt_sample_valid", "1") == "1"]
        passo_amostra = max(1, len(medidos) // 1800)
        medidos_visiveis = medidos[::passo_amostra]
        eixo.scatter([float(registro["received_elapsed_s"]) for registro in medidos_visiveis],
                   [float(registro["rtt_ms"]) for registro in medidos_visiveis], s=8, alpha=.28,
                   color="#2457A6", linewidths=0, label="RTT medido válido")
        eixo.plot(instantes, [float(registro["rtt_est_ms"]) for registro in linhas], linewidth=1.8,
                  color="#C46B13", label="RTT estimado (EWMA)")
        valores_rtt = [float(registro["rtt_ms"]) for registro in medidos] + [float(registro["rtt_est_ms"]) for registro in linhas]
        limite_inferior = max(0, min(valores_rtt) - 5)
        limite_superior = max(valores_rtt) + 5
        eixo.set(xlabel="Tempo desde o primeiro REQ (s), ordem de chegada", ylabel="RTT (ms)", title=titulo)
        eixo.set_ylim(limite_inferior, limite_superior)
        eixo.set_xlim(0, max(instantes))
        eixo.legend(frameon=False, ncols=2, loc="upper right")
        eixo.grid(color="#D8E1EA", linewidth=.8)
        eixo.set_axisbelow(True)
        salvar_figura(figura, "rtt_estimado")
        figura, eixo = plt.subplots(figsize=(10, 5.4), layout="constrained")
        passo = max(1, len(linhas) // 1600)
        rtos = [float(registro["timeout_ms"]) for registro in linhas]
        eixo.plot(instantes[::passo], rtos[::passo],
                  label="RTO recalculado (SRTT + 4 × DevRTT)", linewidth=1.8, color="#007F73")
        timeout_inicial_ms = selecionado["timeout_s"] * 1000
        eixo.axhline(timeout_inicial_ms, linestyle=(0, (5, 3)), linewidth=1.5,
                     color="#52657A", label=f"Timeout inicial: {timeout_inicial_ms:.0f} ms")
        mediana_rto = float(__import__("statistics").median(rtos))
        eixo.axhline(mediana_rto, linestyle=":", linewidth=1.2, color="#C46B13",
                     label=f"Mediana do RTO: {mediana_rto:.1f} ms")
        eixo.set(xlabel="Tempo desde o primeiro REQ (s)", ylabel="RTO calculado (ms)", title=titulo)
        eixo.set_ylim(bottom=0, top=max(rtos + [timeout_inicial_ms]) * 1.12)
        eixo.set_xlim(0, max(instantes))
        eixo.yaxis.set_major_locator(MaxNLocator(6))
        eixo.text(.985, .90, f"Timeout inicial: {timeout_inicial_ms:.0f} ms",
                  transform=eixo.transAxes, ha="right", va="top", color="#52657A",
                  fontsize=9, bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 2})
        eixo.text(.985, .84, f"Mediana do RTO: {mediana_rto:.1f} ms",
                  transform=eixo.transAxes, ha="right", va="top", color="#A94F0D",
                  fontsize=9, bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 2})
        eixo.grid(color="#D8E1EA", linewidth=.8)
        eixo.set_axisbelow(True)
        salvar_figura(figura, "timeout")
def _gerar_graficos_svg(destino: Path, analise: dict) -> None:
    """Gera figuras vetoriais sem dependências Python de plotting."""
    pasta = destino / "graficos"
    pasta.mkdir(parents=True, exist_ok=True)
    conversor = shutil.which("rsvg-convert")

    def salvar_svg(nome: str, conteudo: str) -> None:
        arquivo_svg = pasta / f"{nome}.svg"
        arquivo_svg.write_text(conteudo, encoding="utf-8")
        if conversor:
            for formato in ("png", "pdf"):
                subprocess.run([conversor, "-f", formato, "-o", str(pasta / f"{nome}.{formato}"),
                                str(arquivo_svg)], check=True, capture_output=True)

    def eixos(titulo, xlabel, ylabel, xmax, ymax):
        largura, altura = 1000, 540
        esquerda, direita, topo, baixo = 88, 28, 58, 72
        area_w, area_h = largura - esquerda - direita, altura - topo - baixo
        partes = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{altura}" viewBox="0 0 {largura} {altura}">',
                  '<rect width="100%" height="100%" fill="white"/>',
                  f'<text x="{largura/2}" y="30" text-anchor="middle" font-family="sans-serif" font-size="20">{html.escape(titulo)}</text>',
                  f'<path d="M {esquerda} {topo} V {topo+area_h} H {esquerda+area_w}" fill="none" stroke="#334155"/>']
        for i in range(6):
            valor = ymax * i / 5
            y = topo + area_h * (1-i/5)
            partes += [f'<path d="M {esquerda} {y:.1f} H {esquerda+area_w}" stroke="#e2e8f0"/>',
                       f'<text x="{esquerda-10}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12">{valor:.3g}</text>']
        for i in range(6):
            valor = xmax * i / 5
            x = esquerda + area_w * i / 5
            partes.append(f'<text x="{x:.1f}" y="{topo+area_h+24}" text-anchor="middle" font-family="sans-serif" font-size="12">{valor:.3g}</text>')
        partes += [f'<text x="{esquerda+area_w/2}" y="{altura-15}" text-anchor="middle" font-family="sans-serif" font-size="14">{html.escape(xlabel)}</text>',
                   f'<text transform="translate(22 {topo+area_h/2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="14">{html.escape(ylabel)}</text>']
        return partes, (esquerda, topo, area_w, area_h)

    execucoes = analise.get("execucoes", [])
    adaptativos = [linha for linha in execucoes if linha.get("timeout_mode") == "adaptive"]
    selecionado = None
    for linha in analise.get("selecao_parametros", []):
        escolhido = linha.get("escolhido")
        if not escolhido:
            continue
        selecionado = next((item for item in adaptativos
            if item.get("contexto_id") == linha.get("contexto_id")
            and item.get("protocolo") == linha.get("protocolo")
            and item.get("alpha") == escolhido.get("alpha")
            and item.get("beta") == escolhido.get("beta")), None)
        if selecionado:
            break
    amostras = []
    if selecionado and selecionado.get("metricas_path"):
        with Path(selecionado["metricas_path"]).open(newline="", encoding="utf-8") as entrada:
            amostras = list(csv.DictReader(entrada))
        amostras = [r for r in amostras if r.get("received_elapsed_s") and r.get("rtt_est_ms")]
        amostras.sort(key=lambda r: float(r["received_elapsed_s"]))

    cores = {"medido": "#2563eb", "estimado": "#b45309", "rto": "#0f766e", "usado": "#7c3aed"}
    if amostras:
        tempos = [float(r["received_elapsed_s"]) for r in amostras]
        pontos = [(float(r["rtt_ms"]), r) for r in amostras if r.get("rtt_ms") and r.get("rtt_sample_valid", "1") == "1"]
        ymax = max([float(r["rtt_est_ms"]) for r in amostras] + [v for v, _ in pontos]) * 1.08
        partes, geo = eixos("RTT medido e estimado por segmento", "Tempo desde o início da transferência (s)", "RTT (ms)", max(tempos), ymax)
        left, top, w, h = geo
        def xy(t, y): return left + w*t/max(tempos), top+h*(1-y/ymax)
        for chave, cor in (("estimado", cores["estimado"]),):
            coords = " ".join(f"{x:.1f},{y:.1f}" for x,y in (xy(float(r["received_elapsed_s"]), float(r["rtt_est_ms"])) for r in amostras))
            partes.append(f'<polyline points="{coords}" fill="none" stroke="{cor}" stroke-width="1.5"/>')
        for indice, (_, registro) in enumerate(pontos[::max(1, len(pontos)//2500)]):
            x,y = xy(float(registro["received_elapsed_s"]), float(registro["rtt_ms"]))
            partes.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{cores["medido"]}" opacity=".55"/>')
        partes += [f'<text x="{left+10}" y="{top+18}" font-family="sans-serif" font-size="13" fill="{cores["medido"]}">RTT medido</text>',
                   f'<text x="{left+130}" y="{top+18}" font-family="sans-serif" font-size="13" fill="{cores["estimado"]}">RTT estimado</text>', '</svg>']
        salvar_svg("rtt_estimado", "".join(partes))

        inicial = float(selecionado.get("timeout_s") or 0.2) * 1000
        ymax = max(max(float(r["timeout_ms"]) for r in amostras), inicial) * 1.08
        partes, geo = eixos("Timeout adaptativo durante a transferência", "Tempo desde o início da transferência (s)", "Timeout (ms)", max(tempos), ymax)
        left, top, w, h = geo
        def xy2(t, y): return left + w*t/max(tempos), top+h*(1-y/ymax)
        series = [r for r in amostras if r.get("timeout_ms")]
        coords = " ".join(f"{x:.1f},{y:.1f}" for x,y in (xy2(float(r["received_elapsed_s"]), float(r["timeout_ms"])) for r in series))
        partes.append(f'<polyline points="{coords}" fill="none" stroke="{cores["rto"]}" stroke-width="2"/>')
        yi = xy2(0, inicial)[1]
        partes += [f'<path d="M {left} {yi:.1f} H {left+w}" stroke="#52657A" stroke-width="1.5" stroke-dasharray="7 5"/>',
                   f'<text x="{left+10}" y="{top+18}" font-family="sans-serif" font-size="13" fill="{cores["rto"]}">RTO recalculado (SRTT + 4 × DevRTT)</text>',
                   f'<text x="{left+10}" y="{top+40}" font-family="sans-serif" font-size="13" fill="#52657A">Timeout inicial ({inicial:.0f} ms)</text>', '</svg>']
        salvar_svg("timeout", "".join(partes))
    else:
        for nome, titulo in (("rtt_estimado", "RTT medido e estimado"), ("timeout", "Timeout adaptativo")):
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="400">'
                   f'<rect width="100%" height="100%" fill="white"/><text x="450" y="190" text-anchor="middle" font-family="sans-serif" font-size="22">{html.escape(titulo)}</text>'
                   '<text x="450" y="230" text-anchor="middle" font-family="sans-serif" font-size="16">Dados de estimador indisponíveis</text></svg>')
            salvar_svg(nome, svg)

    for arquivo, integrados, contexto in tabelas_integradas_graficos(analise):
        linhas = [r for r in integrados if r.get("status") == "medido"]
        if linhas:
            xmax = len(linhas)
            ymax = max(r["throughput_medio_bps"] / 1e6 for r in linhas) * 1.15
            partes, geo = eixos(f"Throughput médio em {arquivo} por protocolo e timeout", "Configuração", "Throughput (Mbit/s)", xmax, ymax)
            left, top, w, h = geo
            slot = w/xmax
            for i, r in enumerate(linhas):
                valor = r["throughput_medio_bps"] / 1e6
                altura = h * valor/ymax
                cor = "#2563eb" if r["timeout_mode"] == "fixed" else "#0f766e"
                x = left+i*slot+slot*.2
                partes.append(f'<rect x="{x:.1f}" y="{top+h-altura:.1f}" width="{slot*.6:.1f}" height="{altura:.1f}" fill="{cor}"/>')
                label = f'{r["protocolo"]} {"fixo" if r["timeout_mode"]=="fixed" else "adapt."}'
                partes.append(f'<text transform="translate({x+slot*.3:.1f} {top+h+34}) rotate(-35)" text-anchor="end" font-family="sans-serif" font-size="10">{html.escape(label)}</text>')
            partes.append('</svg>')
            salvar_svg(f"throughput_integrado_{arquivo}", "".join(partes))
        else:
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="400"><rect width="100%" height="100%" fill="white"/><text x="450" y="200" text-anchor="middle" font-family="sans-serif" font-size="22">Throughput integrado de {arquivo} sem dados</text></svg>'
            salvar_svg(f"throughput_integrado_{arquivo}", svg)
    copiar_grafico_large(pasta)
