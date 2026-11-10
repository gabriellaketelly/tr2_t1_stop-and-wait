"""Testes sem tráfego de rede: orquestração e seleção de evidências remotas."""

import contextlib
import csv
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import analisar_rtt
import executar_experimentos_rtt as executor
from validacao_metricas import validar_csv_metricas


def criar_resultado_exemplo(raiz, protocolo="SR", modo="adaptive", vazao=1000.0,
                   alfa=.125, beta=.25, perda=.05, repeticao=1,
                   servidor=executor.SERVIDOR_REMOTO, tamanho=4):
    pasta = Path(raiz)
    pasta.mkdir(parents=True, exist_ok=True)
    dados = b"a" * tamanho
    checksum = hashlib.md5(dados).hexdigest()
    resumo = {"servidor": servidor, "porta": 8080, "grupo": "grupo08", "arquivo": "large",
               "file_size": tamanho, "segment_size": 512, "md5_esperado": checksum,
               "md5_recebido": checksum, "checksum_ok": True, "done_ok": True,
               "protocolo": protocolo, "janela": 1 if protocolo == "SAW" else 16,
               "timeout_mode": modo, "alpha": alfa, "beta": beta, "loss_rate": perda,
               "timeout_s": .2, "rto_min_s": .01, "rto_max_s": 60.,
               "throughput_medido_bps": vazao, "duracao_s": tamanho * 8 / vazao,
               "retransmissoes": 2, "repeticao": repeticao, "loss_seed": 40 + repeticao,
               "rtt_medio_s": .022, "total_segments": (tamanho + 511) // 512}
    (pasta / "resumo.json").write_text(json.dumps(resumo), encoding="utf-8")
    with (pasta / "metricas.csv").open("w", newline="", encoding="utf-8") as destino:
        escritor = csv.writer(destino)
        escritor.writerow(("seq", "bytes", "rtt_ms"))
        for sequencia in range(resumo["total_segments"]):
            escritor.writerow((sequencia, min(512, tamanho - sequencia * 512), 22))
    (pasta / "arquivo.bin").write_bytes(dados)
    return resumo


class TestesExecutorExperimentos(unittest.TestCase):
    def test_nomes_configuracoes_preservam_precisao_dos_parametros(self):
        argumentos = executor.analisar_argumentos(["--repetitions", "1", "--modes", "adaptive",
                                  "--parameter-pairs", ".1250001:.25", ".1250002:.25",
                                  "--loss-rates", ".05000001", ".05000002"])
        configuracoes = executor.montar_cenarios(argumentos)
        self.assertEqual(len(configuracoes), 4)
        self.assertEqual(len({configuracao["id"] for configuracao in configuracoes}), 4)
        self.assertEqual(len({executor.nomear_csv(configuracao) for configuracao in configuracoes}), 4)

    def test_nomes_configuracoes_padrao_permanecem_compativeis(self):
        argumentos = executor.analisar_argumentos(["--repetitions", "1", "--modes", "adaptive",
                                  "--parameter-pairs", ".125:.25", "--loss-rates", ".05"])
        configuracao = executor.montar_cenarios(argumentos)[0]
        self.assertEqual(configuracao["id"], "sr-w16-loss5-adaptive_a0.125_b0.25-rep01")
        self.assertEqual(executor.nomear_csv(configuracao),
                         "resultado_SR_w16_loss5_adaptive_alpha0.125_beta0.25_rep01.csv")

    def test_matriz_usa_apenas_remoto_e_sementes_pareadas(self):
        argumentos = executor.analisar_argumentos(["--protocols", "SR", "GBN", "--repetitions", "2", "--baseline"])
        configuracoes = executor.montar_cenarios(argumentos)
        self.assertEqual(len(configuracoes), 38)
        for configuracao in configuracoes:
            self.assertEqual(configuracao["servidor"], executor.SERVIDOR_REMOTO)
            self.assertEqual(configuracao["loss_seed"], argumentos.seed + configuracao["repeticao"] - 1)
            comando = executor.montar_comando(configuracao, Path("out"))
            self.assertEqual(comando[comando.index("--server") + 1], executor.SERVIDOR_REMOTO)
            if configuracao["protocolo"] == "SAW":
                self.assertNotIn("--loss-rate", comando)
                self.assertNotIn("--timeout-mode", comando)
        self.assertEqual(configuracoes, executor.montar_cenarios(argumentos))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            executor.analisar_argumentos(["--server", "127.0.0.1"])

    def test_simulacao_comandos_nao_cria_arquivos_nem_envia_pacotes(self):
        with tempfile.TemporaryDirectory() as temporario:
            destino = Path(temporario) / "not-created"
            with patch.object(executor, "verificar_servidor") as rede, patch.object(executor.subprocess, "run") as processo:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(executor.principal(["--dry-run", "--output-dir", str(destino)]), 0)
                rede.assert_not_called()
                processo.assert_not_called()
            self.assertFalse(destino.exists())

    def test_falha_verificacao_fica_registrada_sem_iniciar_coleta(self):
        with tempfile.TemporaryDirectory() as temporario:
            with patch.object(executor, "negociar_sessao", side_effect=TimeoutError("sem OK")), \
                    patch.object(executor.socket, "socket"), patch.object(executor.subprocess, "run") as processo:
                with contextlib.redirect_stdout(io.StringIO()):
                    codigo = executor.principal(["--output-dir", temporario])
            self.assertEqual(codigo, 1)
            processo.assert_not_called()
            manifesto = json.loads((Path(temporario) / "manifesto.json").read_text())
            self.assertEqual(manifesto["runs"], [])
            self.assertEqual(manifesto["preflights"][0]["status"], "failed")
            self.assertEqual(list(Path(temporario).rglob("resumo.json")), [])

    def test_retomada_preserva_dados_concluidos(self):
        def simular_cliente_concluido(comando, **opcoes):
            destino = Path(comando[comando.index("--output-dir") + 1]) / "sr" / "large"
            resumo = criar_resultado_exemplo(destino, modo="fixed", repeticao=1)
            resumo["loss_seed"] = int(comando[comando.index("--loss-seed") + 1])
            (destino / "resumo.json").write_text(json.dumps(resumo))
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as temporario:
            argumentos = ["--output-dir", temporario, "--skip-preflight", "--repetitions", "1",
                         "--modes", "fixed", "--loss-rates", ".05", "--interval", "0"]
            with patch.object(executor.subprocess, "run", side_effect=simular_cliente_concluido) as processo:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(executor.principal(argumentos), 0)
                    self.assertEqual(executor.principal(argumentos + ["--resume"]), 0)
            self.assertEqual(processo.call_count, 1)
            manifesto = json.loads((Path(temporario) / "manifesto.json").read_text())
            self.assertEqual(len(manifesto["runs"]), 1)
            self.assertEqual(manifesto["runs"][0]["status"], "success")

    def test_validacao_rejeita_configuracao_divergente(self):
        argumentos = executor.analisar_argumentos(["--repetitions", "1", "--loss-rates", ".05",
                                  "--modes", "adaptive", "--parameter-pairs", ".125:.25", "--seed", "41"])
        configuracao = executor.montar_cenarios(argumentos)[0]
        with tempfile.TemporaryDirectory() as temporario:
            resumo = criar_resultado_exemplo(temporario)
            caminho = Path(temporario) / "resumo.json"
            executor.validar_resultado(caminho, configuracao)
            resumo["alpha"] = .5
            caminho.write_text(json.dumps(resumo))
            with self.assertRaisesRegex(ValueError, "alpha"):
                executor.validar_resultado(caminho, configuracao)

    def test_parametros_rejeitam_valores_nao_finitos(self):
        for argumentos in (["--timeout", "nan"], ["--loss-rates", "inf"],
                          ["--parameter-pairs", "0.1:nan"], ["--repetitions", "0"]):
            with self.subTest(arguments=argumentos), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                executor.analisar_argumentos(argumentos)

    def test_validacao_rejeita_md5_recebido_incorreto(self):
        argumentos = executor.analisar_argumentos(["--repetitions", "1", "--loss-rates", ".05",
                                  "--modes", "adaptive", "--parameter-pairs", ".125:.25", "--seed", "41"])
        configuracao = executor.montar_cenarios(argumentos)[0]
        with tempfile.TemporaryDirectory() as temporario:
            resumo = criar_resultado_exemplo(temporario)
            resumo["md5_recebido"] = "0" * 32
            caminho = Path(temporario) / "resumo.json"
            caminho.write_text(json.dumps(resumo))
            with self.assertRaisesRegex(ValueError, "MD5"):
                executor.validar_resultado(caminho, configuracao)


class TestesAnalise(unittest.TestCase):
    def test_analise_vazia_indica_ausencias_sem_inventar_resultados(self):
        with tempfile.TemporaryDirectory() as temporario:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(analisar_rtt.principal(["--input-dir", temporario, "--no-plots"]), 0)
            resultado = json.loads((Path(temporario) / "analise" / "analise.json").read_text())
            self.assertEqual(resultado["execucoes"], [])
            self.assertEqual(resultado["selecao_parametros"], [])
            self.assertTrue(all(linha["status"] == "ausente" for linha in resultado["integrados"]))
            self.assertTrue(all(linha["throughput_medio_bps"] is None for linha in resultado["integrados"]))

    def test_resultados_locais_falhos_ou_incompletos_sao_excluidos(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_resultado_exemplo(raiz / "local", servidor="127.0.0.1")
            criar_resultado_exemplo(raiz / "remote")
            criar_resultado_exemplo(raiz / "partial")
            caminho = raiz / "partial" / "resumo.json"
            resumo = json.loads(caminho.read_text())
            resumo["done_ok"] = False
            caminho.write_text(json.dumps(resumo))
            registros, avisos = analisar_rtt.coletar_resultados([raiz])
            self.assertEqual(len(registros), 1)
            self.assertEqual(len(avisos), 2)
            (raiz / "manifesto.json").write_text(json.dumps({"runs": [
                {"id": "remote", "status": "failed", "summary": "remote/resumo.json"}]}))
            registros, avisos = analisar_rtt.coletar_resultados([raiz])
            self.assertEqual(registros, [])

    def test_comparacao_parametros_usa_apenas_condicoes_comuns(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_resultado_exemplo(raiz / "a1", vazao=1000)
            criar_resultado_exemplo(raiz / "a2", vazao=9000, repeticao=2)
            criar_resultado_exemplo(raiz / "b1", vazao=2000, alfa=.25, beta=.5)
            registros, _ = analisar_rtt.coletar_resultados([raiz])
            selecao = analisar_rtt.selecionar_parametros(registros)[0]
            self.assertEqual(selecao["escolhido"]["alpha"], .25)
            self.assertEqual(selecao["escolhido"]["n"], 1)
            self.assertEqual(len(selecao["condicoes_comuns"]), 1)

    def test_par_parametros_sem_coleta_impede_escolha(self):
        argumentos = executor.analisar_argumentos(["--repetitions", "1", "--loss-rates", ".05", "--seed", "41"])
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_resultado_exemplo(raiz / "a", alfa=.125, beta=.25)
            criar_resultado_exemplo(raiz / "b", alfa=.25, beta=.5, vazao=2000)
            registros, _ = analisar_rtt.coletar_resultados([raiz])
            selecao = analisar_rtt.selecionar_parametros(registros, executor.montar_cenarios(argumentos))[0]
            self.assertIsNone(selecao["escolhido"])
            self.assertEqual(selecao["status"], "matriz_incompleta")
            self.assertEqual(len(selecao["configuracoes_ausentes"]), 1)

    def test_condicoes_duplicadas_bloqueiam_escolha_independente_da_ordem(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_resultado_exemplo(raiz / "first", vazao=1000)
            criar_resultado_exemplo(raiz / "duplicate", vazao=9000)
            criar_resultado_exemplo(raiz / "second_pair", alfa=.25, beta=.5, vazao=2000)
            pastas = [raiz / "first", raiz / "duplicate", raiz / "second_pair"]
            ordem_direta, _ = analisar_rtt.coletar_resultados(pastas)
            ordem_inversa, _ = analisar_rtt.coletar_resultados(list(reversed(pastas)))
            selecionado = analisar_rtt.selecionar_parametros(ordem_direta)
            self.assertEqual(selecionado, analisar_rtt.selecionar_parametros(ordem_inversa))
            self.assertIsNone(selecionado[0]["escolhido"])
            self.assertEqual(selecionado[0]["status"], "condicoes_ambiguas")
            self.assertEqual(len(selecionado[0]["condicoes_duplicadas"]), 1)
            self.assertEqual(len(selecionado[0]["condicoes_duplicadas"][0]["execucoes"]), 2)

    def test_historico_nao_entra_na_media_das_novas_coletas(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_resultado_exemplo(raiz / "old", vazao=100)
            criar_resultado_exemplo(raiz / "new", vazao=1000)
            registros, _ = analisar_rtt.coletar_resultados([raiz / "new"], [raiz / "old"])
            linhas = analisar_rtt.agrupar_resultados(registros)
            self.assertEqual(len(linhas), 2)
            self.assertEqual({linha["throughput_medio_bps"] for linha in linhas}, {100, 1000})

    def test_contagem_invalida_de_retransmissoes_e_excluida(self):
        with tempfile.TemporaryDirectory() as temporario:
            resumo = criar_resultado_exemplo(temporario)
            resumo["retransmissoes"] = None
            (Path(temporario) / "resumo.json").write_text(json.dumps(resumo))
            registros, avisos = analisar_rtt.coletar_resultados([Path(temporario)])
            self.assertEqual(registros, [])
            self.assertIn("retransmissões inválida", avisos[0])

    def test_tabela_integrada_nao_mistura_tamanhos_ou_perdas(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_resultado_exemplo(raiz / "saw", protocolo="SAW", modo="fixed", perda=0, tamanho=4)
            criar_resultado_exemplo(raiz / "gbn", protocolo="GBN", modo="fixed", perda=0, tamanho=8)
            criar_resultado_exemplo(raiz / "sr", protocolo="SR", modo="fixed", perda=.1, tamanho=4)
            registros, _ = analisar_rtt.coletar_resultados([raiz])
            integrados, contexto = analisar_rtt.montar_tabela_integrada(registros, analisar_rtt.agrupar_resultados(registros))
            self.assertEqual(sum(linha["status"] == "medido" for linha in integrados), 1)
            self.assertIsNotNone(contexto)

    def test_dispersao_amostral_fica_ausente_com_uma_repeticao(self):
        with tempfile.TemporaryDirectory() as temporario:
            criar_resultado_exemplo(temporario)
            registros, _ = analisar_rtt.coletar_resultados([Path(temporario)])
            linha = analisar_rtt.agrupar_resultados(registros)[0]
            self.assertEqual(linha["n"], 1)
            self.assertIsNone(linha["throughput_desvio_bps"])


class TestesValidacaoMetricas(unittest.TestCase):
    def test_csv_invalido_e_rejeitado_por_executor_e_analisador(self):
        argumentos = executor.analisar_argumentos(["--repetitions", "1", "--loss-rates", ".05",
                                  "--modes", "adaptive", "--parameter-pairs", ".125:.25", "--seed", "41"])
        configuracao = executor.montar_cenarios(argumentos)[0]
        invalidos = {
            "empty": "",
            "header_only": "seq,bytes,rtt_ms\n",
            "missing_segment": "seq,bytes,rtt_ms\n0,512,22\n",
            "duplicate": "seq,bytes,rtt_ms\n0,512,22\n0,512,22\n",
            "out_of_range": "seq,bytes,rtt_ms\n0,512,22\n2,1,22\n",
            "wrong_payload_size": "seq,bytes,rtt_ms\n0,512,22\n1,2,22\n",
            "truncated_row": "seq,bytes,rtt_ms\n0,512,22\n1,1",
            "extra_field": "seq,bytes,rtt_ms\n0,512,22\n1,1,22,extra\n",
        }
        for nome, conteudo in invalidos.items():
            with self.subTest(name=nome), tempfile.TemporaryDirectory() as temporario:
                raiz = Path(temporario)
                criar_resultado_exemplo(raiz, tamanho=513)
                (raiz / "metricas.csv").write_text(conteudo)
                with self.assertRaises(ValueError):
                    executor.validar_resultado(raiz / "resumo.json", configuracao)
                registros, avisos = analisar_rtt.coletar_resultados([raiz])
                self.assertEqual(registros, [])
                self.assertTrue(any("CSV" in aviso for aviso in avisos))

    def test_quantidade_segmentos_declarada_deve_corresponder_ao_arquivo(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            resumo = criar_resultado_exemplo(raiz, tamanho=513)
            resumo["total_segments"] = 3
            with self.assertRaisesRegex(ValueError, "total_segments"):
                validar_csv_metricas(raiz / "metricas.csv", resumo)

    def test_csv_completo_fora_de_ordem_e_rtt_karn_vazio_sao_validos(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            resumo = criar_resultado_exemplo(raiz, tamanho=513)
            (raiz / "metricas.csv").write_text("seq,bytes,rtt_ms\n1,1,\n0,512,22\n")
            self.assertEqual(validar_csv_metricas(raiz / "metricas.csv", resumo), 2)
            del resumo["total_segments"]
            self.assertEqual(validar_csv_metricas(raiz / "metricas.csv", resumo), 2)


if __name__ == "__main__":
    unittest.main()
