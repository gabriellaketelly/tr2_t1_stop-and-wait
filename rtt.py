"""Estimador EWMA de RTT e desvio, independente de transporte e arquivos.

A ordem segue o enunciado: DevRTT usa o RTT estimado já atualizado.
O chamador deve excluir amostras retransmitidas, conforme a regra de Karn.
"""

import math


class EstimadorRTT:
    def __init__(self, timeout_inicial, alpha=0.125, beta=0.25,
                 minimo=0.01, maximo=60.0, modo="fixed"):
        valores = (timeout_inicial, alpha, beta, minimo, maximo)
        if not all(math.isfinite(valor) for valor in valores):
            raise ValueError("parâmetros RTT devem ser finitos")
        if timeout_inicial <= 0 or not 0 < alpha <= 1 or not 0 < beta <= 1:
            raise ValueError("timeout deve ser positivo; alpha e beta em (0, 1]")
        if not 0 < minimo <= maximo:
            raise ValueError("limites RTO devem satisfazer 0 < mínimo <= máximo")
        if modo not in ("fixed", "adaptive"):
            raise ValueError("modo deve ser fixed ou adaptive")
        self.timeout_inicial = timeout_inicial
        self.alpha = alpha
        self.beta = beta
        self.minimo = minimo
        self.maximo = maximo
        self.modo = modo
        self.rtt_estimado = None
        self.desvio_rtt = None
        self.amostras = 0

    @classmethod
    def a_partir_dos_argumentos(cls, argumentos):
        return cls(argumentos.timeout, getattr(argumentos, "alpha", 0.125),
                   getattr(argumentos, "beta", 0.25), getattr(argumentos, "rto_min", 0.01),
                   getattr(argumentos, "rto_max", 60.0),
                   getattr(argumentos, "timeout_mode", "fixed"))

    def limitar(self, valor):
        return min(self.maximo, max(self.minimo, valor))

    @property
    def timeout(self):
        if self.modo == "fixed":
            return self.timeout_inicial
        if self.rtt_estimado is None:
            return self.limitar(self.timeout_inicial)
        return self.limitar(self.rtt_estimado + 4 * self.desvio_rtt)

    def atualizar(self, amostra):
        if not math.isfinite(amostra) or amostra <= 0:
            raise ValueError("amostra RTT deve ser positiva e finita")
        if self.rtt_estimado is None:
            self.rtt_estimado = amostra
            self.desvio_rtt = amostra / 2
        else:
            self.rtt_estimado = ((1 - self.alpha) * self.rtt_estimado
                                  + self.alpha * amostra)
            self.desvio_rtt = ((1 - self.beta) * self.desvio_rtt
                            + self.beta * abs(amostra - self.rtt_estimado))
        self.amostras += 1
        return self.timeout

    def aplicar_recuo(self, timeout):
        return self.limitar(2 * timeout) if self.modo == "adaptive" else self.timeout

    def campos_metricas(self):
        return {
            "rtt_est_ms": self.rtt_estimado * 1000 if self.amostras else "",
            "dev_rtt_ms": self.desvio_rtt * 1000 if self.amostras else "",
            "timeout_ms": self.timeout * 1000,
        }

    def resumo(self):
        return {
            "timeout_mode": self.modo, "alpha": self.alpha, "beta": self.beta,
            "rto_min_s": self.minimo, "rto_max_s": self.maximo,
            "rto_final_s": self.timeout, "amostras_rtt": self.amostras,
            "rtt_estimado_final_s": self.rtt_estimado,
            "dev_rtt_final_s": self.desvio_rtt,
        }
