"""Mensagens e validações compartilhadas pelos clientes RDT sobre UDP."""

import argparse
import math
import socket
import time


class ErroProtocolo(Exception):
    """Indica uma mensagem ou transição inválida no protocolo RDT."""


def validar_identificador(valor):
    """Valida o identificador de grupo usado no campo grupo do HELLO."""
    if not valor or not valor.isascii() or any(caractere in valor for caractere in "|=\r\n"):
        raise argparse.ArgumentTypeError("identificador vazio ou com delimitadores inválidos")
    return valor


def interpretar_campos(pacote, tipo_esperado):
    try:
        partes = pacote.decode("ascii").split("|")
        if partes[0] != tipo_esperado:
            raise ValueError("tipo inesperado")
        campos = {}
        for parte in partes[1:]:
            chave, valor = parte.split("=", 1)
            if chave in campos:
                raise ValueError("campo duplicado")
            campos[chave] = valor
        return campos
    except (UnicodeError, ValueError) as erro:
        raise ErroProtocolo(f"{tipo_esperado} inválido: {erro}") from erro


def confirmacao_nao_suportada(pacote, avisos):
    """Reconhece a incompatibilidade de ACK observada no servidor remoto."""
    if pacote.rstrip() != b"ERROR|msg=tipo_desconhecido_ACK":
        return False
    if avisos is not None and "ack_nao_suportado" not in avisos:
        avisos.add("ack_nao_suportado")
        print("Aviso: servidor rejeita ACK; mantendo o fluxo de envio compatível.", flush=True)
    return True


def trocar_mensagem(conexao, mensagem, tipo_esperado, timeout_segundos,
                    max_retransmissoes, avisos=None):
    for _ in range(max_retransmissoes + 1):
        conexao.send(mensagem)
        prazo = time.perf_counter() + timeout_segundos
        while True:
            tempo_restante = prazo - time.perf_counter()
            if tempo_restante <= 0:
                break
            conexao.settimeout(tempo_restante)
            try:
                pacote = conexao.recv(65507)
            except socket.timeout:
                break
            if pacote.startswith(tipo_esperado + b"|"):
                return interpretar_campos(pacote, tipo_esperado.decode("ascii"))
            if pacote.startswith(b"ERROR"):
                if confirmacao_nao_suportada(pacote, avisos):
                    continue
                raise ErroProtocolo(pacote.decode("ascii", errors="replace"))
    raise TimeoutError(f"Sem {tipo_esperado.decode()} após {max_retransmissoes + 1} tentativas")


def negociar_sessao(conexao, argumentos):
    hello = (f"HELLO|grupo={argumentos.group}|segment_size={argumentos.segment_size}"
             f"|file={argumentos.file}").encode("ascii")
    campos = trocar_mensagem(conexao, hello, b"OK", argumentos.timeout, argumentos.max_retries)
    try:
        informacoes = {chave: int(campos[chave]) for chave in
                       ("file_size", "total_segments", "segment_size")}
        checksum = campos["checksum"].lower()
        if len(checksum) != 32 or any(caractere not in "0123456789abcdef" for caractere in checksum):
            raise ValueError("MD5 inválido")
        if informacoes["file_size"] <= 0 or not 1 <= informacoes["segment_size"] <= 512:
            raise ValueError("tamanho inválido")
        if informacoes["total_segments"] != math.ceil(
                informacoes["file_size"] / informacoes["segment_size"]):
            raise ValueError("quantidade de segmentos inconsistente")
        informacoes.update(checksum=checksum, seed=campos.get("seed"))
        return informacoes
    except (KeyError, ValueError) as erro:
        raise ErroProtocolo(f"Parâmetros do OK inválidos: {erro}") from erro


def interpretar_dados(pacote):
    try:
        tipo, campo_sequencia, campo_total, conteudo = pacote.split(b"|", 3)
        if (tipo != b"DATA" or not campo_sequencia.startswith(b"seq=")
                or not campo_total.startswith(b"total=")):
            raise ValueError("cabeçalho inesperado")
        sequencia = int(campo_sequencia[4:])
        tamanho = int(campo_total[6:])
        if sequencia < 0 or tamanho < 0:
            raise ValueError("valor negativo")
        return sequencia, tamanho, conteudo
    except ValueError as erro:
        raise ErroProtocolo(f"DATA inválido: {erro}") from erro


def finalizar(conexao, soma_verificacao, argumentos, avisos=None):
    campos = trocar_mensagem(
        conexao, f"FIN|checksum={soma_verificacao}".encode("ascii"), b"DONE",
        argumentos.timeout, argumentos.max_retries, avisos,
    )
    if campos.get("ok") not in ("0", "1"):
        raise ErroProtocolo("DONE sem campo ok válido")
    return campos["ok"] == "1"
