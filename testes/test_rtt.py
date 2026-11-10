"""Valida lógica com relógio e datagramas em memória; não mede desempenho."""

import contextlib
import csv
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cliente_gbn
import cliente_sr
from configuracao_clientes import analisar_argumentos
from rtt import EstimadorRTT
from simulacao_perdas import SimuladorPerdas
from testes.apoio_rtt import DatagramasSimulados


class TestesEstimadorRTT(unittest.TestCase):
    def test_inicializacao_e_formulas_do_enunciado(self):
        estimador = EstimadorRTT(.2, modo="adaptive")
        self.assertEqual(estimador.timeout, .2)
        self.assertAlmostEqual(estimador.atualizar(.022), .066)
        self.assertAlmostEqual(estimador.rtt_estimado, .022)
        self.assertAlmostEqual(estimador.desvio_rtt, .011)
        estimador.atualizar(.030)
        self.assertAlmostEqual(estimador.rtt_estimado, .023)
        self.assertAlmostEqual(estimador.desvio_rtt, .010)
        self.assertAlmostEqual(estimador.timeout, .063)

    def test_constante_converge_e_responde_a_degrau(self):
        estimador = EstimadorRTT(.2, minimo=.001, modo="adaptive")
        for _ in range(100):
            estimador.atualizar(.022)
        self.assertAlmostEqual(estimador.timeout, .022, places=8)
        anterior = estimador.timeout
        estimador.atualizar(.080)
        self.assertGreater(estimador.timeout, anterior)
        self.assertGreater(estimador.desvio_rtt, .01)

    def test_modo_fixo_mede_sem_alterar_timeout(self):
        estimador = EstimadorRTT(.2)
        estimador.atualizar(.022)
        estimador.atualizar(.1)
        self.assertEqual(estimador.timeout, .2)
        self.assertEqual(estimador.aplicar_recuo(.2), .2)
        self.assertEqual(estimador.amostras, 2)

    def test_limites_e_recuo(self):
        estimador = EstimadorRTT(.2, minimo=.01, maximo=.5, modo="adaptive")
        self.assertEqual(estimador.atualizar(.0001), .01)
        self.assertEqual(estimador.atualizar(2), .5)
        self.assertEqual(estimador.aplicar_recuo(.4), .5)
        with self.assertRaises(ValueError):
            estimador.atualizar(float("nan"))

    def test_argumentos_rejeitam_parametros_invalidos(self):
        for opcoes in (("--alpha", "0"), ("--beta", "1.1"), ("--alpha", "nan"),
                      ("--timeout", "inf"), ("--rto-min", "0"),
                      ("--rto-max", ".001"), ("--loss-rate", "nan")):
            with self.subTest(opcoes=opcoes), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    analisar_argumentos(["--group", "grupo08", *opcoes])

    def test_perdas_reproduziveis_independentes_da_ordem(self):
        ordem_direta = SimuladorPerdas(.1, 42)
        ordem_inversa = SimuladorPerdas(.1, 42)
        esperado = {sequencia: ordem_direta.descartar(sequencia, 1) for sequencia in range(200)}
        obtido = {sequencia: ordem_inversa.descartar(sequencia, 1) for sequencia in reversed(range(200))}
        self.assertEqual(esperado, obtido)
        self.assertTrue(any(obtido.values()))
        self.assertFalse(all(obtido.values()))
        self.assertFalse(SimuladorPerdas(0, 42).descartar(0, 1))
        self.assertTrue(SimuladorPerdas(1, 42).descartar(0, 1))


