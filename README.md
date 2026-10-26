# RDT-UnB — Entrega 1: Stop-and-Wait

CIC0236 — Teleinformática e Redes 2. Grupo **08**, identificador **grupo08**.

O cliente implementa transferência confiável sobre UDP: HELLO/OK, negociação de
segment_size, REQ → DATA → ACK, timeout, retransmissões e verificação MD5.
`--group` é obrigatório e seu valor é enviado no campo `grupo=` do HELLO.

## Execução

Python 3.10 ou superior. O cliente usa somente a biblioteca padrão;
Matplotlib é necessário para os gráficos.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 cliente.py --server 137.131.178.229 --group grupo08 --file small
python3 cliente.py --server 137.131.178.229 --group grupo08 --file medium
python3 cliente.py --server 137.131.178.229 --group grupo08 --file large
python3 graficos.py
```

Execute as transferências sequencialmente. Padrões: porta 8080, segmento de
512 bytes, timeout de 2 s e até 10 retransmissões por operação. O tamanho
recebido no OK prevalece. Novas execuções substituem os resultados do arquivo.
Uma transferência só termina com sucesso se tamanho, MD5 e DONE forem válidos.

## Resultados e métricas

`resultados/{small,medium,large}/` contém os CSVs, resumos e gráficos das três
execuções reais. Arquivos recebidos `.bin` e parciais `.part` são ignorados pelo
Git. `comparativo.csv` e `comparativo.png/pdf` comparam as vazões.

CSV por segmento:
`seq,bytes,rtt_ms,tempo_segmento_ms,throughput_bps,retransmissoes,timeout_ocorrido`.

- RTT: primeiro REQ até DATA, somente quando não houve retransmissão.
- Tempo do segmento: primeiro REQ até DATA, incluindo timeouts.
- Throughput por segmento: bits úteis divididos pelo tempo do segmento.
- Retransmissões: quantidade de REQs adicionais; timeout_ocorrido: 0 ou 1.

Throughput teórico: `segment_size × 8 / RTT_médio`, com RTT em segundos.
Throughput medido: total de bits úteis dividido pela duração do primeiro REQ
até o processamento e ACK do último segmento, excluindo HELLO e FIN.
A média das taxas por segmento não é usada como vazão agregada.

Os gráficos mostram todos os segmentos, com throughput, RTT e eventos de
timeout. A média móvel de 100 segmentos é apenas uma referência visual.
Para ajustar: `python3 graficos.py --janela 50`.

O servidor real rejeita o ACK previsto no enunciado com
`ERROR|msg=tipo_desconhecido_ACK`. O cliente mantém os ACKs e tolera somente
esse erro específico, sem renovar o timeout. A divergência está no relatório
e nos resumos em `avisos_servidor`.

## Testes

```bash
python3 -m unittest discover -s testes -v
```

O relatório é mantido no Overleaf. Os CSVs, resumos e gráficos usados nele
estão em `resultados/`.

## Entrega 2 — GBN e Selective Repeat

A matriz em `entrega-2-v2/` contém 21 cenários: SAW (janela 1), GBN e SR
(janelas 4, 8 e 16), com perdas de 0%, 5% e 10%. Para executar e analisar:

```bash
python run_experiments.py --output-dir entrega-2-v2
python analyze_data.py --input-dir entrega-2-v2
```

### Simulação de perda

Em `run_experiments.py`, um proxy UDP local descarta pacotes `DATA` antes de
entregá-los ao cliente, com probabilidade de 0, 0,05 ou 0,10. O mesmo método é
usado para SAW, GBN e SR. O servidor local é `test_localserver.py`; os testes
usam arquivo de 64 KiB, segmentos de 512 bytes e timeout de 0,2 s. Na demo
com o servidor real, a simulação deve permanecer desativada.

### Registro no CSV

Cada cenário contém `metricas.csv`, `resumo.json` e `arquivo.bin`. A coluna
`simulated_loss` informa quantas vezes o DATA de cada sequência foi descartado;
`simulated_loss_total`, no resumo, é a soma da coluna. Retransmissões aparecem
em `retransmissoes`.

### Resultados da matriz

A tabela completa está em `entrega-2-v2/comparativo.csv`; os 21 cenários
terminaram com `checksum_ok=true` e `done_ok=true`.

Throughput sem perda:

| Protocolo | Janela 4 | Janela 8 | Janela 16 |
|---|---:|---:|---:|
| GBN | 59,89 Mbit/s | 73,87 Mbit/s | 74,34 Mbit/s |
| SR | 61,08 Mbit/s | 66,27 Mbit/s | 72,63 Mbit/s |

Com janela 16 e 10% de perda:

| Protocolo | Throughput | Retransmissões | Perdas simuladas | Retransmissões por perda | Tempo total |
|---|---:|---:|---:|---:|---:|
| GBN | 180.561 bit/s | 212 | 33 | 6,42 | 2,90 s |
| SR | 497.855 bit/s | 13 | 13 | 1,00 | 1,05 s |

Com 10% de perda e janela 16, o GBN retransmitiu 212 segmentos contra 13 do
SR, explicando seu menor throughput e maior tempo total.

Os gráficos por segmento estão em `entrega-2-v2/graficos/`:

- `grafico_throughput_gbn_sr_w16_loss10.png`;
- `grafico_retransmissoes_gbn_sr_w16_loss10.png`.
