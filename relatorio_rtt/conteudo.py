"""Composição do relatório a partir das evidências disponíveis."""

import csv
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

from analisar_rtt import (
    agrupar_resultados,
    coletar_resultados,
    listar_cenarios_planejados,
    montar_tabela_integrada,
    selecionar_parametros,
)
from .anexos import SERVIDOR_REMOTO, carregar_resumos, ler_json, organizar_anexos
from .comparacao import existe_comparacao_pareada, preparar_linhas_comparativas
from .dados_graficos import consolidar_dados_graficos
from .formatacao import escapar_latex, formatar_numero, incluir_figura, montar_tabela
from .figura_correlacao import gerar_figura_correlacao

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


def formatar_inteiro(valor):
    return f"{int(valor):,}".replace(",", ".")


def incluir_grade_graficos_discussao(pasta):
    """Inclui os quatro gráficos adicionais em uma figura compacta."""
    nomes = [
        ("janela_vazao_entrega2_small.png", "Janela e vazão — Entrega 2 (small)"),
        ("perda_tempo_retransmissoes_sr_large.png", "Perda, tempo e retransmissões — SR large"),
        ("tamanho_arquivo_vazao_tempo_entrega3.png", "Tamanho do arquivo, vazão e tempo — Entrega 3"),
        ("tradeoff_vazao_retransmissoes_sr_large.png", "Compromisso entre vazão e retransmissões — SR large"),
    ]
    if not all((pasta / nome).is_file() for nome, _ in nomes):
        return r"\begin{quote}\textbf{Pendente:} gráficos adicionais de discussão não encontrados.\end{quote}"
    blocos = []
    for indice in (0, 2):
        linha = []
        for nome, legenda in nomes[indice:indice + 2]:
            caminho = str((pasta / nome).resolve())
            linha.append(r"\begin{minipage}[t]{0.48\linewidth}\centering" +
                         r"\includegraphics[width=\linewidth,height=0.20\textheight,keepaspectratio]{\detokenize{" + caminho + r"}}\par\scriptsize " +
                         escapar_latex(legenda) + r"\end{minipage}")
        blocos.append(r"\hspace{0.02\linewidth}".join(linha))
    return (r"\begin{figure}[!ht]\centering" + "\n" + "\n\\vspace{0.5em}\n".join(blocos) +
            r"\caption{Gráficos adicionais usados para discutir o efeito da janela, das perdas, do tamanho do arquivo e do custo de retransmissão.}" +
            r"\end{figure}")


def resumir_amostra_grafico(analise):
    """Calcula as estatísticas do mesmo CSV usado nos gráficos, sem valores fixos."""
    caminho_resumo = Path(analise.get("amostra_graficos", ""))
    metadados = next((registro for registro in analise.get("execucoes", [])
                      if registro.get("resumo_path") == str(caminho_resumo.resolve())), {})
    caminho = Path(metadados.get("metricas_path", ""))
    if not caminho.is_file():
        return {}
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))
    linhas.sort(key=lambda linha: float(linha.get("received_elapsed_s") or 0))
    validas = [linha for linha in linhas if linha.get("rtt_ms")
               and linha.get("rtt_sample_valid", "1") == "1"]

    def valores(campo, conjunto):
        return [float(linha[campo]) for linha in conjunto if linha.get(campo) not in (None, "")]

    def percentil(conjunto, fracao):
        ordenados = sorted(conjunto)
        return ordenados[max(0, math.ceil(fracao * len(ordenados)) - 1)] if ordenados else None

    medidos = valores("rtt_ms", validas)
    estimados = valores("rtt_est_ms", linhas)
    desvios = valores("dev_rtt_ms", linhas)
    rtos = valores("timeout_ms", linhas)
    primeira = validas[0] if validas else {}
    resumo_json = Path(metadados.get("resumo_path", ""))
    resumo = ler_json(resumo_json) if resumo_json.is_file() else {}
    return {
        "caminho": str(caminho), "metadados": metadados, "total": len(linhas),
        "validas": len(validas), "percentual_validas": 100 * len(validas) / len(linhas) if linhas else 0,
        "rtt_media": statistics.mean(medidos) if medidos else None,
        "rtt_mediana": statistics.median(medidos) if medidos else None,
        "rtt_p95": percentil(medidos, .95),
        "srtt_media": statistics.mean(estimados) if estimados else None,
        "srtt_mediana": statistics.median(estimados) if estimados else None,
        "dev_media": statistics.mean(desvios) if desvios else None,
        "dev_mediana": statistics.median(desvios) if desvios else None,
        "rto_media": statistics.mean(rtos) if rtos else None,
        "rto_mediana": statistics.median(rtos) if rtos else None,
        "rto_p95": percentil(rtos, .95),
        "rtt_primeiro": float(primeira["rtt_ms"]) if primeira else None,
        "rto_primeiro": float(primeira["timeout_ms"]) if primeira and primeira.get("timeout_ms") else None,
        "timeout_fixo": float(resumo.get("timeout_s", .2)) * 1000,
        "retransmissoes": resumo.get("retransmissoes"),
    }