class TestesTemporizadoresClientes(unittest.TestCase):
    def executar_transferencia(self, protocolo, modo="adaptive", descartes=1, reordenar=False):
        conteudo = b"a|\xff\x00" * 6 + b"xy"
        conexao = DatagramasSimulados(conteudo, descartes, reordenar)
        informacoes = dict(file_size=len(conteudo), total_segments=7, segment_size=4,
                    checksum=hashlib.md5(conteudo).hexdigest(), seed="unit-test")
        with tempfile.TemporaryDirectory() as temporario:
            argumentos = analisar_argumentos([
                "--group", "grupo08", "--segment-size", "4", "--window-size", "4",
                "--timeout", ".2", "--timeout-mode", modo, "--rto-max", ".8",
                "--max-retries", "4", "--output-dir", temporario,
            ])
            funcao = (cliente_sr.baixar_com_repeticao_seletiva if protocolo == "sr"
                      else cliente_gbn.baixar_com_go_back_n)
            with patch("time.perf_counter", side_effect=lambda: conexao.agora), \
                    patch("time.time", side_effect=lambda: 1700000000 + conexao.agora), \
                    contextlib.redirect_stdout(io.StringIO()):
                resumo = funcao(conexao, argumentos, informacoes)
            diretorio = Path(temporario) / protocolo / "small"
            self.assertEqual((diretorio / "arquivo.bin").read_bytes(), conteudo)
            self.assertTrue(resumo["checksum_ok"] and resumo["done_ok"])
            with (diretorio / "metricas.csv").open() as origem:
                linhas = list(csv.DictReader(origem))
            with (diretorio / "eventos.csv").open() as origem:
                eventos = list(csv.DictReader(origem))
            self.assertEqual(sum(int(r["retransmissoes"]) for r in linhas), resumo["retransmissoes"])
            self.assertEqual(sum(int(r["rtt_sample_valid"]) for r in linhas), resumo["amostras_rtt"])
            self.assertEqual([int(r["seq"]) for r in linhas], list(range(7)))
            return resumo, linhas, eventos

    def test_sr_perda_retransmite_apenas_segmento_e_karn(self):
        resumo, linhas, eventos = self.executar_transferencia("sr")
        self.assertEqual(resumo["retransmissoes"], 1)
        self.assertEqual(resumo["amostras_rtt"], 6)
        self.assertEqual(linhas[0]["rtt_ms"], "")
        self.assertEqual(float(linhas[0]["timeout_usado_ms"]), 400)
        for linha in linhas[1:4]:
            self.assertAlmostEqual(float(linha["rtt_ms"]), 22)
            self.assertEqual(float(linha["timeout_usado_ms"]), 200)

    def test_sr_usa_recebimento_em_vez_de_escrita_do_buffer(self):
        resumo, linhas, eventos = self.executar_transferencia("sr", descartes=0, reordenar=True)
        self.assertEqual(resumo["retransmissoes"], 0)
        self.assertAlmostEqual(float(linhas[1]["rtt_est_ms"]), 22)
        self.assertGreater(float(linhas[0]["rtt_est_ms"]), 22)
        self.assertLess(float(linhas[1]["received_elapsed_s"]), float(linhas[0]["received_elapsed_s"]))

    def test_gbn_retransmite_janela_e_exclui_amostras_ambiguas(self):
        resumo, linhas, eventos = self.executar_transferencia("gbn")
        self.assertEqual(resumo["retransmissoes"], 4)
        self.assertEqual(resumo["amostras_rtt"], 3)
        self.assertTrue(all(linha["rtt_ms"] == "" for linha in linhas[:4]))
        self.assertTrue(any(evento["event"] == "DISCARD" for evento in eventos))

    def test_recuo_repetido_e_timeout_fixo(self):
        for protocolo in ("sr", "gbn"):
            with self.subTest(protocolo=protocolo):
                _, _, eventos_adaptativos = self.executar_transferencia(protocolo, descartes=2)
                _, _, eventos_fixos = self.executar_transferencia(protocolo, modo="fixed", descartes=2)
                obter_timeouts = lambda eventos: [float(e["timeout_ms"]) for e in eventos
                                          if e["event"] == "REQ" and e["seq"] == "0"]
                self.assertEqual(obter_timeouts(eventos_adaptativos), [200, 400, 800])
                self.assertEqual(obter_timeouts(eventos_fixos), [200, 200, 200])

    def test_trafego_invalido_nao_adia_limite(self):
        for funcao in (cliente_gbn.baixar_com_go_back_n,
                       cliente_sr.baixar_com_repeticao_seletiva):
            with self.subTest(funcao=funcao.__name__), tempfile.TemporaryDirectory() as temporario:
                conexao = DatagramasSimulados(b"abcd", ruido=True)
                argumentos = analisar_argumentos(["--group", "grupo08", "--timeout", ".02",
                                              "--max-retries", "0", "--output-dir", temporario])
                informacoes = dict(file_size=4, total_segments=1, segment_size=4,
                            checksum=hashlib.md5(b"abcd").hexdigest(), seed="unit-test")
                with patch("time.perf_counter", side_effect=lambda: conexao.agora), \
                        patch("time.time", side_effect=lambda: 1700000000 + conexao.agora):
                    with self.assertRaises(TimeoutError):
                        funcao(conexao, argumentos, informacoes)
                self.assertLessEqual(conexao.agora, .025)
                self.assertFalse(list(Path(temporario).rglob("arquivo.bin")))


if __name__ == "__main__":
    unittest.main()
