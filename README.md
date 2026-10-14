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
