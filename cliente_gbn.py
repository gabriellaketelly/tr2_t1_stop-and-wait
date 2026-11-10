"""Cliente Go-Back-N UDP com timeout fixo ou RTT adaptativo."""

import csv
import hashlib
import json
import socket
import time

from protocolo_rdt import (
    ErroProtocolo,
    confirmacao_nao_suportada,
    finalizar,
    interpretar_dados,
    negociar_sessao,
)
from configuracao_clientes import analisar_argumentos, tamanho_segmento
from registro_metricas import (COLUNAS_METRICAS, RegistroEventos,
                               campos_csv_enunciado, nomear_csv_metricas)
from rtt import EstimadorRTT
from simulacao_perdas import SimuladorPerdas


def baixar_com_go_back_n(conexao, argumentos, informacoes):
    total, janela = informacoes["total_segments"], argumentos.window_size
    diretorio = argumentos.output_dir / "gbn" / argumentos.file
    diretorio.mkdir(parents=True, exist_ok=True)
    for nome in ("arquivo.bin", "arquivo.part", "metricas.csv", "eventos.csv", "resumo.json"):
        (diretorio / nome).unlink(missing_ok=True)

    estimador = EstimadorRTT.a_partir_dos_argumentos(argumentos)
    perdas = SimuladorPerdas(argumentos.loss_rate, getattr(argumentos, "loss_seed", None))
    base = proxima_sequencia = 0
    tentativas = [0] * total
    primeiro_envio, ultimo_envio, instantes_req, timeouts_req = {}, {}, {}, {}
    perdas_simuladas = [0] * total
    calculador_md5, avisos, rtts = hashlib.md5(), set(), []
    retransmissoes_total = total_expiracoes = bytes_recebidos = 0
    inicio = time.perf_counter()
    inicio_epoch = time.time()
    timeout_ativo = estimador.timeout
    arquivo_parcial = diretorio / "arquivo.part"

    with arquivo_parcial.open("wb") as arquivo_saida, (diretorio / "metricas.csv").open(
        "w", newline="", encoding="utf-8"
    ) as arquivo_metricas, (diretorio / "eventos.csv").open(
        "w", newline="", encoding="utf-8"
    ) as arquivo_eventos:
        escritor = csv.DictWriter(arquivo_metricas, fieldnames=COLUNAS_METRICAS)
        escritor.writeheader()
        registro = RegistroEventos(arquivo_eventos, inicio)

        def enviar_req(sequencia):
            nonlocal retransmissoes_total
            agora, instante_unix = time.perf_counter(), time.time()
            if tentativas[sequencia] == 0:
                primeiro_envio[sequencia] = agora
            else:
                retransmissoes_total += 1
            tentativas[sequencia] += 1
            ultimo_envio[sequencia] = agora
            instantes_req[sequencia] = instante_unix
            timeouts_req[sequencia] = timeout_ativo
            conexao.send(f"REQ|seq={sequencia}".encode("ascii"))
            registro.registrar(
                "REQ", sequencia, tentativas[sequencia], timeout_ativo,
                agora=agora, instante_unix=instante_unix,
            )

        def preencher_janela():
            nonlocal proxima_sequencia
            while proxima_sequencia < min(total, base + janela):
                enviar_req(proxima_sequencia)
                proxima_sequencia += 1

        preencher_janela()
        prazo = ultimo_envio[base] + timeout_ativo
        while base < total:
            # Verificação explícita: tráfego inválido/duplicado não adia o temporizador.
            tempo_restante = prazo - time.perf_counter()
            if tempo_restante <= 0:
                pendentes = range(base, proxima_sequencia)
                for sequencia in pendentes:
                    if tentativas[sequencia] - 1 >= argumentos.max_retries:
                        raise TimeoutError(f"Segmento {sequencia}: limite de retransmissões atingido")
                registro.registrar("TIMEOUT", base, tentativas[base], timeout_ativo,
                          detalhe=f"janela={base}:{proxima_sequencia - 1}")
                print(f"Timeout em {base}; retransmitindo {base} até {proxima_sequencia - 1}", flush=True)
                # Um recuo por expiração da janela, sem alterar o estimador.
                timeout_ativo = estimador.aplicar_recuo(timeout_ativo)
                for sequencia in pendentes:
                    enviar_req(sequencia)
                total_expiracoes += 1
                prazo = ultimo_envio[base] + timeout_ativo
                continue

            conexao.settimeout(tempo_restante)
            try:
                pacote = conexao.recv(65507)
                recebido_em, instante_unix = time.perf_counter(), time.time()
            except socket.timeout:
                continue
            if pacote.startswith(b"ERROR"):
                if confirmacao_nao_suportada(pacote, avisos):
                    continue
                raise ErroProtocolo(pacote.decode("ascii", errors="replace"))
            try:
                sequencia, tamanho_total, conteudo = interpretar_dados(pacote)
            except ErroProtocolo:
                continue
            if not 0 <= sequencia < proxima_sequencia:
                continue  # DATA sem REQ correspondente nunca é aceito.
            tamanho_esperado = tamanho_segmento(sequencia, informacoes)
            if (len(conteudo) != tamanho_esperado
                    or tamanho_total not in (tamanho_esperado, informacoes["file_size"])):
                continue
            registro.registrar("DATA", sequencia, tentativas[sequencia], timeout_ativo,
                      agora=recebido_em, instante_unix=instante_unix)
            if sequencia < base:
                continue
            # O descarte acontece antes da política GBN, inclusive fora de ordem.
            if perdas.descartar(sequencia, tentativas[sequencia]):
                perdas_simuladas[sequencia] += 1
                registro.registrar("DROP", sequencia, tentativas[sequencia], timeout_ativo, "simulated_loss",
                          agora=recebido_em, instante_unix=instante_unix)
                continue
            if sequencia != base:
                registro.registrar("DISCARD", sequencia, tentativas[sequencia], timeout_ativo, "out_of_order",
                          agora=recebido_em, instante_unix=instante_unix)
                continue

            tempo_decorrido = recebido_em - primeiro_envio[sequencia]
            amostra_valida = tentativas[sequencia] == 1
            if amostra_valida:
                rtts.append(tempo_decorrido)
                timeout_ativo = estimador.atualizar(tempo_decorrido)
            vazao_segmento = len(conteudo) * 8 / tempo_decorrido if tempo_decorrido > 0 else 0
            metricas_rtt = estimador.campos_metricas()
            linha = {
                "grupo": argumentos.group, "servidor": argumentos.server,
                "porta": argumentos.port, "arquivo": argumentos.file, "protocolo": "GBN",
                "seq": sequencia, "bytes": len(conteudo),
                "rtt_ms": tempo_decorrido * 1000 if amostra_valida else "",
                "tempo_segmento_ms": tempo_decorrido * 1000,
                "throughput_bps": vazao_segmento,
                "retransmissoes": tentativas[sequencia] - 1,
                "timeout_ocorrido": int(tentativas[sequencia] > 1),
                "simulated_loss": perdas_simuladas[sequencia],
                "req_timestamp_epoch": f"{instantes_req[sequencia]:.9f}",
                "data_timestamp_epoch": f"{instante_unix:.9f}",
                "received_elapsed_s": recebido_em - inicio,
                "timeout_usado_ms": timeouts_req[sequencia] * 1000,
                "rtt_sample_valid": int(amostra_valida), **metricas_rtt,
                **campos_csv_enunciado(sequencia, instante_unix, len(conteudo),
                    metricas_rtt["rtt_est_ms"], vazao_segmento,
                    tentativas[sequencia] - 1, janela, "GBN"),
            }
            escritor.writerow(linha)
            arquivo_saida.write(conteudo)
            calculador_md5.update(conteudo)
            bytes_recebidos += len(conteudo)
            conexao.send(f"ACK|seq={sequencia}".encode("ascii"))
            base += 1
            preencher_janela()
            # ACK avança a base e arma um novo temporizador; prazos já ativos não
            # são recalculados a cada passagem pelo laço.
            prazo = recebido_em + timeout_ativo
            if base % 100 == 0 or base == total:
                print(f"GBN: {base}/{total} segmentos", flush=True)

    duracao = time.perf_counter() - inicio
    md5 = calculador_md5.hexdigest()
    md5_valido = bytes_recebidos == informacoes["file_size"] and md5 == informacoes["checksum"]
    confirmado = finalizar(conexao, md5, argumentos, avisos)
    metrics_file = nomear_csv_metricas(
        diretorio / "metricas.csv", argumentos.group, "gbn", inicio_epoch,
    )
    resumo = {
        "protocolo": "GBN", "grupo": argumentos.group, "arquivo": argumentos.file,
        "servidor": argumentos.server, "porta": argumentos.port, "janela": janela,
        "loss_rate": argumentos.loss_rate, "loss_seed": getattr(argumentos, "loss_seed", None),
        "loss_method": "sha256_seq_attempt_v1" if perdas.semente is not None else "random",
        "simulated_loss_total": sum(perdas_simuladas),
        "file_size": bytes_recebidos, "segment_size": informacoes["segment_size"],
        "total_segments": total, "seed": informacoes.get("seed"),
        "md5_esperado": informacoes["checksum"], "md5_recebido": md5,
        "checksum_ok": md5_valido, "done_ok": confirmado, "duracao_s": duracao,
        "rtt_medio_s": sum(rtts) / len(rtts) if rtts else None,
        "throughput_medido_bps": bytes_recebidos * 8 / duracao if duracao > 0 else 0,
        "retransmissoes": retransmissoes_total, "timeouts": total_expiracoes,
        "timeout_s": argumentos.timeout, "avisos_servidor": sorted(avisos),
        "metrics_file": metrics_file,
        **estimador.resumo(),
    }
    (diretorio / "resumo.json").write_text(
        json.dumps(resumo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not md5_valido or not confirmado:
        raise ErroProtocolo("Integridade não confirmada; consulte resumo.json")
    arquivo_parcial.replace(diretorio / "arquivo.bin")
    return resumo


def principal(lista_argumentos=None):
    argumentos = analisar_argumentos(lista_argumentos)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
            conexao.connect((argumentos.server, argumentos.port))
            informacoes = negociar_sessao(conexao, argumentos)
            print(f"Arquivo: {informacoes['file_size']} bytes | Segmentos: {informacoes['total_segments']} "
                  f"| Janela: {argumentos.window_size} | Timeout: {argumentos.timeout_mode}")
            resumo = baixar_com_go_back_n(conexao, argumentos, informacoes)
            print(f"MD5: {resumo['md5_recebido']}")
            print(f"Throughput: {resumo['throughput_medido_bps']:.2f} bit/s")
        return 0
    except (OSError, ErroProtocolo, TimeoutError, UnicodeError) as erro:
        print(f"Erro: {erro}")
        return 1


if __name__ == "__main__":
    raise SystemExit(principal())
