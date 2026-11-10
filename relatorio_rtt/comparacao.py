"""Preparação das tabelas e verificação do pareamento dos experimentos."""

from collections import defaultdict

from analisar_rtt import agrupar_resultados

ARQUIVOS = ("small", "medium", "large")


def grupos_com_contexto(registros):
    """Acrescenta origem, arquivo e MD5 sem misturar grupos de coleta."""
    contextos = {linha["contexto_id"]: linha for linha in registros}
    return [dict(contextos[grupo["contexto_id"]], **grupo)
            for grupo in agrupar_resultados(registros)]


def cobertura_entregas(historico_saw, registros_janelas, tabelas_integradas):
    """Confere todos os tamanhos e a matriz remota de janelas da Entrega 2.

    A cobertura nunca soma réplicas de arquivos com hashes diferentes.
    A Entrega 1 conserva sua coleta original de uma execução por tamanho;
    as matrizes das entregas seguintes exigem três repetições por condição.
    """
    linhas, pendencias = [], []
    grupos = grupos_com_contexto(registros_janelas)
    contextos_janelas = defaultdict(list)
    for grupo in grupos:
        if grupo["timeout_mode"] == "fixed" and not grupo.get("historico"):
            contextos_janelas[(grupo["arquivo"], grupo["contexto_id"], grupo["timeout_s"])].append(grupo)
    exigidas = {(protocolo, janela, perda) for protocolo in ("GBN", "SR")
                for janela in (4, 8, 16) for perda in (0.0, .05, .10)}
    for arquivo in ARQUIVOS:
        origem = [linha for linha in historico_saw if linha["arquivo"] == arquivo]
        linhas.append({"entrega": 1, "arquivo": arquivo, "concluidas": bool(origem),
                       "condicoes": len(origem), "esperadas": 1,
                       "contexto_id": None})
        if not origem:
            pendencias.append(f"Entrega 1: falta o resultado remoto de {arquivo}.")
        candidatos = [(chave, valores) for chave, valores in contextos_janelas.items()
                      if chave[0] == arquivo]
        def cobertura(item):
            return {(g["protocolo"], g["janela"], round(g["loss_rate"], 2))
                    for g in item[1] if g["n"] >= 3} & exigidas
        melhor = max(candidatos, key=lambda item: len(cobertura(item)), default=None)
        presentes = cobertura(melhor) if melhor else set()
        linhas.append({"entrega": 2, "arquivo": arquivo,
                       "concluidas": presentes == exigidas,
                       "condicoes": len(presentes), "esperadas": len(exigidas),
                       "contexto_id": melhor[0][1] if melhor else None})
        if presentes != exigidas:
            pendencias.append(f"Entrega 2 / {arquivo}: {len(presentes)} de 18 condições "
                              "GBN/SR × janelas 4/8/16 × perdas 0/5/10% têm três repetições válidas no mesmo contexto.")
        integrados = tabelas_integradas[arquivo]["integrados"]
        completos = sum(linha.get("status") == "medido" and linha.get("n", 0) >= 3
                        for linha in integrados)
        linhas.append({"entrega": 3, "arquivo": arquivo, "concluidas": completos == 5,
                       "condicoes": completos, "esperadas": 5,
                       "contexto_id": (tabelas_integradas[arquivo].get("contexto_integrado") or {}).get("contexto_id")})
        if completos != 5:
            pendencias.append(f"Entrega 3 / {arquivo}: {completos} de cinco configurações "
                              "SAW, GBN fixo/adaptativo e SR fixo/adaptativo têm três repetições sem perda no mesmo contexto.")
    return linhas, pendencias


def preparar_linhas_comparativas(registros):
    """Adapta o agrupamento compartilhado, incluindo porta e limites do RTO."""
    por_caminho = {linha["resumo_path"]: linha for linha in registros}
    saida = []
    for grupo in agrupar_resultados(registros):
        primeiro = por_caminho[grupo["execucoes"][0]]
        saida.append(dict(primeiro, n=grupo["n"], vazao=grupo["throughput_medio_bps"],
            desvio_vazao=grupo["throughput_desvio_bps"], duracao=grupo["tempo_medio_s"],
            retransmissoes=grupo["retransmissoes_media"]))
    return saida


def existe_comparacao_pareada(registros):
    """Exige o mesmo contexto, protocolo e sementes em ambas as taxas de perda."""
    fixos, adaptativos = defaultdict(set), defaultdict(set)
    for linha in registros:
        if linha["protocolo"] not in ("GBN", "SR"):
            continue
        perda = round(linha["loss_rate"], 2)
        if perda not in (.05, .10) or linha.get("repeticao") is None or linha.get("loss_seed") is None:
            continue
        contexto = tuple(linha[campo] for campo in ("contexto_id", "protocolo", "janela", "timeout_s"))
        condicao = (perda, linha["repeticao"], linha["loss_seed"])
        if linha["timeout_mode"] == "fixed":
            fixos[contexto].add(condicao)
        else:
            parametros = tuple(linha[campo] for campo in ("alpha", "beta", "rto_min_s", "rto_max_s"))
            adaptativos[(contexto, parametros)].add(condicao)
    return any({condicao[0] for condicao in condicoes & fixos[contexto]} == {.05, .10}
               for (contexto, _), condicoes in adaptativos.items())

