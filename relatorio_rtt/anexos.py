"""Leitura dos registros e organização auditável de CSVs e checksums."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

SERVIDOR_REMOTO = "137.131.178.229"


def ler_json(caminho, padrao=None):
    if not caminho.is_file():
        return {} if padrao is None else padrao
    return json.loads(caminho.read_text(encoding="utf-8"))


def carregar_resumos(raiz):
    registros = []
    if not raiz.is_dir():
        return registros
    for caminho in sorted(raiz.rglob("resumo.json")):
        dados = ler_json(caminho)
        if not dados.get("checksum_ok") or not dados.get("done_ok"):
            continue
        if dados.get("md5_esperado") != dados.get("md5_recebido"):
            continue
        if not (caminho.parent / "metricas.csv").is_file():
            continue
        dados = dict(dados, origem=str(caminho.resolve()))
        dados.setdefault("protocolo", "SAW")
        dados.setdefault("janela", 1)
        dados.setdefault("timeout_mode", "fixed")
        dados.setdefault("loss_rate", 0.0)
        registros.append(dados)
    return registros


def escrever_csv(caminho, linhas, colunas):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(linhas)


def _timestamp_iso(linha):
    """Usa o instante de recebimento original; não inventa tempos históricos."""
    if linha.get("timestamp"):
        return linha["timestamp"]
    for campo in ("data_timestamp_epoch", "timestamp_epoch"):
        if linha.get(campo):
            instante = datetime.fromtimestamp(float(linha[campo]), timezone.utc)
            return instante.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return ""


def _normalizar_linha_csv(linha, resumo):
    """Mantém colunas antigas e acrescenta os nomes pedidos no enunciado."""
    linha = dict(linha)
    sequencia = linha.get("seq", linha.get("segment", ""))
    tamanho = linha.get("bytes", linha.get("size_bytes", ""))
    vazao = linha.get("throughput_bps", "")
    if vazao == "" and linha.get("throughput_kbps"):
        vazao = float(linha["throughput_kbps"]) * 1000
    estimativa = linha.get("rtt_est_ms", linha.get("rtt_estimated_ms", ""))
    timeout_configurado = linha.get("timeout_ms", linha.get("timeout_usado_ms", ""))
    if timeout_configurado == "" and resumo.get("timeout_s") not in (None, ""):
        timeout_configurado = float(resumo["timeout_s"]) * 1000
    rtt_valido = linha.get("rtt_sample_valid", "")
    if rtt_valido == "" and linha.get("rtt_ms", "") != "":
        rtt_valido = "1"
    linha.update({
        "segment": sequencia,
        "timestamp": _timestamp_iso(linha),
        "size_bytes": tamanho,
        "rtt_estimated_ms": estimativa,
        "timeout_ms": timeout_configurado,
        "timeout_used_ms": linha.get("timeout_usado_ms", linha.get("timeout_used_ms", timeout_configurado)),
        "rtt_sample_valid": rtt_valido,
        "simulated_loss": linha.get("simulated_loss", ""),
        "throughput_kbps": float(vazao) / 1000 if vazao not in (None, "") else "",
        "retransmissions": linha.get("retransmissoes", linha.get("retransmissions", "")),
        "timeout_occurred": linha.get("timeout_ocorrido", linha.get("timeout_occurred", "")),
        "window_size": resumo.get("janela", 1 if resumo.get("protocolo") == "SAW" else ""),
        "protocol": str(resumo.get("protocolo", linha.get("protocolo", ""))).lower(),
    })
    return linha


def organizar_anexos(saida, origens, copiar_csv=True):
    pasta_anexos = saida / "anexos"
    if pasta_anexos.exists():
        shutil.rmtree(pasta_anexos)
    manifesto, verificacoes_md5 = [], []
    for entrega, registros in origens:
        for indice, linha in enumerate(registros, 1):
            resumo = Path(linha['origem'])
            metricas = resumo.parent / "metricas.csv"
            ambiente = "remoto" if linha.get("servidor") == SERVIDOR_REMOTO else "servidor_indisponivel"
            perda = round(float(linha.get("loss_rate", 0)) * 100)
            modo = linha.get("timeout_mode", "fixed")
            inicio = linha.get("coleta_inicio_utc")
            if inicio:
                instante_nome = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
            else:
                instante_nome = datetime.fromtimestamp(metricas.stat().st_mtime).astimezone()
            sufixo_data = instante_nome.astimezone().strftime("%Y%m%d_%H%M%S_%f")
            grupo = linha.get("grupo") or "grupo08"
            nome_arquivo = f"metrics_{grupo}_{linha['protocolo'].lower()}_{sufixo_data}.csv"
            destino = saida / "anexos" / entrega / ambiente / nome_arquivo
            destino.parent.mkdir(parents=True, exist_ok=True)
            linhas = []
            if copiar_csv:
                with metricas.open(newline="", encoding="utf-8") as origem:
                    leitor = csv.DictReader(origem)
                    colunas_originais = leitor.fieldnames or []
                    linhas = [_normalizar_linha_csv(registro, linha) for registro in leitor]
                colunas_alias = ["segment", "timestamp", "size_bytes", "rtt_estimated_ms",
                                 "throughput_kbps", "retransmissions", "timeout_occurred",
                                 "timeout_ms", "timeout_used_ms", "rtt_sample_valid",
                                 "simulated_loss", "window_size", "protocol"]
                escrever_csv(destino, linhas, list(dict.fromkeys(colunas_originais + colunas_alias)))
            manifesto.append({
                "entrega": entrega, "ambiente": ambiente,
                "grupo": linha.get("grupo"), "servidor": linha.get("servidor"),
                "origem": str(metricas.resolve()), "anexo": str(destino.relative_to(saida)),
                "timestamp_segmento": "presente" if any(registro.get("timestamp") for registro in linhas) else "indisponível no legado",
                "sha256_csv": hashlib.sha256((destino if copiar_csv else metricas).read_bytes()).hexdigest(),
            })
            binario = resumo.parent / "arquivo.bin"
            md5_recalculado = hashlib.md5(binario.read_bytes()).hexdigest() if binario.is_file() else ""
            verificacoes_md5.append({
                "entrega": entrega, "ambiente": ambiente,
                "grupo": linha.get("grupo"), "servidor": linha.get("servidor"),
                "protocolo": linha["protocolo"], "timeout_mode": modo,
                "arquivo": linha["arquivo"], "origem_resumo": str(resumo),
                "md5_esperado": linha["md5_esperado"],
                "md5_registrado": linha["md5_recebido"],
                "md5_recalculado": md5_recalculado,
                "arquivo_disponivel": binario.is_file(),
                "md5_confere": md5_recalculado == linha["md5_esperado"] if md5_recalculado else "N/D",
            })
    escrever_csv(saida / "anexos" / "csv_manifest.csv", manifesto,
              ["entrega", "ambiente", "grupo", "servidor", "origem", "anexo",
               "timestamp_segmento", "sha256_csv"])
    escrever_csv(saida / "anexos" / "md5.csv", verificacoes_md5,
              ["entrega", "ambiente", "grupo", "servidor", "protocolo", "timeout_mode", "arquivo",
               "origem_resumo", "md5_esperado", "md5_registrado", "md5_recalculado",
               "arquivo_disponivel", "md5_confere"])
    return manifesto, verificacoes_md5

