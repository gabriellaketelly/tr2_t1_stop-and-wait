"""Transporte simulado para testar os clientes sem rede nem espera real.

send, recv e settimeout preservam a interface do socket usada pelos clientes.
"""

import heapq
import socket


class DatagramasSimulados:
    """Transporta bytes e avança um relógio virtual, sem abrir socket."""

    def __init__(self, conteudo, tentativas_descartadas=1, reordenar=False, ruido=False):
        self.agora = 0.0
        self.conteudo = conteudo
        self.tentativas_descartadas = tentativas_descartadas
        self.reordenar = reordenar
        self.ruido = ruido
        self.requisicoes = {}
        self.fila = []
        self.contador = 0
        self.timeout = 1
        self.enviados = []

    def agendar(self, atraso, pacote):
        self.contador += 1
        heapq.heappush(self.fila, (self.agora + atraso, self.contador, pacote))

    def send(self, pacote):
        self.enviados.append((self.agora, pacote))
        if pacote.startswith(b"REQ"):
            sequencia = int(pacote.split(b"=")[1])
            self.requisicoes[sequencia] = self.requisicoes.get(sequencia, 0) + 1
            if sequencia == 0 and self.requisicoes[sequencia] <= self.tentativas_descartadas:
                if self.ruido:
                    for n in range(1, 100):
                        self.agendar(n * .005, b"invalid")
                return len(pacote)
            atraso = .030 if self.reordenar and sequencia == 0 else .022
            conteudo_segmento = self.conteudo[sequencia * 4:(sequencia + 1) * 4]
            cabecalho = f"DATA|seq={sequencia}|total={len(self.conteudo)}|".encode()
            self.agendar(atraso, cabecalho + conteudo_segmento)
            if sequencia == 0:
                # DATA duplicado ou não solicitado não pode alterar o arquivo nem o estimador.
                self.agendar(atraso + .001, b"DATA|seq=999|total=4|oops")
        elif pacote.startswith(b"FIN"):
            self.agendar(.005, b"DONE|ok=1")
        return len(pacote)

    def settimeout(self, timeout):
        self.timeout = timeout

    def recv(self, tamanho):
        if self.fila and self.fila[0][0] <= self.agora + self.timeout:
            self.agora, _, pacote = heapq.heappop(self.fila)
            return pacote
        self.agora += self.timeout
        raise socket.timeout
