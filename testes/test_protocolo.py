import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock
import cliente


class ProtocolTests(unittest.TestCase):
    def test_payload_binario(self):
        payload = b'a|b\x00\xff|'
        self.assertEqual(cliente.parse_data(b'DATA|seq=2|total=6|' + payload), (2, 6, payload))

    def test_cabecalho_invalido(self):
        for packet in (b'DATA|seq=x|total=2|ab', b'DATA|seq=-1|total=2|ab', b'PONG'):
            with self.assertRaises(cliente.ProtocolError):
                cliente.parse_data(packet)

    def test_grupo_obrigatorio(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cliente.parse_args([])

    def test_udp_com_perda_e_sequencia_errada(self):
        content = b'ab|\xff012345'
        md5 = hashlib.md5(content).hexdigest()
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(('127.0.0.1', 0))
        port = server.getsockname()[1]
        server.settimeout(3)
        errors, events = [], []

        def serve():
            requests = {}
            try:
                while True:
                    packet, peer = server.recvfrom(65507)
                    events.append(packet)
                    if packet.startswith(b'HELLO'):
                        self.assertIn(b'grupo=grupo08', packet)
                        server.sendto(f'OK|file_size=10|checksum={md5}|seed=1|total_segments=3|segment_size=4'.encode(), peer)
                    elif packet.startswith(b'REQ'):
                        seq = int(packet.split(b'=')[1])
                        requests[seq] = requests.get(seq, 0) + 1
                        if seq == 0 and requests[seq] == 1:
                            continue
                        server.sendto(b'DATA|seq=99|total=10|xxxx', peer)
                        server.sendto(f'DATA|seq={seq}|total=10|'.encode() + content[seq * 4:(seq + 1) * 4], peer)
                    elif packet.startswith(b'FIN'):
                        self.assertEqual(packet, f'FIN|checksum={md5}'.encode())
                        server.sendto(b'DONE|ok=1', peer)
                        break
                    elif packet.startswith(b'ACK'):
                        server.sendto(b'ERROR|msg=tipo_desconhecido_ACK', peer)
            except Exception as exc:
                errors.append(exc)
            finally:
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as temporary:
            with contextlib.redirect_stdout(io.StringIO()):
                result = cliente.main(['--server', '127.0.0.1', '--port', str(port), '--group', 'grupo08', '--timeout', '0.05', '--output-dir', temporary])
            thread.join(4)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, 0)
            directory = Path(temporary) / 'small'
            self.assertEqual((directory / 'arquivo.bin').read_bytes(), content)
            summary = json.loads((directory / 'resumo.json').read_text())
            self.assertEqual(summary['retransmissoes'], 1)
            self.assertEqual(summary['amostras_rtt'], 2)
            self.assertTrue(summary['done_ok'])
            self.assertEqual(summary['avisos_servidor'], ['ack_nao_suportado'])
            self.assertLess(events.index(b'ACK|seq=0'), events.index(b'REQ|seq=1'))

    def test_apenas_erro_especifico_ack_tolerado(self):
        avisos = set()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(cliente.ack_nao_suportado(b'ERROR|msg=tipo_desconhecido_ACK ', avisos))
        self.assertFalse(cliente.ack_nao_suportado(b'ERROR|msg=sessao_invalida', avisos))

    def test_limite_de_tentativas_segmento(self):
        sock = Mock()
        sock.recv.side_effect = socket.timeout
        with self.assertRaises(TimeoutError):
            cliente.receber_segmento(sock, 7, 4, 4, .1, 2)
        self.assertEqual(sock.send.call_count, 3)
        self.assertTrue(all(call.args == (b'REQ|seq=7',) for call in sock.send.call_args_list))

    def test_limite_de_tentativas_handshake(self):
        sock = Mock()
        sock.recv.side_effect = socket.timeout
        with self.assertRaises(TimeoutError):
            cliente.exchange(sock, b'HELLO', b'OK', .1, 2)
        self.assertEqual(sock.send.call_count, 3)

    def verificar_falha_integridade(self, expected_md5, done):
        with tempfile.TemporaryDirectory() as temporary:
            args = cliente.parse_args(['--group', 'grupo08', '--output-dir', temporary])
            sock = Mock()
            sock.recv.side_effect = [b'DATA|seq=0|total=4|abcd', done]
            info = dict(file_size=4, total_segments=1, segment_size=4,
                        checksum=expected_md5, seed='teste')
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(cliente.ProtocolError):
                cliente.baixar_arquivo(sock, args, info)
            directory = Path(temporary) / 'small'
            self.assertFalse((directory / 'arquivo.bin').exists())
            self.assertTrue((directory / 'arquivo.part').exists())
            return json.loads((directory / 'resumo.json').read_text())

    def test_md5_incorreto_mesmo_com_done_positivo(self):
        summary = self.verificar_falha_integridade('0' * 32, b'DONE|ok=1')
        self.assertFalse(summary['checksum_ok'])
        self.assertTrue(summary['done_ok'])

    def test_done_negativo_mesmo_com_md5_correto(self):
        summary = self.verificar_falha_integridade(hashlib.md5(b'abcd').hexdigest(), b'DONE|ok=0')
        self.assertTrue(summary['checksum_ok'])
        self.assertFalse(summary['done_ok'])

    def test_erro_servidor_nao_e_ignorado(self):
        sock = Mock()
        sock.recv.return_value = b'ERROR|msg=sessao_invalida'
        with self.assertRaises(cliente.ProtocolError):
            cliente.receber_segmento(sock, 0, 4, 4, .1, 2)
        self.assertEqual(sock.send.call_count, 1)


if __name__ == '__main__':
    unittest.main()
