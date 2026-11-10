"""Argumentos e tamanhos negociados compartilhados por GBN e SR."""

import argparse
import math
from pathlib import Path

from protocolo_rdt import validar_identificador
from rtt import EstimadorRTT


def analisar_argumentos(lista_argumentos=None):
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--server", default="137.131.178.229")
    analisador.add_argument("--port", type=int, default=8080)
    analisador.add_argument("--group", required=True, type=validar_identificador)
    analisador.add_argument("--file", choices=("small", "medium", "large"), default="small")
    analisador.add_argument("--segment-size", type=int, default=512)
    analisador.add_argument("--timeout", type=float, default=0.2,
                        help="timeout fixo ou RTO inicial adaptativo, em segundos")
    analisador.add_argument("--timeout-mode", choices=("fixed", "adaptive"), default="fixed")
    analisador.add_argument("--alpha", type=float, default=0.125)
    analisador.add_argument("--beta", type=float, default=0.25)
    analisador.add_argument("--rto-min", type=float, default=0.01)
    analisador.add_argument("--rto-max", type=float, default=60.0)
    analisador.add_argument("--max-retries", type=int, default=10)
    analisador.add_argument("--window-size", type=int, choices=(4, 8, 16), default=4)
    analisador.add_argument("--loss-rate", type=float, default=0.0)
    analisador.add_argument("--loss-seed", type=int, default=None)
    analisador.add_argument("--output-dir", type=Path, default=Path("resultados"))
    argumentos = analisador.parse_args(lista_argumentos)
    if not 1 <= argumentos.segment_size <= 512:
        analisador.error("--segment-size deve estar entre 1 e 512")
    try:
        EstimadorRTT.a_partir_dos_argumentos(argumentos)
    except ValueError as erro:
        analisador.error(str(erro))
    if argumentos.max_retries < 0:
        analisador.error("--max-retries não pode ser negativo")
    if not 1 <= argumentos.port <= 65535:
        analisador.error("porta inválida")
    if not math.isfinite(argumentos.loss_rate) or not 0 <= argumentos.loss_rate <= 1:
        analisador.error("--loss-rate deve estar entre 0 e 1")
    return argumentos


def tamanho_segmento(sequencia, informacoes):
    tamanho_negociado = informacoes["segment_size"]
    bytes_restantes = informacoes["file_size"] - sequencia * tamanho_negociado
    return min(tamanho_negociado, bytes_restantes)
