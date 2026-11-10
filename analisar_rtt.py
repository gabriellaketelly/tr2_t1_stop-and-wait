"""Consolida somente coletas remotas válidas da Entrega 3, sem inventar dados.

Médias são de transferências completas. Gráficos de convergência usam a ordem
de chegada de DATA, importante no SR, cuja gravação em disco é ordenada.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

from validacao_metricas import validar_csv_metricas
from graficos_rtt import gerar_graficos


SERVIDOR_REMOTO = "137.131.178.229"
ARQUIVOS_OBRIGATORIOS = ("small", "medium", "large")
CAMPOS_CONTEXTO = ("servidor", "porta", "grupo", "arquivo", "file_size",
                  "segment_size", "md5_esperado")
CAMPOS_EXECUCAO = ("contexto_id", *CAMPOS_CONTEXTO, "protocolo", "janela", "timeout_mode",
                 "alpha", "beta", "loss_rate", "timeout_s", "rto_min_s", "rto_max_s",
                 "repeticao", "loss_seed", "throughput_medido_bps", "retransmissoes",
                 "duracao_s", "rtt_medio_s", "amostras_rtt", "simulated_loss_total",
                 "md5_recebido", "checksum_ok", "done_ok", "historico", "coleta_inicio_utc",
                 "resumo_path", "metricas_path")
CAMPOS_AGRUPAMENTO = ("contexto_id", "protocolo", "janela", "timeout_mode", "alpha", "beta",
                "loss_rate", "timeout_s", "rto_min_s", "rto_max_s", "historico")
CAMPOS_COMPARATIVO = (*CAMPOS_AGRUPAMENTO, "n", "throughput_medio_bps", "throughput_desvio_bps",
              "retransmissoes_media", "retransmissoes_desvio", "tempo_medio_s",
              "tempo_desvio_s", "rtt_medio_s", "execucoes")
CAMPOS_INTEGRADOS = ("protocolo", "janela", "timeout_mode", "contexto_id", "loss_rate",
                     "timeout_s", "alpha", "beta", "n", "throughput_medio_bps",
                     "throughput_desvio_bps", "retransmissoes_media", "tempo_medio_s",
                     "historico", "status", "execucoes")
CONFIGURACOES_OBRIGATORIAS = (("SAW", "fixed"), ("GBN", "fixed"), ("GBN", "adaptive"),
            ("SR", "fixed"), ("SR", "adaptive"))


def positivo_finito(valor) -> bool:
    return isinstance(valor, (int, float)) and math.isfinite(valor) and valor > 0


def localizar_manifestos(raiz: Path) -> list[Path]:
    """Inclui campanhas complementares sem depender de consolidação manual."""
    return sorted(raiz.rglob("manifesto.json")) if raiz.is_dir() else []


def localizar_fontes_coleta(raiz: Path):
    manifestos = localizar_manifestos(raiz)
    pastas_manifestos = {caminho.parent for caminho in manifestos}
    # Um resumo sob um manifesto só pode entrar por uma execução concluída.
    avulsos = [caminho for caminho in sorted(raiz.rglob("resumo.json"))
               if not any(pasta in pastas_manifestos for pasta in caminho.parents)]
    return manifestos, avulsos


def coletar_resultados(pastas: list[Path], pastas_historicas: list[Path] | None = None):
    registros, avisos, encontrados = [], [], set()
    for raiz, historico in [(pasta, False) for pasta in pastas] + [(pasta, True) for pasta in pastas_historicas or []]:
        if not raiz.exists():
            avisos.append(f"Pasta de coleta ausente: {raiz}")
            continue
        manifestos, candidatos = localizar_fontes_coleta(raiz)
        for caminho_manifesto in manifestos:
            try:
                manifesto = json.loads(caminho_manifesto.read_text(encoding="utf-8"))
                concluidos = {}
                for registro in manifesto.get("runs", []):
                    if registro.get("status") == "success" and registro.get("summary"):
                        concluidos[registro["id"]] = caminho_manifesto.parent / registro["summary"]
                    elif registro.get("status") not in ("success",):
                        avisos.append(f"Execução excluída ({registro.get('status')}): {registro.get('id')}")
                candidatos.extend(concluidos.values())
                for registro in manifesto.get("preflights", []):
                    if registro.get("status") == "failed":
                        avisos.append(f"Diagnóstico remoto falhou em {registro.get('started_utc')}: {registro.get('error')}")
            except (OSError, ValueError, KeyError) as erro:
                avisos.append(f"Manifesto inválido em {caminho_manifesto}: {erro}")
                continue
        for caminho in candidatos:
            if caminho.resolve() in encontrados:
                continue
            encontrados.add(caminho.resolve())
            try:
                resumo = json.loads(caminho.read_text(encoding="utf-8"))
                if resumo.get("servidor") != SERVIDOR_REMOTO:
                    avisos.append(f"Coleta não remota excluída: {caminho}")
                    continue
                if resumo.get("checksum_ok") is not True or resumo.get("done_ok") is not True:
                    avisos.append(f"Integridade não confirmada, excluído: {caminho}")
                    continue
                if (not positivo_finito(resumo.get("duracao_s"))
                        or not positivo_finito(resumo.get("throughput_medido_bps"))):
                    avisos.append(f"Métricas incompletas ou inválidas, excluído: {caminho}")
                    continue
                retrans = resumo.get("retransmissoes")
                if (not isinstance(retrans, (int, float)) or not math.isfinite(retrans)
                        or retrans < 0 or int(retrans) != retrans):
                    avisos.append(f"Contagem de retransmissões inválida, excluído: {caminho}")
                    continue
                if (not resumo.get("md5_esperado")
                        or resumo.get("md5_esperado") != resumo.get("md5_recebido")):
                    avisos.append(f"Checksum inconsistente, excluído: {caminho}")
                    continue
                caminho_csv = caminho.parent / "metricas.csv"
                if not caminho_csv.is_file():
                    avisos.append(f"CSV ausente, excluído: {caminho}")
                    continue
                validar_csv_metricas(caminho_csv, resumo)
                protocolo = resumo.get("protocolo", "SAW").upper()
                modo = resumo.get("timeout_mode", "fixed")
                if protocolo not in ("SAW", "GBN", "SR") or modo not in ("fixed", "adaptive"):
                    avisos.append(f"Protocolo/modo desconhecido, excluído: {caminho}")
                    continue
                if modo == "adaptive" and not all(positivo_finito(resumo.get(chave))
                        and resumo[chave] <= 1 for chave in ("alpha", "beta")):
                    avisos.append(f"Parâmetros adaptativos inválidos, excluído: {caminho}")
                    continue
                registro = {campo: resumo.get(campo) for campo in CAMPOS_EXECUCAO}
                registro.update(protocolo=protocolo, timeout_mode=modo,
                              janela=resumo.get("janela", 1 if protocolo == "SAW" else None),
                              loss_rate=resumo.get("loss_rate", 0.0), historico=historico,
                              resumo_path=str(caminho.resolve()), metricas_path=str(caminho_csv.resolve()))
                if modo == "fixed":
                    registro["alpha"] = registro["beta"] = None
                    # Limites do estimador não afetam execução com timeout fixo.
                    registro["rto_min_s"] = registro["rto_max_s"] = None
                contexto = {campo: registro[campo] for campo in CAMPOS_CONTEXTO}
                registro["contexto_id"] = hashlib.sha256(json.dumps(contexto, sort_keys=True).encode()).hexdigest()[:12]
                registros.append(registro)
            except (OSError, ValueError, KeyError, TypeError) as erro:
                avisos.append(f"Resumo ilegível em {caminho}: {erro}")
    if not registros:
        avisos.append("Nenhuma transferência remota completa e válida disponível; tabelas e gráficos não contêm resultados medidos.")
    return registros, avisos


def agrupar_resultados(registros: list[dict]) -> list[dict]:
    grupos = defaultdict(list)
    for registro in registros:
        grupos[tuple(registro[campo] for campo in CAMPOS_AGRUPAMENTO)].append(registro)
    linhas = []
    for chave, execucoes in sorted(grupos.items(), key=lambda item: str(item[0])):
        linha = dict(zip(CAMPOS_AGRUPAMENTO, chave))
        linha.update(n=len(execucoes), historico=any(registro["historico"] for registro in execucoes),
                   execucoes=[registro["resumo_path"] for registro in execucoes])
        for origem, media, desvio in (
                ("throughput_medido_bps", "throughput_medio_bps", "throughput_desvio_bps"),
                ("retransmissoes", "retransmissoes_media", "retransmissoes_desvio"),
                ("duracao_s", "tempo_medio_s", "tempo_desvio_s")):
            valores = [float(registro[origem]) for registro in execucoes]
            linha[media] = statistics.mean(valores)
            linha[desvio] = statistics.stdev(valores) if len(valores) > 1 else None
        rtts = [registro["rtt_medio_s"] for registro in execucoes if positivo_finito(registro["rtt_medio_s"])]
        linha["rtt_medio_s"] = statistics.mean(rtts) if rtts else None
        linhas.append(linha)
    return linhas


def listar_cenarios_planejados(pastas: list[Path]) -> list[dict]:
    """A matriz planejada permite detectar também pares sem qualquer sucesso."""
    esperados = []
    caminhos = {caminho.resolve() for raiz in pastas for caminho in localizar_manifestos(raiz)}
    encontrados = set()
    for caminho in sorted(caminhos):
        try:
            manifesto = json.loads(caminho.read_text(encoding="utf-8"))
            for cenario in manifesto.get("specification", {}).get("scenarios", []):
                chave = json.dumps(cenario, sort_keys=True)
                if chave not in encontrados:
                    esperados.append(cenario)
                    encontrados.add(chave)
        except (OSError, ValueError):
            continue
    return esperados


def selecionar_parametros(registros: list[dict], esperados: list[dict] | None = None) -> list[dict]:
    """Compara apenas condições (perda, repetição e semente) comuns a todos os pares."""
    contextos = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for registro in registros:
        if registro["timeout_mode"] != "adaptive" or registro["historico"]:
            continue
        chave = tuple(registro[campo] for campo in ("contexto_id", "protocolo", "janela",
                                                "timeout_s", "rto_min_s", "rto_max_s"))
        par = (registro["alpha"], registro["beta"])
        condicao = (registro["loss_rate"], registro["repeticao"], registro["loss_seed"])
        # Não agrupar coletas avulsas sem identificação de repetição como pares.
        if registro["repeticao"] is None or registro["loss_seed"] is None:
            continue
        contextos[chave][par][condicao].append(registro)
    selecoes = []
    for chave, pares in sorted(contextos.items(), key=lambda item: str(item[0])):
        exemplo = next(iter(next(iter(pares.values())).values()))[0]
        campos_correspondencia = ("servidor", "porta", "grupo", "arquivo", "segment_size", "protocolo",
                           "janela", "timeout_s", "rto_min_s", "rto_max_s")
        planejados = [configuracao for configuracao in esperados or []
                   if configuracao.get("timeout_mode") == "adaptive"
                   and all(configuracao.get(campo) == exemplo.get(campo) for campo in campos_correspondencia)]
        ausentes = []
        for configuracao in planejados:
            par = (configuracao["alpha"], configuracao["beta"])
            condicao = (configuracao["loss_rate"], configuracao["repeticao"], configuracao["loss_seed"])
            if condicao not in pares.get(par, {}):
                ausentes.append(configuracao.get("id", str((par, condicao))))
        ausentes = sorted(set(ausentes))
        duplicadas = []
        pares_unicos = {}
        for (alfa, beta), condicoes in sorted(pares.items()):
            pares_unicos[(alfa, beta)] = {}
            for condicao, execucoes in sorted(condicoes.items()):
                if len(execucoes) == 1:
                    pares_unicos[(alfa, beta)][condicao] = execucoes[0]
                else:
                    duplicadas.append({"alpha": alfa, "beta": beta,
                                       "loss_rate": condicao[0], "repeticao": condicao[1],
                                       "loss_seed": condicao[2],
                                       "execucoes": sorted(linha["resumo_path"] for linha in execucoes)})
        # Uma pasta repetida é deduplicada em coletar_resultados. A mesma condição em
        # arquivos distintos é ambígua: não escolher silenciosamente a última.
        comuns = set.intersection(*(set(execucoes) for execucoes in pares_unicos.values())) if pares else set()
        classificacao = []
        for (alfa, beta), execucoes in sorted(pares_unicos.items()):
            if not comuns:
                continue
            valores = [execucoes[condicao] for condicao in sorted(comuns)]
            classificacao.append({"alpha": alfa, "beta": beta, "n": len(valores),
                           "throughput_medio_bps": statistics.mean(valor["throughput_medido_bps"] for valor in valores),
                           "tempo_medio_s": statistics.mean(valor["duracao_s"] for valor in valores),
                           "retransmissoes_media": statistics.mean(valor["retransmissoes"] for valor in valores)})
        classificacao.sort(key=lambda linha: linha["throughput_medio_bps"], reverse=True)
        elegivel = len(classificacao) >= 2 and bool(comuns) and not ausentes and not duplicadas
        selecoes.append({"contexto_id": chave[0], "protocolo": chave[1], "janela": chave[2],
                           "timeout_s": chave[3], "rto_min_s": chave[4], "rto_max_s": chave[5],
                           "criterio": "Maior média de throughput entre condições comuns de perda, repetição e semente",
                           "condicoes_comuns": [list(condicao) for condicao in sorted(comuns)],
                           "ranking": classificacao,
                           "escolhido": classificacao[0] if elegivel else None,
                           "configuracoes_ausentes": ausentes,
                           "condicoes_duplicadas": duplicadas,
                           "matriz_verificada": bool(planejados),
                           "status": ("condicoes_ambiguas" if duplicadas else
                                      "matriz_incompleta" if ausentes else
                                      "comparacao_disponivel" if elegivel else "dados_insuficientes")})
    return selecoes


def montar_tabela_integrada(registros: list[dict], agrupados: list[dict],
                           arquivo: str = "large", perda: float = 0.0):
    """Compara protocolo/modo com tamanho, conteúdo e perda comuns.

    A chamada sem argumentos extras preserva a tabela histórica de large.
    Arquivos com mesmo nome mas tamanho ou MD5 diferentes nunca se completam.
    """
    informacoes_contexto = {registro["contexto_id"]: {chave: registro[chave] for chave in CAMPOS_CONTEXTO} for registro in registros}
    candidatos = defaultdict(list)
    for linha in agrupados:
        if linha["janela"] != (1 if linha["protocolo"] == "SAW" else 16):
            continue
        if informacoes_contexto[linha["contexto_id"]]["arquivo"] != arquivo:
            continue
        if linha["loss_rate"] != perda:
            continue
        candidatos[linha["contexto_id"]].append(linha)
    escolhido = None
    if candidatos:
        escolhido = max(candidatos, key=lambda chave: (
            len({(registro["protocolo"], registro["timeout_mode"]) for registro in candidatos[chave]}),
            sum(registro["n"] for registro in candidatos[chave]), chave))
    candidatos_contexto = candidatos.get(escolhido, [])
    integrados = []
    for protocolo, modo in CONFIGURACOES_OBRIGATORIAS:
        opcoes = [registro for registro in candidatos_contexto if registro["protocolo"] == protocolo and registro["timeout_mode"] == modo]
        if opcoes:
            melhor = max(opcoes, key=lambda registro: registro["throughput_medio_bps"])
            linha = {campo: melhor.get(campo) for campo in CAMPOS_INTEGRADOS}
            linha["status"] = "medido"
        else:
            linha = {campo: None for campo in CAMPOS_INTEGRADOS}
            linha.update(protocolo=protocolo, janela=1 if protocolo == "SAW" else 16,
                       timeout_mode=modo, contexto_id=escolhido, loss_rate=perda,
                       n=0, status="ausente")
        integrados.append(linha)
    contexto = (informacoes_contexto[escolhido] | {"contexto_id": escolhido, "loss_rate": perda}
                if escolhido else None)
    return integrados, contexto


def montar_tabelas_integradas(registros: list[dict], agrupados: list[dict], perda: float = 0.0):
    """Expõe os três tamanhos, inclusive quando uma coleta ainda está ausente."""
    tabelas = {}
    for arquivo in ARQUIVOS_OBRIGATORIOS:
        linhas, contexto = montar_tabela_integrada(registros, agrupados, arquivo, perda)
        tabelas[arquivo] = {
            "integrados": linhas, "contexto_integrado": contexto,
            "ausentes": [{"protocolo": linha["protocolo"], "timeout_mode": linha["timeout_mode"]}
                         for linha in linhas if linha["status"] == "ausente"],
        }
    return tabelas


def salvar_csv(caminho: Path, campos, linhas) -> None:
    with caminho.open("w", newline="", encoding="utf-8") as arquivo_aberto:
        escritor = csv.DictWriter(arquivo_aberto, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({chave: json.dumps(valor, ensure_ascii=False) if isinstance(valor, (list, dict)) else valor
                             for chave, valor in linha.items()})


def principal(argumentos_cli=None) -> int:
    interpretador = argparse.ArgumentParser(description=__doc__)
    interpretador.add_argument("--input-dir", type=Path, nargs="+", default=[Path("entrega-3")])
    interpretador.add_argument("--historical-dir", type=Path, nargs="*", default=[])
    interpretador.add_argument("--output-dir", type=Path)
    interpretador.add_argument("--no-plots", action="store_true", help="gera tabelas sem depender de matplotlib")
    argumentos = interpretador.parse_args(argumentos_cli)
    destino = argumentos.output_dir or argumentos.input_dir[0] / "analise"
    destino.mkdir(parents=True, exist_ok=True)
    registros, avisos = coletar_resultados(argumentos.input_dir, argumentos.historical_dir)
    agrupados = agrupar_resultados(registros)
    tabelas = montar_tabelas_integradas(registros, agrupados)
    integrados = tabelas["large"]["integrados"]
    contexto = tabelas["large"]["contexto_integrado"]
    if any(registro["n"] == 1 for registro in agrupados):
        avisos.append("Há cenários com uma única execução; não há estimativa de dispersão nem evidência de significância estatística.")
    for arquivo, tabela in tabelas.items():
        if tabela["ausentes"]:
            faltantes = ", ".join(f"{linha['protocolo']} {linha['timeout_mode']}" for linha in tabela["ausentes"])
            avisos.append(f"Tabela integrada de {arquivo} incompleta: faltam {faltantes} no mesmo contexto remoto e perda de 0%.")
    if any(registro["historico"] for tabela in tabelas.values() for registro in tabela["integrados"]):
        avisos.append("A tabela integrada inclui coleta histórica identificada; datas e condições temporais da rede podem diferir.")
    analise = {"execucoes": registros, "comparativo": agrupados,
                "integrados": integrados, "contexto_integrado": contexto,
                "integrados_por_arquivo": {arquivo: tabela["integrados"] for arquivo, tabela in tabelas.items()},
                "contextos_integrados": {arquivo: tabela["contexto_integrado"] for arquivo, tabela in tabelas.items()},
                "configuracoes_ausentes_por_arquivo": {arquivo: tabela["ausentes"] for arquivo, tabela in tabelas.items()},
                "selecao_parametros": selecionar_parametros(registros, listar_cenarios_planejados(argumentos.input_dir)), "avisos": avisos,
                "metodo": "Médias por transferência; desvio amostral apenas para n>1; dados incompletos excluídos; contextos não misturados"}
    if any(selecao["status"] == "matriz_incompleta" for selecao in analise["selecao_parametros"]):
        avisos.append("Há configurações adaptativas planejadas sem coleta válida; o ranking parcial não escolhe vencedor.")
    if any(selecao["condicoes_duplicadas"] for selecao in analise["selecao_parametros"]):
        avisos.append("Há condições de perda/repetição/semente duplicadas em arquivos distintos; a seleção de α/β fica bloqueada até desambiguar as coletas.")
    if not argumentos.no_plots:
        try:
            gerar_graficos(destino, analise)
        except ImportError as erro:
            avisos.append(f"Gráficos não gerados: instale requirements.txt ({erro})")
    salvar_csv(destino / "execucoes.csv", CAMPOS_EXECUCAO, registros)
    salvar_csv(destino / "comparativo.csv", CAMPOS_COMPARATIVO, agrupados)
    salvar_csv(destino / "integrados.csv", CAMPOS_INTEGRADOS, integrados)
    for arquivo, tabela in tabelas.items():
        salvar_csv(destino / f"integrados_{arquivo}.csv", CAMPOS_INTEGRADOS, tabela["integrados"])
    (destino / "analise.json").write_text(json.dumps(analise, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for mensagem in avisos:
        print(f"Aviso: {mensagem}")
    print(f"{len(registros)} execuções remotas válidas; análise em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
