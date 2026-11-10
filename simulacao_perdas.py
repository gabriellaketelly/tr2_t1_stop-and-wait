"""Descartes reproduzíveis de DATA no receptor, sem interferir no transporte."""

import hashlib
import math
import random


class SimuladorPerdas:
    """Perda no receptor, reproduzível por semente, segmento e tentativa.

    DATA não ecoa tentativa: a chave usa a tentativa atual do cliente, tal
    como os temporizadores. Sem semente, usa um gerador privado aleatório.
    """

    def __init__(self, taxa, semente=None):
        if not math.isfinite(taxa) or not 0 <= taxa <= 1:
            raise ValueError("probabilidade de perda deve estar entre 0 e 1")
        self.taxa = taxa
        self.semente = semente
        self.gerador = random.Random()

    def descartar(self, sequencia, tentativa):
        # Garante os extremos inclusive diante do arredondamento int/float.
        if self.taxa == 0:
            return False
        if self.taxa == 1:
            return True
        if self.semente is None:
            valor = self.gerador.random()
        else:
            chave = f"rdt-loss-v1:{self.semente}:{sequencia}:{tentativa}".encode("ascii")
            valor = int.from_bytes(hashlib.sha256(chave).digest()[:8], "big") / 2**64
        return valor < self.taxa
