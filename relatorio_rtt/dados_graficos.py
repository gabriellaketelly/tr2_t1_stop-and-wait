"""Exporta apenas os dados usados no relatório, separados por entrega e protocolo."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from zoneinfo import ZoneInfo
from pathlib import Path


CAMPOS = [
    "tipo_dado", "fonte", "protocolo", "arquivo", "grupo", "servidor", "janela",
    "timeout_mode", "timeout_s", "alpha", "beta", "loss_rate", "repeticao", "n",
    "throughput_kbps", "throughput_desvio_kbps", "duracao_s", "retransmissoes",
    "rtt_medio_ms", "md5", "segment", "timestamp", "elapsed_s", "size_bytes",
    "rtt_ms", "rtt_estimated_ms", "dev_rtt_ms", "timeout_ms", "timeout_used_ms",
    "rtt_sample_valid", "timeout_occurred", "entrega", "md5_esperado",
    "md5_recebido", "md5_recalculado", "checksum_verificado",
]


def _linha(tipo, fonte, **dados):
    linha = {campo: "" for campo in CAMPOS}
    linha.update(tipo_dado=tipo, fonte=fonte)
    linha.update({campo: valor for campo, valor in dados.items() if campo in linha})
    return linha


def _timestamp_utc(epoch):
    if not epoch:
        return ""
    return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def consolidar_dados_graficos(destino, analise, grupos_janelas, historico_saw,
                               verificacoes_md5=()):
    """Escreve CSVs derivados sem apagar os CSVs brutos anexados.

    Os arquivos de métricas por execução são a fonte auditável completa. O
    consolidado é apenas uma visão adicional para gráficos e tabelas; portanto
    nunca pode remover os anexos brutos já copiados por ``organizar_anexos``.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    linhas = []
    contextos = {r["contexto_id"]: r for r in analise.get("execucoes", [])}
    integrados = analise.get("integrados_por_arquivo") or {"large": analise.get("integrados", [])}
    contextos_integrados = analise.get("contextos_integrados") or {"large": analise.get("contexto_integrado")}

    def adicionar_media(tipo, entrega, registro, contexto):
        linhas.append(_linha(tipo, "medias_de_transferencias_remotas", entrega=entrega,
            protocolo=registro.get("protocolo"), arquivo=contexto.get("arquivo"),
            grupo=contexto.get("grupo"), servidor=contexto.get("servidor"),
            contexto_id=registro.get("contexto_id"), md5=contexto.get("md5_esperado"),
            size_bytes=contexto.get("file_size"), janela=registro.get("janela"),
            timeout_mode=registro.get("timeout_mode"), timeout_s=registro.get("timeout_s"),
            alpha=registro.get("alpha"), beta=registro.get("beta"),
            loss_rate=registro.get("loss_rate"), n=registro.get("n"),
            throughput_kbps=registro.get("throughput_medio_bps", 0) / 1000,
            throughput_desvio_kbps=registro["throughput_desvio_bps"] / 1000
                if registro.get("throughput_desvio_bps") is not None else "",
            duracao_s=registro.get("tempo_medio_s"), retransmissoes=registro.get("retransmissoes_media"),
            rtt_medio_ms=registro["rtt_medio_s"] * 1000 if registro.get("rtt_medio_s") is not None else "",
            origem_resumo=json.dumps(registro.get("execucoes", []), ensure_ascii=False)))

    for arquivo, resultados in integrados.items():
        contexto = contextos_integrados.get(arquivo) or {}
        for registro in resultados:
            if registro.get("status") == "medido":
                adicionar_media("throughput_integrado", "entrega3", registro, contexto)
    for registro in analise.get("comparativo", []):
        adicionar_media("comparacao_timeout_parametros", "entrega3", registro,
                        contextos.get(registro["contexto_id"], {}))
    for registro in grupos_janelas:
        adicionar_media("janela_perda", "entrega2", registro, registro)
    for registro in analise.get("execucoes", []):
        linhas.append(_linha("transferencia_completa", "resumo_validado", entrega="entrega3",
            protocolo=registro.get("protocolo"), arquivo=registro.get("arquivo"),
            grupo=registro.get("grupo"), servidor=registro.get("servidor"),
            contexto_id=registro.get("contexto_id"), janela=registro.get("janela"),
            timeout_mode=registro.get("timeout_mode"), timeout_s=registro.get("timeout_s"),
            alpha=registro.get("alpha"), beta=registro.get("beta"), loss_rate=registro.get("loss_rate"),
            repeticao=registro.get("repeticao"), n=1,
            throughput_kbps=registro.get("throughput_medido_bps", 0) / 1000,
            duracao_s=registro.get("duracao_s"), retransmissoes=registro.get("retransmissoes"),
            md5=registro.get("md5_recebido"), size_bytes=registro.get("file_size"),
            origem_resumo=registro.get("resumo_path")))

    for registro in historico_saw:
        linhas.append(_linha(
            "entrega1_saw_historico", "entrega1_medicoes_remotas",
            entrega="entrega1",
            protocolo="SAW", arquivo=registro.get("arquivo"), grupo=registro.get("grupo"),
            servidor=registro.get("servidor"), janela=1, timeout_mode=registro.get("timeout_mode", "fixed"),
            timeout_s=registro.get("timeout_s"), loss_rate=registro.get("loss_rate", 0), n=1,
            throughput_kbps=(registro.get("throughput_medido_bps") or 0) / 1000,
            duracao_s=registro.get("duracao_s"), retransmissoes=registro.get("retransmissoes"),
            rtt_medio_ms=(registro.get("rtt_medio_s") or 0) * 1000,
            md5=registro.get("md5_recebido"), size_bytes=registro.get("file_size"),
        ))

    unicos_md5 = {}
    for registro in verificacoes_md5:
        chave = (registro.get("entrega"), registro.get("ambiente"),
                 registro.get("protocolo"), registro.get("arquivo"),
                 registro.get("md5_esperado"), registro.get("md5_registrado"))
        anterior = unicos_md5.get(chave)
        if anterior is None or (not anterior.get("md5_recalculado") and registro.get("md5_recalculado")):
            unicos_md5[chave] = registro
    for registro in unicos_md5.values():
        linhas.append(_linha(
            "md5_integridade", registro.get("ambiente", ""),
            entrega=registro.get("entrega"), protocolo=registro.get("protocolo"),
            arquivo=registro.get("arquivo"), md5_esperado=registro.get("md5_esperado"),
            md5_recebido=registro.get("md5_registrado"),
            md5_recalculado=registro.get("md5_recalculado"),
            checksum_verificado=(registro.get("md5_esperado") == registro.get("md5_registrado")
                == registro.get("md5_recalculado") and bool(registro.get("md5_recalculado"))),
        ))

    amostra_resumo = Path(analise.get("amostra_graficos", ""))
    execucao = next((registro for registro in analise.get("execucoes", [])
                     if registro.get("resumo_path") == str(amostra_resumo.resolve())), {})
    caminho_metricas = Path(execucao.get("metricas_path", ""))
    if caminho_metricas.is_file():
        with caminho_metricas.open(newline="", encoding="utf-8") as arquivo:
            for amostra in csv.DictReader(arquivo):
                linhas.append(_linha(
                    "rtt_timeout_segmento", "entrega3_csv_segmentos_mais_recente",
                    entrega="entrega3",
                    protocolo=execucao.get("protocolo"), arquivo=execucao.get("arquivo"),
                    grupo=execucao.get("grupo"), servidor=execucao.get("servidor"),
                    janela=execucao.get("janela"), timeout_mode=execucao.get("timeout_mode"),
                    timeout_s=execucao.get("timeout_s"), alpha=execucao.get("alpha"), beta=execucao.get("beta"),
                    loss_rate=execucao.get("loss_rate"), repeticao=execucao.get("repeticao"),
                    segment=amostra.get("seq"), timestamp=_timestamp_utc(amostra.get("data_timestamp_epoch")),
                    elapsed_s=amostra.get("received_elapsed_s"), size_bytes=amostra.get("bytes"),
                    rtt_ms=amostra.get("rtt_ms"), rtt_estimated_ms=amostra.get("rtt_est_ms"),
                    dev_rtt_ms=amostra.get("dev_rtt_ms"), timeout_ms=amostra.get("timeout_ms"),
                    timeout_used_ms=amostra.get("timeout_usado_ms"),
                    rtt_sample_valid=amostra.get("rtt_sample_valid"),
                    timeout_occurred=amostra.get("timeout_ocorrido"),
                ))

    grupos = {}
    for linha in linhas:
        tipo = linha["tipo_dado"]
        entrega = linha.get("entrega", "")
        protocolo = str(linha.get("protocolo", "")).lower()
        if tipo == "entrega1_saw_historico":
            chave = ("entrega1", "saw")
        elif tipo == "janela_perda":
            chave = ("entrega2", protocolo)
        elif tipo == "md5_integridade":
            entrega_csv = ("entrega2" if entrega.startswith("entrega2") else entrega)
            chave = (entrega_csv, protocolo)
        else:
            chave = (entrega or "entrega3", protocolo)
        grupos.setdefault(chave, []).append(linha)

    manifesto = []
    # Também preserva uma visão consolidada única para o link do relatório.
    with destino.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=CAMPOS, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(linhas)
    for (nome_entrega, protocolo), linhas_grupo in sorted(grupos.items()):
        carimbo = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y%m%d_%H%M%S_%f")
        nome = f"metrics_grupo08_{protocolo}_{carimbo}.csv"
        caminho = destino.parent / nome
        with caminho.open("w", newline="", encoding="utf-8") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=CAMPOS, extrasaction="ignore")
            escritor.writeheader()
            escritor.writerows(linhas_grupo)
        manifesto.append({
            "entrega": nome_entrega, "protocolo": protocolo,
            "anexo": str(caminho.name), "linhas": len(linhas_grupo),
            "total_linhas": len(linhas),
            "arquivos": sorted({linha["arquivo"] for linha in linhas_grupo if linha["arquivo"]}),
            "sha256_csv": hashlib.sha256(caminho.read_bytes()).hexdigest(),
        })
    (destino.parent / "manifesto_anexos.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifesto
