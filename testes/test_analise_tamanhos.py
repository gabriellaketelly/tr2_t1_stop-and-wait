"""Comparações dos três tamanhos sem misturar conteúdo ou condições de perda."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analisar_rtt
import graficos_rtt
from testes.test_experimentos_rtt import criar_resultado_exemplo


def criar_coleta(pasta, arquivo="large", **opcoes):
    resumo = criar_resultado_exemplo(pasta, **opcoes)
    resumo["arquivo"] = arquivo
    (pasta / "resumo.json").write_text(json.dumps(resumo))
    return resumo


class TestesComparacaoTamanhos(unittest.TestCase):
    def test_cada_tamanho_preserva_seu_contexto_e_suas_medias(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            for indice, arquivo in enumerate(analisar_rtt.ARQUIVOS_OBRIGATORIOS, 1):
                for protocolo, modo in analisar_rtt.CONFIGURACOES_OBRIGATORIAS:
                    criar_coleta(raiz / arquivo / f"{protocolo}-{modo}", arquivo,
                                 protocolo=protocolo, modo=modo, perda=0,
                                 tamanho=indice * 4, vazao=indice * 1000)
            registros, avisos = analisar_rtt.coletar_resultados([raiz])
            self.assertEqual(avisos, [])
            tabelas = analisar_rtt.montar_tabelas_integradas(registros, analisar_rtt.agrupar_resultados(registros))
            for indice, arquivo in enumerate(analisar_rtt.ARQUIVOS_OBRIGATORIOS, 1):
                tabela = tabelas[arquivo]
                self.assertEqual(tabela["ausentes"], [])
                self.assertEqual(tabela["contexto_integrado"]["arquivo"], arquivo)
                self.assertEqual(tabela["contexto_integrado"]["file_size"], indice * 4)
                self.assertTrue(all(linha["throughput_medio_bps"] == indice * 1000
                                    for linha in tabela["integrados"]))
                self.assertTrue(all(linha["n"] == 1 for linha in tabela["integrados"]))

    def test_mesmo_nome_e_tamanho_com_md5_distinto_nao_completa_tabela(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_coleta(raiz / "saw", "small", protocolo="SAW", modo="fixed", perda=0)
            resumo = criar_coleta(raiz / "gbn", "small", protocolo="GBN", modo="fixed", perda=0)
            resumo["md5_esperado"] = resumo["md5_recebido"] = hashlib.md5(b"bbbb").hexdigest()
            (raiz / "gbn" / "arquivo.bin").write_bytes(b"bbbb")
            (raiz / "gbn" / "resumo.json").write_text(json.dumps(resumo))
            registros, _ = analisar_rtt.coletar_resultados([raiz])
            grupos = analisar_rtt.agrupar_resultados(registros)
            linhas, contexto = analisar_rtt.montar_tabela_integrada(registros, grupos, "small")
            self.assertEqual(sum(linha["status"] == "medido" for linha in linhas), 1)
            self.assertEqual({linha["contexto_id"] for linha in linhas}, {contexto["contexto_id"]})

    def test_perda_alta_nao_entra_na_comparacao_sem_perda(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_coleta(raiz / "zero", "medium", modo="fixed", perda=0, vazao=100)
            criar_coleta(raiz / "loss", "medium", modo="adaptive", perda=.1, vazao=10000)
            registros, _ = analisar_rtt.coletar_resultados([raiz])
            grupos = analisar_rtt.agrupar_resultados(registros)
            linhas, contexto = analisar_rtt.montar_tabela_integrada(registros, grupos, "medium")
            self.assertEqual(contexto["loss_rate"], 0)
            medidos = [linha for linha in linhas if linha["status"] == "medido"]
            self.assertEqual(len(medidos), 1)
            self.assertEqual(medidos[0]["timeout_mode"], "fixed")
            linhas, contexto = analisar_rtt.montar_tabela_integrada(registros, grupos, "medium", .1)
            self.assertEqual(contexto["loss_rate"], .1)
            self.assertEqual([linha["timeout_mode"] for linha in linhas if linha["status"] == "medido"], ["adaptive"])

    def test_manifestos_complementares_respeitam_status_e_deduplicacao(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            complemento = raiz / "complemento" / "small"
            criar_coleta(raiz / "large", "large", perda=0)
            criar_coleta(complemento / "ok", "small", perda=0)
            criar_coleta(complemento / "failed", "medium", perda=0)
            cenario = {"id": "small-sr", "arquivo": "small"}
            (raiz / "manifesto.json").write_text(json.dumps({"runs": [
                {"id": "large", "status": "success", "summary": "large/resumo.json"},
                {"id": "small", "status": "success", "summary": "complemento/small/ok/resumo.json"},
            ], "specification": {"scenarios": [cenario]}}))
            (complemento / "manifesto.json").write_text(json.dumps({"runs": [
                {"id": "small", "status": "success", "summary": "ok/resumo.json"},
                {"id": "failed", "status": "failed", "summary": "failed/resumo.json"},
            ], "specification": {"scenarios": [cenario]}}))
            registros, avisos = analisar_rtt.coletar_resultados([raiz])
            self.assertEqual(sorted(registro["arquivo"] for registro in registros), ["large", "small"])
            self.assertTrue(any("failed" in aviso for aviso in avisos))
            self.assertEqual(analisar_rtt.listar_cenarios_planejados([raiz, complemento]), [cenario])

    def test_ausencias_por_tamanho_csv_e_alias_large(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            criar_coleta(raiz / "large", "large", modo="fixed", perda=0)
            with contextlib.redirect_stdout(io.StringIO()):
                analisar_rtt.principal(["--input-dir", str(raiz), "--no-plots"])
            analise = json.loads((raiz / "analise" / "analise.json").read_text())
            self.assertEqual(analise["integrados"], analise["integrados_por_arquivo"]["large"])
            self.assertEqual(analise["contexto_integrado"], analise["contextos_integrados"]["large"])
            for arquivo in ("small", "medium"):
                self.assertIsNone(analise["contextos_integrados"][arquivo])
                self.assertEqual(len(analise["configuracoes_ausentes_por_arquivo"][arquivo]), 5)
                self.assertTrue(any(f"de {arquivo} incompleta" in aviso for aviso in analise["avisos"]))
                self.assertTrue((raiz / "analise" / f"integrados_{arquivo}.csv").is_file())
            with patch.object(graficos_rtt.shutil, "which", return_value=None):
                graficos_rtt._gerar_graficos_svg(raiz / "analise", analise)
            pasta = raiz / "analise" / "graficos"
            for arquivo in ("small", "medium", "large"):
                self.assertIn(arquivo, (pasta / f"throughput_integrado_{arquivo}.svg").read_text())
            self.assertEqual((pasta / "throughput_integrado.svg").read_bytes(),
                             (pasta / "throughput_integrado_large.svg").read_bytes())


if __name__ == "__main__":
    unittest.main()
