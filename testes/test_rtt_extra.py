"""Casos de fronteira dos clientes; datagramas em memória, sem rede."""

import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cliente_gbn
import cliente_sr
from protocolo_rdt import ErroProtocolo
from configuracao_clientes import analisar_argumentos
from simulacao_perdas import SimuladorPerdas
from testes.apoio_rtt import DatagramasSimulados


class DatagramasComDoneNegativo(DatagramasSimulados):
    def send(self, pacote):
        if pacote.startswith(b"FIN"):
            self.enviados.append((self.agora, pacote))
            self.agendar(.005, b"DONE|ok=0")
            return len(pacote)
        return super().send(pacote)


class TestesLimitesClientes(unittest.TestCase):
    protocolos = (("gbn", cliente_gbn.baixar_com_go_back_n),
                  ("sr", cliente_sr.baixar_com_repeticao_seletiva))

    def criar_argumentos(self, diretorio, *opcoes):
        return analisar_argumentos([
            "--group", "grupo08", "--segment-size", "4", "--window-size", "4",
            "--timeout", ".05", "--timeout-mode", "adaptive",
            "--rto-max", ".1", "--max-retries", "2", "--output-dir", diretorio,
            *opcoes,
        ])

    def criar_informacoes(self, conteudo):
        return dict(file_size=len(conteudo), total_segments=(len(conteudo) + 3) // 4,
                    segment_size=4, checksum=hashlib.md5(conteudo).hexdigest(),
                    seed="unit-test")

    def executar_transferencia(self, funcao, conexao, argumentos, informacoes):
        with patch("time.perf_counter", side_effect=lambda: conexao.agora), \
                patch("time.time", side_effect=lambda: 1700000000 + conexao.agora), \
                contextlib.redirect_stdout(io.StringIO()):
            return funcao(conexao, argumentos, informacoes)

    def test_perda_cem_porcento_termina_no_limite(self):
        conteudo = b"abcdefghij"
        for nome, funcao in self.protocolos:
            with self.subTest(protocolo=nome), tempfile.TemporaryDirectory() as diretorio:
                conexao = DatagramasSimulados(conteudo, tentativas_descartadas=0)
                argumentos = self.criar_argumentos(diretorio, "--loss-rate", "1", "--loss-seed", "42")
                with self.assertRaises(TimeoutError):
                    self.executar_transferencia(funcao, conexao, argumentos, self.criar_informacoes(conteudo))
                self.assertEqual(conexao.requisicoes, {0: 3, 1: 3, 2: 3})
                self.assertLessEqual(conexao.agora, .251)
                destino = Path(diretorio) / nome / "small"
                self.assertFalse((destino / "arquivo.bin").exists())
                self.assertFalse((destino / "resumo.json").exists())
                with (destino / "metricas.csv").open() as origem:
                    self.assertEqual(list(csv.DictReader(origem)), [])

    def test_md5_ou_done_negativo_nao_publica_arquivo(self):
        conteudo = b"abcdx"
        for nome, funcao in self.protocolos:
            for falha in ("checksum", "done"):
                with self.subTest(protocolo=nome, falha=falha), \
                        tempfile.TemporaryDirectory() as diretorio:
                    transporte = DatagramasComDoneNegativo if falha == "done" else DatagramasSimulados
                    conexao = transporte(conteudo, tentativas_descartadas=0)
                    informacoes = self.criar_informacoes(conteudo)
                    if falha == "checksum":
                        informacoes["checksum"] = "0" * 32
                    with self.assertRaises(ErroProtocolo):
                        self.executar_transferencia(
                            funcao, conexao, self.criar_argumentos(diretorio), informacoes,
                        )
                    destino = Path(diretorio) / nome / "small"
                    self.assertFalse((destino / "arquivo.bin").exists())
                    self.assertEqual((destino / "arquivo.part").read_bytes(), conteudo)
                    resumo = json.loads((destino / "resumo.json").read_text())
                    self.assertEqual(resumo["checksum_ok"], falha != "checksum")
                    self.assertEqual(resumo["done_ok"], falha != "done")

    def test_instantes_correspondem_a_req_data_e_rtt(self):
        conteudo = b"abcdefghijklmnopx"
        for nome, funcao in self.protocolos:
            with self.subTest(protocolo=nome), tempfile.TemporaryDirectory() as diretorio:
                conexao = DatagramasSimulados(conteudo, tentativas_descartadas=0)
                self.executar_transferencia(
                    funcao, conexao, self.criar_argumentos(diretorio),
                    self.criar_informacoes(conteudo),
                )
                destino = Path(diretorio) / nome / "small"
                with (destino / "metricas.csv").open() as origem:
                    linhas = list(csv.DictReader(origem))
                with (destino / "eventos.csv").open() as origem:
                    eventos = list(csv.DictReader(origem))
                self.assertEqual(set(conexao.requisicoes), set(range(5)))
                self.assertTrue(all(n == 1 for n in conexao.requisicoes.values()))
                for linha in linhas:
                    req = next(evento for evento in eventos
                               if evento["seq"] == linha["seq"] and evento["event"] == "REQ")
                    data = next(evento for evento in eventos
                                if evento["seq"] == linha["seq"] and evento["event"] == "DATA")
                    self.assertEqual(linha["req_timestamp_epoch"], req["timestamp_epoch"])
                    self.assertEqual(linha["data_timestamp_epoch"], data["timestamp_epoch"])
                    self.assertAlmostEqual(float(linha["rtt_ms"]), 22)
                    medido = float(linha["data_timestamp_epoch"]) - float(linha["req_timestamp_epoch"])
                    self.assertAlmostEqual(medido * 1000, float(linha["rtt_ms"]), places=3)

    def test_perda_valida_extremos_sem_sorteio(self):
        for semente in (None, 0, 42):
            self.assertFalse(SimuladorPerdas(0, semente).descartar(0, 1))
            self.assertTrue(SimuladorPerdas(1, semente).descartar(0, 1))
        for taxa in (-1, 2, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                SimuladorPerdas(taxa)


if __name__ == "__main__":
    unittest.main()
