import unittest

from correlacionar_captura import (
    correlacionar_medicoes,
    identificar_retransmissoes,
    validar_sessao_unica,
)


class TestesCaptura(unittest.TestCase):
    def test_reuso_da_porta_nao_mistura_transferencias(self):
        eventos = [{"event": evento} for evento in ("HELLO", "OK", "REQ", "DATA", "FIN", "DONE", "HELLO")]
        with self.assertRaisesRegex(ValueError, "mais de uma sessão"):
            validar_sessao_unica(eventos)
        validar_sessao_unica(eventos[:-1])
        validar_sessao_unica([{"event": "HELLO"}, {"event": "HELLO"}, {"event": "REQ"}])

    def test_correlaciona_rtt_aplica_karn(self):
        pacotes = [
            dict(frame=1, timestamp_epoch=100.0, event="REQ", seq=7),
            dict(frame=2, timestamp_epoch=100.022, event="DATA", seq=7),
            dict(frame=3, timestamp_epoch=100.1, event="REQ", seq=8),
            dict(frame=4, timestamp_epoch=100.3, event="REQ", seq=8),
            dict(frame=5, timestamp_epoch=100.322, event="DATA", seq=8),
        ]
        linhas = [
            dict(seq="7", rtt_ms="22.2", req_timestamp_epoch="99.9999",
                 data_timestamp_epoch="100.0221", rtt_sample_valid="1"),
            dict(seq="8", rtt_ms="", req_timestamp_epoch="100.3",
                 data_timestamp_epoch="100.322", rtt_sample_valid="0"),
        ]
        correspondencias, ausentes = correlacionar_medicoes(pacotes, linhas)
        self.assertEqual(ausentes, [])
        self.assertEqual(len(correspondencias), 1)
        self.assertEqual(correspondencias[0]["req_frame"], 1)
        self.assertEqual(correspondencias[0]["data_frame"], 2)
        self.assertAlmostEqual(correspondencias[0]["rtt_wireshark_ms"], 22)
        self.assertAlmostEqual(correspondencias[0]["diferenca_ms"], .2)
        retransmissoes = identificar_retransmissoes(pacotes)
        self.assertEqual(len(retransmissoes), 1)
        self.assertEqual(retransmissoes[0]["original_frame"], 3)
        self.assertEqual(retransmissoes[0]["retransmitted_frame"], 4)
        self.assertAlmostEqual(retransmissoes[0]["delta_original_ms"], 200)

    def test_nao_correlaciona_csv_de_outra_sessao(self):
        pacotes = [dict(frame=1, timestamp_epoch=1, event="REQ", seq=0),
                   dict(frame=2, timestamp_epoch=1.02, event="DATA", seq=0)]
        linhas = [dict(seq="0", rtt_ms="20", req_timestamp_epoch="100",
                     data_timestamp_epoch="100.02", rtt_sample_valid="1")]
        correspondencias, ausentes = correlacionar_medicoes(pacotes, linhas)
        self.assertEqual(correspondencias, [])
        self.assertEqual(ausentes, [0])


if __name__ == "__main__":
    unittest.main()