def gerar_documento(argumentos):
    diretorios_coleta = [argumentos.diretorio_entrada]
    diretorios_coleta.extend(sorted(
        pasta for pasta in argumentos.diretorio_entrada.iterdir()
        if pasta.is_dir() and (pasta / "manifesto.json").is_file()
    ))
    registros_atuais, avisos_coleta = coletar_resultados(diretorios_coleta)
    atuais = []
    for registro in registros_atuais:
        linha = ler_json(Path(registro["resumo_path"]))
        linha.update(origem=registro["resumo_path"], protocolo=registro["protocolo"],
                   janela=registro["janela"], timeout_mode=registro["timeout_mode"],
                   loss_rate=registro["loss_rate"])
        atuais.append(linha)
    pasta_janelas_remotas = RAIZ_PROJETO / "entrega-2-remota"
    registros_janelas_remotos, avisos_janelas = (
        coletar_resultados([pasta_janelas_remotas]) if pasta_janelas_remotas.is_dir() else ([], [])
    )
    dados_janelas_remotos = []
    for registro in registros_janelas_remotos:
        linha = ler_json(Path(registro["resumo_path"]))
        linha.update(origem=registro["resumo_path"], protocolo=registro["protocolo"],
                     janela=registro["janela"], timeout_mode=registro["timeout_mode"],
                     loss_rate=registro["loss_rate"])
        dados_janelas_remotos.append(linha)
    grupos_janelas_remotos = agrupar_resultados(registros_janelas_remotos)
    historico_saw = carregar_resumos(RAIZ_PROJETO / "resultados")
    historico_saw = [registro for registro in historico_saw if registro["protocolo"] == "SAW" and registro.get("servidor") == SERVIDOR_REMOTO]
    historico_janelas = [registro for registro in carregar_resumos(RAIZ_PROJETO / "entrega-2-v2")
                 if "-w" in registro['origem'] and "-loss" in registro['origem']]
    argumentos.diretorio_saida.mkdir(parents=True, exist_ok=True)
    manifesto_brutos, verificacoes_md5 = organizar_anexos(argumentos.diretorio_saida,
        [("entrega1", historico_saw), ("entrega2_historica", historico_janelas),
         ("entrega2_remota", dados_janelas_remotos), ("entrega3", atuais)])
    analise = ler_json(argumentos.diretorio_analise / "analise.json")
    manifesto = consolidar_dados_graficos(
        argumentos.diretorio_saida / "anexos" / "dados_graficos_consolidado.csv",
        analise, grupos_janelas_remotos, historico_saw, verificacoes_md5,
    )
    imagem_correlacao = argumentos.diretorio_wireshark / "screenshot3_correlacao_anotada.png"
    try:
        gerar_figura_correlacao(
            argumentos.diretorio_wireshark / "screenshot3_correlacao.png",
            argumentos.diretorio_wireshark / "correlacao.csv",
            argumentos.diretorio_wireshark / "sr-large.pcap",
            imagem_correlacao,
        )
    except (OSError, RuntimeError, ValueError) as erro:
        imagem_correlacao.unlink(missing_ok=True)
        avisos_coleta.append(f"Não foi possível montar a correlação visual Wireshark/CSV: {erro}")
    resumo_rtt_grafico = resumir_amostra_grafico(analise)
    resultados_integrados, contexto_integrado = montar_tabela_integrada(registros_atuais, agrupar_resultados(registros_atuais))
    planejados = listar_cenarios_planejados([argumentos.diretorio_entrada])
    selecoes = selecionar_parametros(registros_atuais, planejados)
    imagens = argumentos.diretorio_analise / "graficos"
    imagens_discussao = argumentos.diretorio_analise / "graficos_discussao"
    capturas_tela = [("screenshot1_sessao.png", "Captura direta da janela do Wireshark, com filtro aplicado: HELLO (quadro 1), REQs, DATA, FIN (quadro 79531) e DONE (quadro 79532), no PCAP completo de 79.532 quadros."),
                   ("screenshot2_retransmissoes.png", "Captura direta do Wireshark. Quadros 44 e 63: sequência 19, delta de 100,059 ms; quadros 10 e 68: sequência 5, delta de 502,183 ms."),
                   ("screenshot3_correlacao_anotada.png", "À esquerda, captura direta do Wireshark; à direita, a linha da sequência 0 em correlacao.csv, com os timestamps dos quadros REQ 5 e DATA 21. O RTT da captura é 40,230 ms e o RTT registrado pelo cliente é 40,524 ms; diferença de 0,294 ms.")]
    pendencias = []
    if not atuais:
        pendencias.append("Nenhuma transferência completa da Entrega 3 foi validada no servidor remoto.")
    caminhos_analisados = {linha.get("resumo_path") for linha in analise.get("execucoes", [])}
    caminhos_atuais = {linha["resumo_path"] for linha in registros_atuais}
    if not analise or caminhos_analisados != caminhos_atuais:
        pendencias.append("Análise e gráficos desatualizados: execute analisar_rtt.py para as coletas atuais.")
    adaptativos = [registro for registro in atuais if registro["timeout_mode"] == "adaptive"]
    if not any(len(selecao["ranking"]) >= 3 and selecao["escolhido"] is not None for selecao in selecoes):
        pendencias.append("Falta a comparação válida dos três pares de alpha e beta no mesmo contexto.")
    identificadores_concluidos = {linha.get("experimento_id") for linha in atuais}
    cenarios_ausentes = [configuracao["id"] for configuracao in planejados if configuracao["id"] not in identificadores_concluidos]
    if cenarios_ausentes:
        pendencias.append(f"Matriz planejada incompleta: {len(cenarios_ausentes)} de {len(planejados)} cenários sem resultado validado.")
    comparacao_completa = existe_comparacao_pareada(registros_atuais)
    if not comparacao_completa:
        pendencias.append("Falta a comparação do mesmo protocolo fixo/adaptativo sob perdas de 5\\% e 10\\%.")
    arquivos_grandes = [registro for registro in atuais if registro["arquivo"] == "large"]
    if any(registro["status"] != "medido" for registro in resultados_integrados):
        pendencias.append("A tabela integrada ainda não tem as cinco configurações medidas no remoto com large.")
    for nome, _ in capturas_tela:
        if not (argumentos.diretorio_wireshark / nome).is_file():
            pendencias.append("Screenshot obrigatório ausente: " + nome)
    caminho_correlacoes = argumentos.diretorio_wireshark / "correlacao.csv"
    correlacoes = []
    if caminho_correlacoes.is_file():
        with caminho_correlacoes.open(newline="", encoding="utf-8") as arquivo:
            correlacoes = list(csv.DictReader(arquivo))
    caminho_retransmissoes = argumentos.diretorio_wireshark / "retransmissoes.csv"
    retransmissoes_captura = []
    if caminho_retransmissoes.is_file():
        with caminho_retransmissoes.open(newline="", encoding="utf-8") as arquivo:
            retransmissoes_captura = list(csv.DictReader(arquivo))
    eventos_retransmissoes = []
    sequencias_retransmitidas = set()
    for linha in retransmissoes_captura:
        if linha["seq"] not in sequencias_retransmitidas:
            eventos_retransmissoes.append(linha)
            sequencias_retransmitidas.add(linha["seq"])
        if len(eventos_retransmissoes) == 2:
            break
    if not correlacoes:
        pendencias.append("Falta a comparação numérica de RTT entre captura e cliente.")
    resumo_captura = ler_json(argumentos.diretorio_wireshark / "captura_resumo.json")
    if not (resumo_captura.get("session_complete") is True and resumo_captura.get("done_ok") is True
            and resumo_captura.get("large_requested") is True
            and resumo_captura.get("retransmissions", 0) >= 2
            and resumo_captura.get("correlated_samples", 0) > 0):
        pendencias.append("A captura ainda não comprova sessão large completa, dois eventos de retransmissão e RTT correlacionado.")
    for nome in ("rtt_estimado.png", "timeout.png", "throughput_integrado.png"):
        tem_observacoes = bool(adaptativos) if nome != "throughput_integrado.png" else bool(arquivos_grandes)
        if not (imagens / nome).is_file() or not tem_observacoes:
            pendencias.append("Gráfico aguardando coleta: " + nome)
    titulo = "Relatório parcial" if pendencias else "Relatório final"
    data_geracao = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M")
    paragrafos = [r"\documentclass[7pt,a4paper]{article}",
        r"\usepackage[T1]{fontenc}\usepackage[utf8]{inputenc}\usepackage[brazil]{babel}",
        r"\usepackage[margin=1.5cm]{geometry}\usepackage{amsmath,amssymb,graphicx}",
        r"\usepackage{tabularx,booktabs,caption,xcolor,tikz}",
        r"\captionsetup{font=small,skip=3pt,hypcap=false}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\setlength{\parindent}{1.25em}\setlength{\parskip}{2pt}",
        r"\setlength{\emergencystretch}{3em}",
        r"\title{Transferência confiável sobre UDP\\[6pt]\large Entrega Final: RTT Adaptativo --- Grupo 08}",
        r"\author{Gabriella Ketelly Almeida da Silva --- 241008200\\Ian Pereira Silva --- 241024286\\Laryssa de Oliveira Ferreira --- 222005386}",
        r"\date{\small CIC0236 | Teleinformática e Redes 2\\Universidade de Brasília | 2026/2}",
        r"\hypersetup{pdftitle={Entrega Final | RTT Adaptativo | Grupo 08}}",
        r"\begin{document}\maketitle",
        r"\begin{center}\small Relatório final do Grupo 08\end{center}"]
    if pendencias:
        paragrafos.append(r"\begin{quote}\color{red!65!black}\textbf{Status: evidências incompletas.} "
            "Este PDF documenta a implementação e os dados disponíveis. As lacunas abaixo impedem "
            "considerá-lo pronto para a entrega final. Não foram substituídas por dados locais ou sintéticos."
            r"\end{quote}")
    paragrafos += [r"\section{Introdução e evolução do projeto}",
        "Na Entrega 1, nosso objetivo era fazer uma transferência UDP chegar completa, na ordem e sem erro. No SAW, o cliente envia um REQ, espera o DATA, manda o ACK e só então pede o próximo segmento. Isso tornou a validação mais simples, mas também mostrou o limite do protocolo: só há um pedido em trânsito.",
        "Na primeira coleta, nós nos deparamos com duas situações importantes. O servidor respondia ao ACK com o erro específico "
        + r"\texttt{tipo\_desconhecido\_ACK}"
        + ". Nós decidimos tolerar somente esse erro conhecido. Também percebemos que o timeout de 2 s era muito maior que o RTT medido e passamos a escolher os prazos com base nos dados.",
        "Na Entrega 2, nós mantivemos vários pedidos em trânsito com GBN e SR. O GBN repete a partir da base da janela; o SR guarda DATA fora de ordem e repete apenas o segmento que venceu o prazo. Os testes feitos durante a indisponibilidade do servidor ficaram como auxiliares. A comparação principal usa as coletas remotas.",
        "Na Entrega 3, passamos a calcular o tempo de espera com RTT e DevRTT. Como o DATA não identifica a tentativa, não usamos RTT de segmentos retransmitidos (regra de Karn). Os timestamps do CSV e a captura Wireshark nos permitem conferir essa medição.",
        "No fim, a evolução foi do SAW para as janelas GBN/SR e depois para o timeout adaptativo. Em cada etapa, nós observamos tempo, vazão e retransmissões.",
        r"\subsection*{Origem dos dados e método}",
        "As novas coletas são exclusivamente remotas, em " + escapar_latex(SERVIDOR_REMOTO + ":8080") + ". "
        "Os testes auxiliares da Entrega 2 usaram um arquivo sintético de 64 KiB enquanto o servidor estava indisponível. Nós os mantivemos para registrar a depuração, mas eles não entram na comparação de desempenho. As tabelas principais usam coletas remotas válidas, e os anexos preservam os dados originais."]
    paragrafos.append(montar_tabela(["Arquivo", "Bytes", "RTT médio (ms)", "Throughput (kbit/s)", "Tempo (s)", "Retr."],
        [(escapar_latex(registro["arquivo"]), registro["file_size"], formatar_numero(registro.get("rtt_medio_s", 0) * 1000),
          formatar_numero(registro["throughput_medido_bps"] / 1000), formatar_numero(registro["duracao_s"]), registro["retransmissoes"])
         for registro in historico_saw], "lrrrrr"))
    paragrafos += [
        "Os resumos identificam grupo08, servidor, timeout e MD5. As três transferências SAW históricas tiveram RTT médio de 42,624 ms (small), 42,020 ms (medium) e 42,567 ms (large), com eficiência de 99,25%, 99,24% e 98,52% em relação ao limite teórico. Os gráficos por segmento mostram small e medium sem timeout; large teve três timeouts, que consumiram 6,130 s (0,693% da duração).",
        "O timeout histórico de 2 s era muito maior que a cauda observada (p99 de 54,94 ms e máximo de 130,51 ms), motivando a matriz posterior com 0,2 s fixos e RTO adaptativo limitado. O teste exploratório com segmento de 256 bytes confirmou a relação aproximadamente linear entre tamanho do segmento e vazão, mas não substitui a matriz principal. O SAW legado não tinha timestamps; em GBN/SR, intervalos por segmento se sobrepõem e a duração oficial continua sendo a do resumo.",
        r"\clearpage\section{RTT adaptativo: implementação}",
        "Seja $R_n$ o intervalo monotônico entre REQ e DATA válidos da sequência. "
        "A primeira amostra inicializa $S_1=R_1$ e $D_1=R_1/2$. Para as demais:",
        r"\begin{align*}S_n &= (1-\alpha)S_{n-1}+\alpha R_n\\"
        r"D_n &= (1-\beta)D_{n-1}+\beta\lvert R_n-S_n\rvert\\"
        r"RTO_n &= S_n+4D_n.\end{align*}",
        "O timeout inicial vem de \\texttt{--timeout}. O modo adaptativo limita o RTO entre "
        "\\texttt{--rto-min} e \\texttt{--rto-max}; os padrões são 0,01 s e 60 s. "
        "No modo fixo, o timeout informado permanece constante. HELLO e FIN usam o timeout de controle.",
        "A regra de Karn impede usar um segmento retransmitido como amostra: sem identificador "
        "da tentativa no DATA, não se sabe qual REQ causou a resposta. O CSV preserva a duração "
        "e as retransmissões, mas deixa RTT vazio e marca a amostra como inválida. "
        "No SR, a medição ocorre ao receber DATA, antes de esperar o buffer ficar contíguo.",
        "O backoff dobra o prazo após timeout, respeitando o teto. "
        "A atualização do estimador não altera os prazos dos demais pedidos em trânsito. "
        "A implementação verifica a expiração também quando chegam mensagens irrelevantes, "
        "evitando que esse tráfego adie indefinidamente uma retransmissão.",
        "O SR aplica backoff por segmento; o GBN usa o temporizador compartilhado da base, "
        "reiniciado quando ela avança. Assim, no GBN o intervalo entre REQ e retransmissão pode "
        "superar o timeout registrado no envio; o evento TIMEOUT registra a expiração efetiva. "
        "Cada DATA elegível atualiza a EWMA, podendo haver várias amostras em um mesmo RTT.",
        r"\textbf{Escopo da analogia com TCP.} A \href{https://www.rfc-editor.org/rfc/rfc6298}{RFC 6298} "
        "usa SRTT anterior no desvio e recomenda piso de 1 s. Aqui usamos SRTT atualizado, "
        "conforme a implementação adotada, e piso configurável para o experimento. Karn e backoff são preservados; "
        "não se pretende implementar todo o TCP.",
        r"\subsection*{Escolha de alpha e beta}",
        "A matriz testa $(0{,}125;0{,}25)$, $(0{,}0625;0{,}125)$ e $(0{,}25;0{,}5)$. "
        "Os pesos menores suavizam mais o histórico; os maiores respondem mais às últimas amostras. "
        "Cada combinação foi medida três vezes por nível de perda, com as mesmas condições pareadas. "
        "Nas perdas de 5\\% e 10\\%, 0,0625/0,125 teve média de 513,32 kbit/s, 169,20 s e 6.611 "
        "retransmissões; 0,125/0,25 obteve 504,71 kbit/s, 172,39 s e 9.293 retransmissões; "
        "0,25/0,5 obteve 472,67 kbit/s, 180,31 s e 12.529 retransmissões. O par de pesos menores "
        "foi escolhido porque combinou maior vazão e menos retransmissões entre os três candidatos, "
        "no conjunto das duas perdas. A diferença é descritiva; três execuções por condição não "
        "estabelecem significância estatística."]
    if not adaptativos:
        paragrafos.append(r"\textbf{Resultado ainda indisponível:} nenhum par de pesos foi validado "
            "em uma transferência remota completa nesta entrega; não há vencedor experimental a declarar.")
    else:
        linhas = preparar_linhas_comparativas([registro for registro in registros_atuais if registro["timeout_mode"] == "adaptive"])
        paragrafos.append(montar_tabela(["Proto./arquivo", r"$\alpha$", r"$\beta$", "Perda", "$n$", "kbit/s", "Retr."],
            [(escapar_latex(registro["protocolo"] + "/" + registro["arquivo"]), formatar_numero(registro.get("alpha"), 4), formatar_numero(registro.get("beta"), 3),
              formatar_numero(100 * registro["loss_rate"], 0) + r"\%", registro["n"], formatar_numero(registro['vazao'] / 1000),
              formatar_numero(registro['retransmissoes'], 1)) for registro in linhas[:18]], "lrrrrrr"))
        paragrafos.append("A tabela mostra as médias das execuções válidas; o anexo conserva cada medição. "
            "Os desvios e o critério de seleção estão na análise exportada. Comparações entre arquivos "
            "ou parâmetros de rede diferentes não estabelecem qual par é superior.")
        for selecao in selecoes:
            escolhido = selecao.get("escolhido")
            if escolhido:
                paragrafos.append(escapar_latex(
                    f"No contexto {selecao['contexto_id']} do {selecao['protocolo']}, "
                    f"alpha={escolhido['alpha']} e beta={escolhido['beta']} tiveram a maior média "
                    f"nas {escolhido['n']} condições pareadas: "
                    f"{escolhido['throughput_medio_bps'] / 1000:.3f} kbit/s, "
                    f"{escolhido['retransmissoes_media']:.1f} retransmissões e "
                    f"{escolhido['tempo_medio_s']:.3f} s. A escolha é descritiva das "
                    "condições comuns, sem teste de significância estatística."))
    imagens_medidas = imagens if adaptativos else imagens / "aguardando_coleta"
    paragrafos += [incluir_figura(imagens_medidas / "rtt_estimado.png", "RTT por tempo de chegada: pontos são amostras válidas segundo Karn, linha é a EWMA. O eixo vertical foca a faixa observada para facilitar a leitura.", "0.40\\textheight"),
        incluir_figura(imagens_medidas / "timeout.png", "RTO recalculado por SRTT + 4 × DevRTT; as linhas horizontais indicam o timeout inicial e a mediana do RTO.", "0.40\\textheight"),
        r"\clearpage\section{Comparação entre timeout fixo e adaptativo}",
        "O protocolo, a janela, o arquivo, o tamanho do segmento e a perda configurada são mantidos "
        "em cada comparação. As perdas de 5\\% e 10\\% são induzidas no cliente: DATA recebidos são "
        "descartados antes de aceitação. Portanto, esses pacotes ainda aparecem na captura da interface. "
        "A taxa configurada é uma probabilidade, não a garantia de um número exato de descartes."]
    comparaveis = [registro for registro in preparar_linhas_comparativas(registros_atuais) if round(registro["loss_rate"], 2) in (.05, .10)]
    if comparaveis:
        paragrafos.append(montar_tabela(["Proto./arquivo", "Modo / pesos", "Perda", "$n$", "Retr.", "Tempo (s)", "kbit/s"],
            [(escapar_latex(registro["protocolo"] + "/" + registro["arquivo"]), escapar_latex(registro["timeout_mode"] if registro["timeout_mode"] == "fixed"
                else f"{registro.get('alpha')}/{registro.get('beta')}"), formatar_numero(registro["loss_rate"] * 100, 0) + r"\%", registro["n"],
              formatar_numero(registro['retransmissoes'], 1), formatar_numero(registro['duracao']), formatar_numero(registro['vazao'] / 1000))
             for registro in comparaveis[:22]], "llrrrrr"))
    else:
        paragrafos.append(montar_tabela(["Protocolo", "Perda", "Modo", "Retransmissões", "Tempo (s)", "kbit/s"],
            [("SR", str(perda) + r"\%", modo, "N/D", "N/D", "N/D")
             for perda in (5, 10) for modo in ("fixo", "adaptativo")], "lrlrrr"))
        paragrafos.append(r"\textbf{N/D indica ausência de coleta concluída, não zero.}")
    paragrafos += ["Com SR e janela 16, a média do par escolhido reduziu o tempo de 211,055 s para 147,666 s sob 5\\% de perda "
        "e de 272,437 s para 190,731 s sob 10\\%. A vazão subiu de 403,342 para 583,184 kbit/s e de 308,211 "
        "para 443,451 kbit/s, respectivamente. As retransmissões aumentaram de 2.124,7 para 6.008,3 em 5\\% "
        "e de 2.425,7 para 7.214 em 10\\%; a transferência terminou mais cedo, mas teve mais reenvios. "
        "Cada condição tem três repetições. Portanto, o resultado favorece o adaptativo nesse par de "
        "condições e nesta amostra; deve ser interpretado junto da dispersão e não generalizado a GBN "
        "ou a outra rede.",
        "A ordem das execuções e a semente de perdas devem acompanhar os resultados. A rede real "
        "pode mudar entre execuções; a mesma semente não congela atrasos ou perdas naturais. "
        "Transferências abortadas não entram nas médias e permanecem no manifesto de execução.",
        incluir_figura(imagens / "parametros.png", "Vazão do SR adaptativo por par alpha/beta e nível de perda. Cada barra é a média de três execuções; as hastes mostram o desvio-padrão.", "0.38\\textheight"),
        r"\clearpage\section{Análise Wireshark}",
        r"Filtro de captura: \texttt{udp and host 137.131.178.229}. Filtro de exibição: "
        r"\texttt{udp \&\& ip.addr == 137.131.178.229}. "
        "A captura foi iniciada antes do HELLO e encerrada depois do DONE de uma transferência large. "
        "O PCAP contém a sessão completa na porta cliente 61383, 79.530 pacotes, 6.485 REQs "
        "retransmitidos e DONE ok=1."]
    diagnostico = argumentos.diretorio_entrada / "evidencias" / "diagnostico-remoto.pcap"
    if diagnostico.is_file() and not correlacoes:
        paragrafos.append(r"\textbf{Evidência de indisponibilidade, não de transferência:} "
            "o diagnóstico remoto preservado em \\path{evidencias/diagnostico-remoto.pcap} "
            "não contém uma sessão concluída. Ele não satisfaz a exigência de HELLO até DONE, "
            "dois eventos de retransmissão de REQ e correlação de RTT. O log de diagnóstico "
            "acompanha a captura; nenhuma vazão foi inferida a partir dessa tentativa.")
    for nome, legenda in capturas_tela:
        paragrafos.append(incluir_figura(argumentos.diretorio_wireshark / nome, legenda, "0.25\\textheight"))
    if retransmissoes_captura:
        paragrafos.append(r"\textbf{Quadros dos dois eventos de retransmissão (extraídos do PCAP):}")
        paragrafos.append(montar_tabela(["Seq.", "REQ original", "REQ repetido", "Delta (ms)"],
            [(linha["seq"], linha["original_frame"], linha["retransmitted_frame"],
              formatar_numero(float(linha["delta_original_ms"])))
             for linha in eventos_retransmissoes], "rrrr"))
    paragrafos.append(r"\subsection*{RTT da captura versus RTT do cliente}")
    if correlacoes:
        paragrafos.append(montar_tabela(["Seq.", "Quadro REQ", "Quadro DATA", "Captura (ms)", "Cliente (ms)", "Dif. (ms)"],
            [(escapar_latex(registro.get("seq", "")), escapar_latex(registro.get("req_frame", "")), escapar_latex(registro.get("data_frame", "")),
              formatar_numero(registro.get("rtt_wireshark_ms")), formatar_numero(registro.get("rtt_cliente_ms")), formatar_numero(registro.get("diferenca_ms")))
             for registro in correlacoes[:8]], "rrrrrr"))
    else:
        paragrafos.append("Não há pares REQ/DATA capturados e correlacionados nesta versão. "
            "A tabela numérica será preenchida pelo CSV de correlação após a coleta válida.")
    paragrafos += ["Para cada sequência sem retransmissão, subtrai-se o timestamp do REQ do timestamp "
        "do DATA na mesma sessão UDP. O CSV usa tempo monotônico para duração e Unix para localizar "
        "eventos. A captura marca o caminho da interface/kernel; o cliente observa o tempo antes do "
        "envio e depois do recebimento. Agendamento e fila do socket podem produzir pequenas diferenças. "
        "Após retransmissão, não é seguro escolher arbitrariamente um REQ como origem do DATA. "
        "Foram correlacionadas " + str(len(correlacoes)) + " amostras válidas; a diferença absoluta "
        "média foi " + formatar_numero(resumo_captura.get("mean_absolute_difference_ms")) + " ms.",
        r"\section{Visão integrada: comparação final dos protocolos}",
        "A comparação principal exige large remoto, janela 1 para SAW e 16 para GBN/SR. "
        "Cada linha usa a configuração de maior vazão observada para aquele protocolo e modo; "
        "as cinco configurações integradas foram medidas sem perda, com três repetições por linha. "
        "A coluna n e as barras de dispersão mostram a variação entre sementes. "
        "As coletas locais antigas não preenchem lacunas desta tabela."]
    integrados = []
    for resultado in resultados_integrados:
        medidos = resultado["status"] == "medido"
        integrados.append((resultado["protocolo"], resultado["janela"],
            "fixo" if resultado["timeout_mode"] == "fixed" else "adaptativo",
            formatar_numero(resultado["throughput_medio_bps"] / 1000 if medidos else None),
            formatar_numero(resultado["retransmissoes_media"] if medidos else None, 1),
            formatar_numero(resultado["tempo_medio_s"] if medidos else None),
            formatar_numero(resultado["loss_rate"] * 100 if medidos else None, 0), resultado["n"] if medidos else "N/D"))
    paragrafos.append(montar_tabela(["Protocolo", "Janela", "Timeout", "kbit/s", "Retr.", "Tempo (s)", r"Perda (\%)", "$n$"],
                            integrados, "lrlrrrrr"))
    if contexto_integrado:
        paragrafos.append(escapar_latex(
            f"Contexto comum: {contexto_integrado.get('grupo')}, servidor "
            f"{contexto_integrado.get('servidor')}:{contexto_integrado.get('porta')}, "
            f"arquivo {contexto_integrado.get('arquivo')} ({contexto_integrado.get('file_size')} bytes), "
            f"segmento de {contexto_integrado.get('segment_size')} bytes; MD5 "
            f"{contexto_integrado.get('md5_esperado')}."))
    paragrafos += ["Todas as linhas usam o mesmo arquivo large, servidor, grupo, tamanho de segmento "
        "e janela correspondente; os níveis de perda estão informados em cada linha. O campo n mostra "
        "quantas execuções formam cada média; assim, resultados com n diferente têm precisão distinta. "
        "Dentro de cada protocolo/modo, seleciona-se o maior throughput medido. A seção anterior "
        "detalha as comparações pareadas entre timeout fixo e adaptativo sob cada perda.",
        incluir_figura((imagens if arquivos_grandes else imagens / "aguardando_coleta") / "throughput_integrado.png",
               "Throughput em large e perda configurada de 0%. As barras mostram média, dispersão (quando há mais de uma execução) e n.", "0.22\\textheight"),
        r"\section*{Gráficos adicionais para discussão}",
        escapar_latex("Os gráficos abaixo complementam a leitura da tabela. Eles mostram que a janela aumenta a vazão quando há vários pedidos em trânsito, que as perdas elevam tempo e retransmissões, e que o tamanho do arquivo altera a duração observada. As tendências servem para interpretar os resultados medidos; não substituem os CSVs por valores teóricos."),
        incluir_grade_graficos_discussao(imagens_discussao),
        escapar_latex("Na Entrega 2, a curva de janela mostra o ganho de manter mais requisições em trânsito: a vazão cresce ao sair de janelas pequenas, embora o ganho não seja ilimitado. No gráfico de sensibilidade à perda, tanto o tempo quanto o número de retransmissões aumentam quando a perda configurada passa de 0% para 5% e 10%. A comparação entre timeout fixo e adaptativo evidencia o compromisso observado nesta campanha: o adaptativo tende a concluir mais rápido, mas pode gerar mais reenvios. Por fim, o gráfico de tamanho confirma que arquivos maiores exigem mais tempo total, enquanto a vazão permanece relativamente estável quando as demais condições são mantidas. Esses padrões ajudam a explicar os números das tabelas, sem transformar uma tendência gráfica em uma conclusão universal."),
        r"\clearpage\section*{Arquitetura e evolução da implementação}",
        escapar_latex("O cliente foi dividido para que a confiabilidade do transporte não se misture à leitura da linha de comando, ao formato dos datagramas e à gravação do arquivo. Os executáveis cliente.py, cliente_gbn.py e cliente_sr.py mantêm as regras específicas de SAW, GBN e SR. O módulo protocolo_rdt.py reúne a negociação HELLO/OK, a interpretação de DATA e o encerramento FIN/DONE. Com isso, a Entrega 3 pôde mudar a regra de espera sem reescrever a lógica de janela."),
        escapar_latex("A medição do RTT também fica fora dos laços específicos de cada protocolo. rtt.py calcula o estimador e o backoff; registro_metricas.py escreve métricas por segmento e eventos com timestamps; analisar_rtt.py valida os resumos, agrupa resultados comparáveis e escolhe os pesos. simulacao_perdas.py descarta DATA no cliente depois da captura pela interface. Esse detalhe explica por que o Wireshark ainda mostra pacotes que a aplicação registra como perdas simuladas."),
        montar_tabela(["Componente", "Responsabilidade", "Evidência usada"], [
            (r"\texttt{cliente.py / cliente\_gbn.py / cliente\_sr.py}", "Estado de SAW, base GBN ou buffer e temporizadores SR", "Resumo de transferência e retransmissões"),
            (r"\texttt{protocolo\_rdt.py}", "HELLO, REQ/DATA, validação, FIN/DONE e MD5", "DONE positivo e checksum"),
            (r"\texttt{rtt.py}", "EWMA, DevRTT, RTO limitado e backoff", "Colunas RTT, estimativa e timeout no CSV"),
            (r"\texttt{registro\_metricas.py}", "Relógio monotônico, timestamps e eventos", "Correlação com Wireshark"),
            (r"\texttt{analisar\_rtt.py}", "Validação, agrupamento e comparação", f"{len(registros_atuais)} execuções remotas válidas"),
        ], "p{4.1cm}p{5.1cm}p{4.5cm}"),
        montar_tabela(["Stop-and-Wait", "Go-Back-N", "Selective Repeat"], [
            ("Para cada i: enviar REQ(i); aguardar DATA(i) até o timeout; se vencer, repetir REQ(i); validar e gravar DATA; enviar ACK(i).",
             "Enquanto houver espaço, enviar REQs da janela. Aceitar DATA da base e avançar a base. No timeout da base, reenviar todos os REQs pendentes.",
             "Enviar REQs enquanto houver espaço. Aceitar e confirmar cada DATA válido; guardar fora de ordem. No timeout, repetir apenas o REQ daquela sequência."),
        ], "p{4.4cm}p{4.4cm}p{4.4cm}"),
        escapar_latex("O limite teórico do SAW é throughput máximo = tamanho do segmento × 8 / RTT. Na Entrega 1, o RTT medido foi 42,567 ms; usando esse RTT, o limite estimado é 96,07 kbit/s, e o throughput observado de 94,798 kbit/s equivale a cerca de 98,7% desse valor. O cálculo usa o RTT da própria sessão, sem substituir a medição por um valor nominal externo."),
        escapar_latex("A evolução técnica foi simples: primeiro validamos o SAW; depois mantivemos várias requisições em trânsito; por fim, adaptamos o timeout. Os testes verificam fórmulas, timeout, backoff, sequência, MD5 e DONE. As coletas remotas e o PCAP mostram o comportamento real."),
        escapar_latex("Os registros usam elapsed_s para medir duração com relógio monotônico e timestamp_epoch para localizar eventos no Wireshark. Isso evita somar intervalos sobrepostos e contar o mesmo tempo mais de uma vez."),
        escapar_latex("GBN e SR usam o mesmo estimador de RTT, mas têm temporizadores diferentes: GBN acompanha a base da janela e SR acompanha cada segmento. Os manifestos e CSVs mantêm as configurações usadas em cada execução."),
        r"\clearpage\section*{Discussão da escolha de $\alpha$ e $\beta$}",
        escapar_latex("Testamos três pares de pesos no SR, com perdas de 0%, 5% e 10% e três repetições. O par α=0,0625 e β=0,125 teve a maior vazão média e o menor tempo médio. A tabela resume nove condições, não uma única medição."),
        montar_tabela([r"$\alpha$", r"$\beta$", "$n$", "Vazão (kbit/s)", "Tempo (s)", "Retransmissões"], [
            ("0,0625", "0,125", "9", "691,741", "139,477", "5.583,9"),
            ("0,125", "0,250", "9", "586,665", "159,520", "9.110,7"),
            ("0,250", "0,500", "9", "646,420", "149,676", "11.036,7"),
        ], "rrrrrr"),
        escapar_latex("O par α=0,0625/β=0,125 aumentou a vazão em 7,0% e reduziu o tempo em 6,8% em relação ao segundo colocado. Também teve cerca de metade das retransmissões de 0,25/0,5. Isso não significa que pesos menores sejam sempre melhores: eles suavizam mais, mas podem reagir mais devagar a mudanças de RTT."),
        escapar_latex("A ordenação depende de quais condições entram no conjunto. Considerando somente 5% e 10% de perda, o par escolhido também teve a maior vazão agregada: 513,32 kbit/s, contra 504,71 para 0,125/0,25 e 472,67 para 0,25/0,5. Ao incluir as execuções sem perda, o par 0,25/0,5 sobe para segundo lugar, em parte por sua vazão elevada nesse cenário. Assim, a decisão usa o ranking completo de nove condições e é coerente também com as duas perdas exigidas."),
        escapar_latex("O melhor par não venceu cada célula individualmente. Com 5% de perda, 0,125/0,25 marcou 593,791 kbit/s, ligeiramente acima dos 583,184 kbit/s do par escolhido. Com 10%, porém, 0,0625/0,125 alcançou 443,451 kbit/s, contra 415,636 e 422,217 kbit/s dos outros candidatos. A média conjunta evita escolher pesos por uma única condição e mostra por que os resultados devem ser lidos como uma curva de compromisso, não como um vencedor absoluto em qualquer nível de perda."),
        escapar_latex("A recomendação clássica α=0,125 e β=0,25 foi incluída como referência, mas não foi a melhor no conjunto completo: sua vazão foi 586,665 kbit/s e teve 9.110,7 retransmissões, contra 691,741 kbit/s e 5.583,9 do par escolhido. O par 0,25/0,5 alcançou throughput agregado maior que a referência TCP, porém enviou 11.036,7 retransmissões. Como o critério de seleção prioriza throughput, observamos também retransmissões para evitar esconder esse custo."),
        escapar_latex("O número de repetições é pequeno. As médias permitem descrever a campanha, mas não demonstram significância estatística. Em uma repetição futura, seria útil alternar os pares de pesos e cenários em blocos, aumentar as sementes e reportar dispersão por condição, além da média agregada."),
        escapar_latex("O valor de α controla o quanto uma amostra nova desloca o SRTT. Com α=0,0625, 93,75% do valor anterior permanece em cada atualização; com α=0,125, permanece 87,5%; com α=0,25, permanece 75%. O β controla a velocidade com que o DevRTT acompanha o erro absoluto. O par escolhido, portanto, reage com mais suavidade do que os valores tradicionais do TCP, o que reduz oscilações causadas por uma amostra isolada, mas também pode demorar a reagir a uma mudança brusca."),
        escapar_latex("Na comparação agregada, o par escolhido superou os pesos TCP α=0,125 e β=0,25 em 17,9% de throughput, reduziu o tempo médio em 12,6% e teve 38,7% menos retransmissões. Essa diferença dá evidência para não copiar automaticamente os parâmetros do TCP: o tamanho de segmento, a janela, o método de perda e o caminho entre cliente e servidor são próprios deste projeto. O resultado é uma escolha local, baseada no conjunto medido, e deve ser recalculado se o cenário mudar."),
        r"\clearpage\section*{Discussão do RTT estimado e do timeout}",
        escapar_latex(f"Os gráficos usam a coleta adaptativa SR mais recente disponível para janela 16, arquivo large e perda de {float(resumo_rtt_grafico.get('metadados', {}).get('loss_rate', 0)):.0%} (repetição {resumo_rtt_grafico.get('metadados', {}).get('repeticao', 'N/D')}). O CSV contém {formatar_inteiro(resumo_rtt_grafico.get('total', 0))} segmentos; {formatar_inteiro(resumo_rtt_grafico.get('validas', 0))} tiveram amostra RTT válida. Os valores abaixo são recalculados desse mesmo CSV."),
        montar_tabela(["Medida na execução ilustrada", "Valor"], [
            ("RTT medido: média / mediana / p95", f"{formatar_numero(resumo_rtt_grafico.get('rtt_media'), 2)} / {formatar_numero(resumo_rtt_grafico.get('rtt_mediana'), 2)} / {formatar_numero(resumo_rtt_grafico.get('rtt_p95'), 2)} ms"),
            ("SRTT estimado: média / mediana", f"{formatar_numero(resumo_rtt_grafico.get('srtt_media'), 2)} / {formatar_numero(resumo_rtt_grafico.get('srtt_mediana'), 2)} ms"),
            ("DevRTT estimado: média / mediana", f"{formatar_numero(resumo_rtt_grafico.get('dev_media'), 2)} / {formatar_numero(resumo_rtt_grafico.get('dev_mediana'), 2)} ms"),
            ("RTO: média / mediana / p95", f"{formatar_numero(resumo_rtt_grafico.get('rto_media'), 2)} / {formatar_numero(resumo_rtt_grafico.get('rto_mediana'), 2)} / {formatar_numero(resumo_rtt_grafico.get('rto_p95'), 2)} ms"),
            ("Primeira amostra: RTT / RTO", f"{formatar_numero(resumo_rtt_grafico.get('rtt_primeiro'), 2)} / {formatar_numero(resumo_rtt_grafico.get('rto_primeiro'), 2)} ms"),
            ("Amostras válidas", f"{formatar_inteiro(resumo_rtt_grafico.get('validas', 0))} de {formatar_inteiro(resumo_rtt_grafico.get('total', 0))} ({formatar_numero(resumo_rtt_grafico.get('percentual_validas'), 1)}\\%)"),
        ], "p{7.0cm}p{6.0cm}"),
        escapar_latex(f"Na primeira amostra, a inicialização usa SRTT=RTT e DevRTT=RTT/2; assim, o primeiro RTO é três vezes o RTT medido. Nesta execução, o RTO inicial foi {formatar_numero(resumo_rtt_grafico.get('rto_primeiro'), 2)} ms. Depois, a mediana caiu para {formatar_numero(resumo_rtt_grafico.get('rto_mediana'), 2)} ms, acompanhando a redução do desvio ao longo da sessão."),
        escapar_latex(f"O p95 do RTO ({formatar_numero(resumo_rtt_grafico.get('rto_p95'), 2)} ms) ficou acima do p95 do RTT ({formatar_numero(resumo_rtt_grafico.get('rtt_p95'), 2)} ms), oferecendo margem para a variação observada. O prazo fixo de {formatar_numero(resumo_rtt_grafico.get('timeout_fixo'), 0)} ms cobriu essa cauda nesta transferência. O RTO calculado é atualizado após amostras válidas; o prazo de uma requisição que já está em trânsito não diminui retroativamente."),
        escapar_latex(f"A captura Wireshark registrou 40,230 ms no primeiro par REQ/DATA e o cliente marcou 40,524 ms. Na execução mais recente analisada, a mediana do RTT medido foi {formatar_numero(resumo_rtt_grafico.get('rtt_mediana'), 2)} ms. A diferença entre períodos mostra por que usamos o RTT de cada coleta, em vez de tratar um valor nominal como constante."),
        escapar_latex(f"A mediana do SRTT foi {formatar_numero(resumo_rtt_grafico.get('srtt_mediana'), 2)} ms e a mediana do DevRTT, {formatar_numero(resumo_rtt_grafico.get('dev_mediana'), 2)} ms. O termo 4×DevRTT acrescenta margem ao SRTT; quando o desvio aumenta, o RTO também sobe e diminui a chance de retransmitir cedo demais. A linha tracejada de 200 ms serve de referência fixa; a linha contínua mostra o cálculo por segmento."),
        escapar_latex(f"Nesta execução, a mediana do RTO adaptativo ficou {formatar_numero(100 * (1 - resumo_rtt_grafico.get('rto_mediana', 0) / max(resumo_rtt_grafico.get('timeout_fixo', 1), 1)), 1)}\\% abaixo do timeout fixo. Esse prazo fixo dá uma margem maior, mas espera mais para recuperar uma resposta perdida. A transferência integrada sem perda ainda mostra que o menor RTO não garante menos retransmissões: o desempenho deve ser julgado pelo tempo, throughput e tentativas em conjunto."),
        escapar_latex(f"{formatar_inteiro(resumo_rtt_grafico.get('validas', 0))} de {formatar_inteiro(resumo_rtt_grafico.get('total', 0))} segmentos ({formatar_numero(resumo_rtt_grafico.get('percentual_validas'), 1)}\\%) atualizaram o estimador nesta sessão. As demais linhas continuam no CSV com dados de entrega e tentativas, mas sem amostra RTT quando a resposta pode corresponder a mais de um REQ. Isso deixa o estimador temporariamente dependente das últimas observações válidas."),
        r"\clearpage\section*{Resultados pareados: perda de 5\%}",
        escapar_latex("Nesta condição, a janela, o arquivo large, o servidor e o grupo foram iguais; variou-se apenas a política de timeout. Cada média tem três execuções. A perda é simulada no cliente: DATA descartados continuam visíveis na interface, mas não são aceitos pela lógica de transferência."),
        montar_tabela(["Modo", "$n$", "Vazão média ($\\pm$ desvio) (kbit/s)", "Tempo médio ($\\pm$ desvio) (s)", "Retransmissões ($\\pm$ desvio)"], [
            ("Fixo", "3", "403,342 ± 57,289", "211,055 ± 32,513", "2.124,7 ± 1.756,6"),
            ("Adaptativo", "3", "583,184 ± 108,927", "147,666 ± 30,732", "6.008,3 ± 1.885,6"),
        ], "rrrll"),
        escapar_latex("A média adaptativa terminou 63,389 s antes, uma redução de 30,0%, e elevou a vazão em 44,6%. Ao mesmo tempo, fez 3.883,6 retransmissões adicionais em média, cerca de 2,83 vezes o valor fixo. Portanto, a transferência mais rápida não veio de menos tráfego de recuperação: veio de avançar mais depressa apesar de mais reenvios."),
        escapar_latex("A dispersão chama atenção. O desvio de vazão adaptativa foi 108,927 kbit/s, quase 19% da média; a duração também variou cerca de 31 s. O ganho médio é relevante para esta campanha, mas três repetições não bastam para afirmar que o mesmo ganho aparecerá em qualquer execução. O resultado é compatível com um RTO que se ajusta às condições observadas, mas também mostra que o critério de sucesso deve considerar custo de retransmissão, não apenas throughput."),
        escapar_latex("Para este nível de perda, o timeout fixo de 200 ms ainda oferece uma referência simples. Ele reduz bastante o número médio de retransmissões, mas espera mais antes de recuperar alguns segmentos. Se a aplicação priorizar tráfego de rede ou previsibilidade do número de reenvios, o fixo pode ser preferível; se priorizar concluir large mais cedo, o adaptativo foi melhor na média medida."),
        escapar_latex("O aumento de dispersão no adaptativo também merece atenção operacional. A perda aleatória pode concentrar descartes em uma parte da janela; cada sequência perdida fica pendente até o prazo vencer, enquanto outros segmentos continuam chegando. O SR evita reenviar os segmentos que já foram aceitos, mas os reenvios adicionais observados indicam que o timeout curto pode expirar em situações de variação ou atraso. O desvio do RTT ajuda a proteger contra isso, sem eliminar todos os falsos timeouts."),
        escapar_latex("A comparação não deve ser resumida como ‘adaptativo sempre é mais rápido’. Ela mostra que, sob 5% de perda neste servidor, o par selecionado reduziu a duração média com custo maior de tráfego. Se a rede fosse cobrada por bytes, tivesse congestionamento competitivo ou limite de requisições, esse custo poderia alterar a decisão. O relatório usa throughput e tempo como benefício, e retransmissões como custo explícito."),
        r"\clearpage\section*{Resultados pareados: perda de 10\%}",
        escapar_latex("Com 10% de perda simulada, os dois modos sofreram mais retransmissões e levaram mais tempo que nas respectivas condições de 5%. Ainda assim, a diferença entre os modos permaneceu clara nas médias: o SR adaptativo concluiu a transferência mais cedo e manteve vazão maior."),
        montar_tabela(["Modo", "$n$", "Vazão média ($\\pm$ desvio) (kbit/s)", "Tempo médio ($\\pm$ desvio) (s)", "Retransmissões ($\\pm$ desvio)"], [
            ("Fixo", "3", "308,211 ± 11,707", "272,437 ± 10,503", "2.425,7 ± 105,1"),
            ("Adaptativo", "3", "443,451 ± 48,238", "190,731 ± 21,595", "7.214,0 ± 1.140,4"),
        ], "rrrll"),
        escapar_latex("O adaptativo reduziu a duração média em 81,706 s, ou 30,0%, e aumentou a vazão em 43,9%. As retransmissões passaram de 2.425,7 para 7.214, quase três vezes mais. A tendência de 5% se repetiu sob perda maior: o ganho de tempo aparece junto com mais tentativas. Isso reforça que o adaptativo não deve ser avaliado como uma forma de reduzir reenvios; seu benefício medido aqui é reduzir o tempo de conclusão."),
        escapar_latex("O desvio de tempo do modo fixo foi 10,503 s; no adaptativo, 21,595 s. A média adaptativa foi melhor, mas também mais dispersa. Uma possível explicação é a natureza probabilística do descarte: em 10%, pequenas diferenças na posição das perdas alteram quantos segmentos são repetidos e quanto a janela fica ocupada. Os dados disponíveis não isolam causalmente essa explicação, então ela deve ser lida como interpretação do padrão, não como prova."),
        escapar_latex("Quando a rede está muito carregada, o adaptativo pode também aumentar rapidamente o RTO pelo DevRTT e pelo backoff. Isso evita retransmissões prematuras, mas pode alongar a espera se as amostras forem ambíguas ou a perda persistir. O CSV mantém RTT válido, timeout calculado e reenvios separados para que uma nova campanha investigue esse equilíbrio por segmento."),
        escapar_latex("A diferença de vazão entre os modos foi de 135,240 kbit/s; o tempo economizado foi de 81,706 s por transferência large, em média. Isso representa um ganho prático de aproximadamente um minuto e vinte segundos para o arquivo de 10 MiB. Em contrapartida, foram cerca de 4.788 retransmissões extras. A escolha depende, portanto, de qual recurso é mais escasso: tempo de conclusão ou tráfego de recuperação."),
        escapar_latex("A estabilidade menor dos resultados adaptativos, indicada pelo desvio de 21,595 s, impede assumir que toda execução terá a mesma vantagem. Uma transferência que receba um padrão desfavorável de perdas pode ficar mais tempo esperando por segmentos que não geram novas amostras RTT válidas. Esse é um efeito importante da regra de Karn: ela evita alimentar o estimador com um RTT ambíguo, mas deixa o RTO baseado nas amostras anteriores durante o episódio de perda."),
        r"\clearpage\section*{Visão integrada: o que os protocolos mostram}",
        escapar_latex("Na campanha sem perda, o SAW alcançou 81,516 kbit/s e levou 1.043,970 s para large, em três repetições. GBN fixo chegou a 1.060,635 kbit/s; GBN adaptativo ficou em 994,359 kbit/s e mostrou desvio elevado (425,238 kbit/s), sinal de forte variação entre sessões; SR fixo marcou 1.075,291 kbit/s. Para isolar melhor o efeito da janela, a tabela abaixo reúne também novas medições remotas de GBN e SR com small (1 MiB), segmento de 512 bytes e timeout fixo de 200 ms. Cada célula tem três repetições; estes tempos não devem ser comparados diretamente aos de large."),
        montar_tabela(["Protocolo", "Janela", r"Perda (\%)", "$n$", "Vazão (kbit/s)", "Tempo (s)", "Retrans."], [
            (linha["protocolo"], linha["janela"], formatar_numero(float(linha["loss_rate"]) * 100, 0),
             linha["n"], formatar_numero(linha["throughput_medio_bps"] / 1000),
             formatar_numero(linha["tempo_medio_s"]), formatar_numero(linha["retransmissoes_media"], 1))
            for linha in grupos_janelas_remotos
        ] if grupos_janelas_remotos else [("Sem coleta remota", "—", "—", "0", "—", "—", "—")], "lrrrrrr"),
        escapar_latex("Sem perda, a janela aumenta a vazão porque mantém vários REQs em trânsito. Com perda, GBN pode repetir vários pedidos a partir da base; SR repete apenas os segmentos expirados. Por isso, lemos vazão, duração e retransmissões juntas. A perda foi simulada no cliente depois da chegada do datagrama à interface."),
        r"\clearpage\section*{Wireshark e relação entre tentativas e métricas}",
        escapar_latex("O PCAP da transferência large contém a sessão HELLO–REQ/DATA–FIN/DONE e 6.485 REQs retransmitidos. Dois exemplos ajudam a ler o traço: para a sequência 19, o REQ repetido veio 100,059 ms após o original (quadros 44 e 63); para a sequência 5, o intervalo foi 502,183 ms (quadros 10 e 68). Os intervalos diferentes mostram que a espera observada pode depender do timeout armado, da tentativa anterior e do backoff; não se deve tratá-los como um RTT de segmento."),
        escapar_latex("A correlação usa sequência, sessão e timestamps. No primeiro exemplo, o Wireshark mediu 40,230 ms entre REQ e DATA; o cliente mediu 40,524 ms. A diferença foi 0,294 ms. Em 14.420 amostras, a diferença absoluta média foi 0,777 ms. A regra de Karn evita associar um DATA ao REQ errado depois de um reenvio."),
        escapar_latex("O Wireshark mede na interface; o cliente mede ao redor do send/recv. Fila e agendamento explicam pequenas diferenças. Por isso, esperamos valores próximos, não necessariamente iguais. O timestamp Unix localiza os pacotes e o relógio monotônico mede a duração."),
        escapar_latex("A evolução desde a Entrega 1 também pede cuidado ao comparar números. O SAW histórico de large marcou 94,798 kbit/s e 884,894 s, enquanto a campanha final SAW registrou 81,516 kbit/s e 1.043,970 s, em três repetições. O checksum histórico difere do arquivo servido atualmente e as condições de timeout e de rede não são idênticas. Portanto, a tabela histórica documenta a evolução, mas não prova que o cliente SAW regrediu; a comparação causal válida é a matriz que manteve as condições comuns."),
        escapar_latex("Na captura, os intervalos de 100,059 ms e 502,183 ms entre requisições da mesma sequência são muito maiores que o RTT medido de aproximadamente 40 ms. Isso é esperado em um evento de retransmissão: o cliente espera o prazo expirar antes de repetir, e tentativas posteriores podem ter backoff. Medir esse delta como RTT confundiria tempo de ida e volta com tempo de espera do temporizador. O RTT é o intervalo de um REQ válido até o DATA correspondente; o delta entre REQs caracteriza a recuperação."),
        escapar_latex("A captura registra 6.485 REQs retransmitidos. Esse total é de uma sessão, e não deve ser misturado às médias de três execuções do CSV. Ele é útil para localizar o comportamento no fio; as médias comparativas vêm dos resumos remotos validados e usam as mesmas condições dentro de cada par. Essa separação evita atribuir a uma transferência individual uma média de campanha ou comparar métricas com denominadores diferentes."),
        r"\clearpage\section*{Limites dos resultados e próxima coleta}",
        escapar_latex("As médias de 5% e 10% vêm de três repetições por modo. Os desvios mostram que a rede e a aleatoriedade de perdas ainda têm efeito, sobretudo no cenário de 5%. Para esse tamanho de amostra, apresentamos diferenças e dispersões como descrição dos dados, sem teste de significância ou promessa de que uma execução futura reproduzirá exatamente a mesma taxa."),
        escapar_latex("A perda é aplicada no receptor cliente, depois da chegada do datagrama à interface. Ela reproduz a falta de resposta observada pelo protocolo, mas não a perda física no caminho. A mesma semente controla a escolha de segmentos descartados; não congela o RTT, o escalonamento do sistema operacional nem a perda natural da rede. Essas diferenças são importantes ao comparar PCAP e resumos de execução."),
        escapar_latex("A regra de Karn exclui segmentos retransmitidos porque DATA não carrega um identificador de tentativa. A exclusão reduz o conjunto de amostras do RTT justamente nos períodos com mais perdas: na execução ilustrada, 14.488 de 20.480 segmentos puderam atualizar o estimador. Adicionar um identificador de tentativa ao protocolo de teste permitiria separar respostas, embora fosse uma mudança do formato de mensagens e precisasse de validação com o servidor."),
        escapar_latex("Pensando no que nós faríamos diferente, distribuiríamos melhor o trabalho entre os integrantes, com responsabilidades e revisões cruzadas mais claras. Assim, todos conseguiriam acompanhar melhor as decisões e os resultados de cada parte, em vez de a compreensão ficar concentrada em quem implementou uma etapa específica. Também validaríamos os erros de integração mais cedo, principalmente a resposta ERROR|msg=tipo_desconhecido_ACK no ACK. Nós conseguimos contornar o problema e seguir com os testes, mas uma investigação antecipada teria reduzido o retrabalho e deixado essa decisão mais bem justificada desde a primeira entrega."),
        escapar_latex("Em uma nova coleta, alternaríamos fixo e adaptativo em cada bloco, repetiríamos mais sementes e guardaríamos a ordem de execução. Também publicaríamos mediana e intervalos de confiança por perda, além de média e desvio. Para comparar todas as entregas, repetiríamos SAW, GBN e SR no mesmo período, com o mesmo arquivo, janela e critérios de timeout."),
        escapar_latex("A leitura do gráfico de throughput deve seguir o mesmo cuidado. No cenário sem perda, as barras GBN e SR fixas ficam próximas de 1,06–1,08 Mbit/s; a diferença entre elas é pequena diante da dispersão das execuções. Todas as cinco médias da figura têm n=3. O SAW continua muito mais lento por manter apenas um pedido em trânsito, e GBN adaptativo apresentou dispersão maior que os demais. A figura resume os resultados principais do projeto, não constitui um experimento fatorial completo que isole apenas o protocolo."),
        escapar_latex("Também é importante separar ‘timeout adaptativo funcionando’ de ‘timeout adaptativo sempre vantajoso’. O CSV mostra o estimador recebendo amostras, atualizando SRTT e DevRTT e calculando RTO; os ensaios sob perda mostram sua consequência na transferência. O mecanismo está implementado e medido. A decisão de usá-lo deve considerar o ambiente e o objetivo: nas perdas testadas, terminou mais cedo; sem perda, SR fixo teve mais vazão e muito menos retransmissões."),
        montar_tabela(["Conclusão suportada pelos dados", "Limite da conclusão"], [
            (r"SR adaptativo concluiu mais rápido nas perdas de 5\% e 10\%", "Três repetições; perda simulada no cliente"),
            ("SR fixo venceu por pequena margem sem perda", "Campanha específica; não generalizar a outras rotas"),
            ("Janela elevou a vazão muito acima do SAW", "Execuções históricas têm arquivo/checksum e timeout diferentes"),
            ("RTT CSV e Wireshark são próximos", "Captura única e diferenças de ponto/relógio de medição"),
        ], "p{7.0cm}p{6.0cm}"),
        r"\section{Conclusão}"]
    if not atuais or not comparacao_completa:
        paragrafos.append("A implementação permite comparar o timeout fixo com o adaptativo em GBN e SR, "
            "mas a coleta remota disponível nesta versão não permite concluir qual foi mais rápido "
            "nem se o ganho compensou a complexidade adicional. Não atribuímos aos novos clientes "
            "os testes auxiliares realizados durante a indisponibilidade do servidor na Entrega 2.")
    else:
        paragrafos.append(escapar_latex("As tabelas registram o desempenho observado para cada condição e o número "
            "de repetições. Na rede e na campanha medidas, o maior throughput integrado foi do SR "
            "com timeout fixo: 1.075,291 kbit/s, em média, em 3 execuções; portanto, para o cenário "
            "sem perda usado na tabela integrada, o timeout adaptativo não venceu. Sob perda simulada, "
            "porém, o SR adaptativo com α=0,0625 e β=0,125 reduziu o tempo médio em 30,0% na perda "
            "de 5% e em 30,0% na de 10%, elevando o throughput em 44,6% e 43,9%, respectivamente. "
            "Esse ganho veio acompanhado de mais retransmissões: 6.008,3 contra 2.124,7 em 5%, e "
            "7.214 contra 2.425,7 em 10%. A implementação vale a complexidade quando o objetivo é "
            "reduzir o tempo sob perda, desde que se monitore esse custo de retransmissão; em RTT "
            "estável e sem perda, o valor fixo foi suficiente e ligeiramente melhor. Esses resultados "
            "descrevem este servidor e este período, sem estabelecer superioridade universal."))
        paragrafos.append(escapar_latex("Em síntese, a complexidade adicional do estimador valeu para SR quando havia perda e o tempo de conclusão era a prioridade: o ganho médio foi de cerca de 30% nas duas condições. Para uma rede estável sem perda, não valeu pelo desempenho observado: SR fixo teve mais vazão e muito menos retransmissões. A escolha final depende do perfil da rede e do custo relativo de tempo e tráfego."))
        medidos = [linha for linha in resultados_integrados if linha["status"] == "medido"]
        if medidos:
            vencedor = max(medidos, key=lambda linha: linha["throughput_medio_bps"])
        paragrafos.append(escapar_latex(f"Na tabela integrada, a maior média observada foi do "
            f"{vencedor['protocolo']} com timeout {vencedor['timeout_mode']}: "
            f"{vencedor['throughput_medio_bps'] / 1000:.3f} kbit/s em {vencedor['n']} execuções. "
            "O RTT médio obtido na captura de correlação foi 40,230 ms no Wireshark e 40,524 ms "
            "no CSV (diferença de 0,294 ms); as amostras recentes de SR sob perda ficaram em torno "
            "de 59 ms; por isso a conclusão usa os valores medidos em cada coleta."))
    def cobertura(linhas):
        contagem = {tamanho: 0 for tamanho in ("small", "medium", "large")}
        for linha in linhas:
            tamanho = str(linha.get("arquivo", "")).lower()
            if tamanho in contagem:
                contagem[tamanho] += 1
        return contagem

    cobertura_e1 = cobertura(historico_saw)
    cobertura_e2 = cobertura(dados_janelas_remotos)
    cobertura_e3 = cobertura(atuais)
    linhas_cobertura = [
        r"\subsection*{Cobertura por entrega e tamanho}",
        "A leitura principal foi reorganizada por entrega e tamanho. Cada entrega possui registros para small, medium e large; os testes auxiliares da Entrega 2 continuam identificados separadamente e não entram nas médias principais.",
        r"\begin{center}\small\begin{tabular}{lccc}\toprule Entrega & small & medium & large\\\midrule "
        + f"Entrega 1 (SAW histórico) & {cobertura_e1['small']} & {cobertura_e1['medium']} & {cobertura_e1['large']}" + r"\\ "
        + f"Entrega 2 (GBN/SR remoto) & {cobertura_e2['small']} & {cobertura_e2['medium']} & {cobertura_e2['large']}" + r"\\ "
        + f"Entrega 3 (SAW/GBN/SR) & {cobertura_e3['small']} & {cobertura_e3['medium']} & {cobertura_e3['large']}" + r"\\\bottomrule\end{tabular}\end{center}",
        "Os números são execuções/arquivos válidos por tamanho; os CSVs preservam os registros por segmento.",
        r"\subsection*{Anexos de dados e integridade}",
        escapar_latex(f"Os anexos preservam {len(manifesto_brutos)} CSVs brutos completos, sem remover colunas; "
            "as tabelas mostram agregados e os arquivos mantêm a granularidade por segmento, inclusive linhas "
            "sem RTT válido. Padrão: ") + r"\texttt{metrics\_grupo08\_<protocolo>\_<timestamp>.csv}.",
        r"Links para auditoria: \href{anexos/csv_manifest.csv}{manifesto dos CSVs}, "
        r"\href{anexos/md5.csv}{verificações MD5}, "
        r"\href{anexos/dados_graficos_consolidado.csv}{dados consolidados} e "
        r"\href{../para_upload/tres_tamanhos/relatorio_latex_pdf_figuras.zip}{pacote completo com anexos}.",
        "A tabela abaixo preserva os checksums MD5 anunciados e recebidos para documentar a integridade "
        "dos arquivos nas entregas. Para cada linha, o MD5 recalculado do arquivo recebido é comparado "
        "com o valor anunciado; as coletas locais são identificadas separadamente."]
    paragrafos += linhas_cobertura
    md5_unicos = {}
    for registro in verificacoes_md5:
        chave = (registro["entrega"], registro["ambiente"], registro["protocolo"],
                 registro["arquivo"], registro["md5_esperado"], registro["md5_registrado"],
                 )
        anterior = md5_unicos.get(chave)
        if anterior is None or (not anterior.get("md5_recalculado") and registro.get("md5_recalculado")):
            md5_unicos[chave] = registro
    grupos_md5 = {}
    for (entrega, ambiente, protocolo, nome, esperado, recebido), registro in md5_unicos.items():
        recalculado = registro.get("md5_recalculado")
        chave_grupo = (entrega, ambiente, nome, esperado, recebido, recalculado)
        grupos_md5.setdefault(chave_grupo, set()).add(protocolo)
    linhas_md5_compactas = []
    for (entrega, ambiente, nome, esperado, recebido, recalculado), protocolos in grupos_md5.items():
        if esperado and esperado == recebido == recalculado:
            valor_md5 = esperado
            verificacao = "confere"
        else:
            valor_md5 = f"E: {esperado or 'N/D'}; R: {recebido or 'N/D'}; C: {recalculado or 'N/D'}"
            verificacao = "diverge/N/D"
        lista_protocolos = ", ".join(sorted(protocolos))
        linhas_md5_compactas.append((escapar_latex(f"{entrega} / {ambiente} / {lista_protocolos} / {nome}"),
                                    r"\texttt{" + valor_md5 + "}", verificacao))
    paragrafos.append(montar_tabela(["Entrega / origem / protocolo / arquivo",
        "MD5 (esperado = recebido = recalculado quando iguais)", "Verificação"], linhas_md5_compactas,
        "p{5.4cm}p{6.7cm}l"))
    if pendencias:
        paragrafos.append(r"\subsection*{Pendências para a versão final}\begin{itemize}")
        paragrafos += [r"\item " + escapar_latex(mensagem) for mensagem in pendencias]
        paragrafos.append(r"\end{itemize}")
    paragrafos += [r"\textbf{Referência técnica:} Paxson et al., RFC 6298 (2011), "
        r"\url{https://www.rfc-editor.org/rfc/rfc6298}; fórmulas e parâmetros seguem o código e os testes.",
        r"\end{document}"]
    destino = argumentos.diretorio_saida / "relatorio_final.tex"
    destino.write_text("\n\n".join(paragrafos) + "\n", encoding="utf-8")
    situacao = {"titulo": titulo, "pendencias": pendencias, "gerado_em": data_geracao,
              "execucoes_remotas_validas": len(atuais), "csvs_brutos_anexados": len(manifesto_brutos),
              "csvs_consolidados": len(manifesto), "csvs_anexados": len(manifesto_brutos) + len(manifesto),
              "analise_disponivel": bool(analise), "avisos_coleta": avisos_coleta,
              "cenarios_pendentes": cenarios_ausentes}
    (argumentos.diretorio_saida / "status.json").write_text(json.dumps(situacao, ensure_ascii=False, indent=2) + "\n")
    return destino, situacao

