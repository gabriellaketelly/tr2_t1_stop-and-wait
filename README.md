# RDT-UnB — Entregas 1, 2 e 3: SAW, GBN, SR e RTT adaptativo

Trabalho da disciplina **CIC0236 — Teleinformática e Redes 2**, grupo **08**
(identificador **grupo08**).

Este repositório implementa transferência confiável de arquivos sobre UDP.
O projeto reúne o Stop-and-Wait da Entrega 1 e os protocolos
de janela deslizante Go-Back-N e Selective Repeat da Entrega 2, com coleta
de métricas, simulação de perda e comparação de desempenho. A Entrega 3
acrescenta timeout adaptativo aos clientes GBN e SR, experimentos remotos
reproduzíveis e instrumentação para correlação com capturas Wireshark.

## Protocolos implementados

Todos os clientes negociam `segment_size` no handshake `HELLO → OK`, enviam
`REQ` para solicitar segmentos, recebem `DATA` e enviam `ACK`. Ao terminar,
verificam o tamanho e o checksum MD5 e encerram com `FIN → DONE`.
`--group` é obrigatório e seu valor é enviado no campo `grupo=` do `HELLO`.
O arquivo só é confirmado como `arquivo.bin` quando a integridade é validada
e o servidor responde `DONE|ok=1`.

| Protocolo | Implementação | Janela e tratamento de perdas |
|---|---|---|
| Stop-and-Wait (SAW) | [cliente.py](cliente.py) | Um segmento por vez: `REQ → DATA → ACK`. Se o DATA não chegar no prazo, retransmite o REQ. |
| Go-Back-N (GBN) | [cliente_gbn.py](cliente_gbn.py) | Mantém até N REQs pendentes e aceita somente o DATA da base da janela. Descarta segmentos fora de ordem; no timeout da base, retransmite todos os REQs pendentes da janela. |
| Selective Repeat (SR) | [cliente_sr.py](cliente_sr.py) | Mantém até N REQs pendentes, com temporizadores individuais. Retransmite apenas os segmentos expirados; confirma e armazena DATA fora de ordem em buffer, gravando o arquivo na sequência correta. |

GBN e SR aceitam janelas de **4, 8 ou 16** segmentos. Ambos reutilizam as
rotinas de handshake, leitura de DATA e finalização do cliente SAW.

## Instalação e execução

Requer **Python 3.10 ou superior**. Os clientes e o executor de experimentos
usam somente a biblioteca padrão; o Matplotlib é necessário para os gráficos.
Execute os comandos a partir da raiz do repositório.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### Clientes no servidor da disciplina

Exemplos sem simulação de perda, adequados à demonstração ao vivo:

```bash
# Entrega 1: executar os três tamanhos sequencialmente.
python3 cliente.py --server 137.131.178.229 --group grupo08 --file small --output-dir resultados_demo
python3 cliente.py --server 137.131.178.229 --group grupo08 --file medium --output-dir resultados_demo
python3 cliente.py --server 137.131.178.229 --group grupo08 --file large --output-dir resultados_demo
python3 graficos.py --resultados resultados_demo

# Entrega 2: exemplos com janela 8 e perda simulada desativada.
python3 cliente_gbn.py --server 137.131.178.229 --group grupo08 --file small --window-size 8 --loss-rate 0 --output-dir resultados_demo
python3 cliente_sr.py --server 137.131.178.229 --group grupo08 --file small --window-size 8 --loss-rate 0 --output-dir resultados_demo
```

| Argumento | Padrão / valores aceitos |
|---|---|
| `--server` / `--port` | `137.131.178.229` / `8080` |
| `--group` | Obrigatório; neste trabalho, `grupo08` |
| `--file` | `small` (padrão), `medium` ou `large` |
| `--segment-size` | 512 bytes; de 1 a 512. O valor negociado no OK prevalece. |
| `--timeout` | SAW: 0,5 s; GBN/SR: 0,2 s |
| `--max-retries` | Até 10 retransmissões |
| `--output-dir` | `resultados` |
| `--window-size` | Apenas GBN/SR: 4 (padrão), 8 ou 16 |
| `--loss-rate` | Apenas GBN/SR: probabilidade entre 0 e 1; padrão 0. Exemplo: `0.05` para 5%. |
| `--timeout-mode` | GBN/SR: `fixed` (padrão) ou `adaptive`. |
| `--alpha` / `--beta` | GBN/SR: pesos EWMA; padrões `0.125` / `0.25`, configuráveis em `(0, 1]`. |
| `--rto-min` / `--rto-max` | GBN/SR: limites do timeout adaptativo, `0.01` / `60` segundos. |
| `--loss-seed` | GBN/SR: semente para perdas reproduzíveis por segmento e tentativa. |

Os resultados são salvos em `<output-dir>/<arquivo>/` para SAW e em
`<output-dir>/{gbn,sr}/<arquivo>/` para os protocolos de janela.
Uma nova execução no mesmo destino substitui a anterior, inclusive quando
se altera a janela ou a taxa de perda. Use destinos diferentes para guardar
experimentos separados.

O timeout padrão de SAW é 0,5 s: na coleta atual de `large`, o RTT p99 foi
124,94 ms, então 4×p99 ≈ 500 ms. A coleta piloto com 0,25 s teve 194 timeouts,
por isso esse valor não é usado como referência recomendada. O timeout fixo de
0,2 s usado nas comparações GBN/SR é mantido para comparar diretamente com o
timeout inicial adaptativo. A coleta histórica com 2 s não justifica o padrão atual.

Os CSVs novos repetem `grupo`, `servidor`, `porta`, `arquivo` e `protocolo` em
cada linha e registram timestamps REQ/DATA. Para a duração total, use
`duracao_s` do `resumo.json`; somar tempos por segmento em GBN/SR contaria
intervalos sobrepostos mais de uma vez.

Nas execuções registradas da Entrega 1, o servidor respondeu aos ACKs com
`ERROR|msg=tipo_desconhecido_ACK`. Os clientes mantêm o envio dos ACKs e
toleram somente esse erro específico, sem renovar o timeout. O aviso fica
registrado em `avisos_servidor` no resumo da transferência.

### Diagnóstico do servidor

[rdt_diagnostico.py](rdt_diagnostico.py) verifica a comunicação com o servidor
em três etapas: `PING → PONG`, `HELLO → OK` para o arquivo `small` e duas
trocas `REQ → DATA`, solicitando as sequências 0 e 1. Exibe RTT, metadados
do arquivo e o resultado de cada etapa, com timeout de 5 segundos.

```bash
python3 rdt_diagnostico.py --server 137.131.178.229 --group grupo08
```

O diagnóstico usa `grupo08` por padrão e aceita `--server`, `--port` e
`--group`. Ele segue o fluxo do script fornecido: o próximo REQ funciona
como confirmação implícita, sem enviar ACK separado. Esse teste recebe
somente dois segmentos; a validação do MD5 do arquivo completo é feita
pelos clientes de transferência descritos acima.

### Entrega 3 — RTT adaptativo no servidor remoto

A implementação em [rtt.py](rtt.py) calcula `RTT_est`, `DevRTT` e
`timeout = RTT_est + 4 × DevRTT`. O desvio usa a estimativa **já atualizada**,
conforme a ordem implementada e testada. Amostras de segmentos retransmitidos são
excluídas (Karn); expirações dobram o timeout até o teto configurado.
O SR preserva o prazo de cada solicitação e atualiza o estimador quando
o DATA chega, mesmo que ainda esteja no buffer aguardando outro segmento.
HELLO e FIN continuam usando `--timeout`.

```bash
python3 cliente_sr.py --server 137.131.178.229 --group grupo08 --file large \
  --window-size 16 --timeout-mode adaptive --timeout 0.2 \
  --alpha 0.125 --beta 0.25 --loss-rate 0.05 --loss-seed 20261109 \
  --output-dir resultados_rtt_sr
```

[executar_experimentos_rtt.py](executar_experimentos_rtt.py) usa exclusivamente
`137.131.178.229`, sem servidor ou proxy local. As perdas são induzidas
no receptor durante transferências pela rede real. A matriz completa
compara os modos fixo/adaptativo, três pares de α/β, perdas 0%, 5% e 10%
e três repetições, incluindo SAW fixo sem perda. Ela pode levar horas.

```bash
# O manifesto já registra uma tentativa de diagnóstico; --resume preserva os dados.
python3 executar_experimentos_rtt.py --protocols GBN SR --baseline \
  --loss-rates 0 0.05 0.10 --file large --repetitions 3 \
  --output-dir entrega-3 --resume
python3 analisar_rtt.py --input-dir entrega-3
python3 gerar_relatorio_rtt.py --input-dir entrega-3
```

Os padrões α=0.125 e β=0.25 são apenas uma referência inicial: a escolha
empírica depende das coletas. `metricas.csv` inclui RTT estimado, desvio,
timeout e timestamps Unix; `eventos.csv` registra REQ, DATA, descartes e
expirações. [correlacionar_captura.py](correlacionar_captura.py) extrai do
PCAP os frames de retransmissão e compara o RTT capturado com o CSV.

**Resultado final:** a análise validou 45 transferências remotas. As cinco
configurações da tabela integrada têm três repetições com sementes distintas.
O relatório final tem 15 páginas e não registra pendências. O pacote portátil
fica abaixo do limite de 50 MB e contém CSVs separados por entrega e protocolo.

- [Relatório PDF](entrega-3/relatorio/relatorio_final.pdf)
- [Pacote ZIP](entrega-3/para_upload/relatorio_latex_pdf_figuras.zip)
- [CSV de métricas anexados](entrega-3/relatorio/anexos/)

Veja [docs/entrega3.md](docs/entrega3.md) para o método dos experimentos,
as diferenças em relação ao TCP e os screenshots Wireshark exigidos.

### Matriz local da Entrega 2 (histórico)

[run_experiments.py](run_experiments.py) executa automaticamente **21 cenários**:
SAW com janela 1, GBN e SR com janelas 4, 8 e 16, cada configuração com
perdas simuladas de **0%, 5% e 10%**.

```bash
# Nova coleta em diretório separado dos resultados versionados.
python3 run_experiments.py --output-dir resultados_experimentos
python3 analyze_data.py --input-dir resultados_experimentos
python3 check_md5.py --original resultados_experimentos/_servidor-local/small/arquivo.bin --received-dir resultados_experimentos
```

O executor inicia [test_localserver.py](test_localserver.py) e um proxy UDP
local para cada cenário. A configuração atual usa `127.0.0.1`, arquivo
`small` sintético de **64 KiB**, segmentos de **512 bytes** (128 segmentos),
timeout de **0,2 s** e até **10 retransmissões**. O arquivo de origem é gerado
automaticamente em `_servidor-local/small/arquivo.bin`. Esses parâmetros
estão definidos no início de `run_experiments.py`.

Cada cenário recebe um diretório como `gbn-w16-loss10/`, com `metricas.csv`,
`resumo.json` e `arquivo.bin` nas subpastas do cliente. O executor também
copia o CSV para `resultado_<PROTOCOLO>_w<JANELA>_loss<PERDA>.csv` na raiz
do cenário. Sem `--output-dir`, o destino é `entrega-2-v2`.

### Simulação de perda

Na matriz, o proxy descarta cada pacote **DATA antes de entregá-lo ao cliente**,
com a probabilidade configurada. HELLO, REQ, ACK e FIN continuam sendo
encaminhados. Isso provoca timeout e retransmissão e aplica o mesmo mecanismo
aos três protocolos, incluindo o SAW, que não possui `--loss-rate` próprio.

Durante essa execução, a perda interna de GBN/SR fica desativada
(`--loss-rate 0`). Ao final de cada cenário, o executor registra no CSV o
número de descartes por sequência em `simulated_loss` e, no resumo, sua soma
em `simulated_loss_total`. Assim, o CSV identifica os descartes simulados;
uma retransmissão sem descarte registrado também pode decorrer de outro
efeito, como atraso ou perda natural.

Em execuções individuais, GBN e SR também podem descartar DATA no próprio
cliente usando `--loss-rate`. Para comparar os três protocolos, use a matriz
com o proxy comum. Na demonstração com o servidor real, mantenha a simulação
desativada.

## Métricas e gráficos

O CSV da Entrega 2 contém uma linha por segmento:

```text
seq,bytes,rtt_ms,tempo_segmento_ms,throughput_bps,retransmissoes,timeout_ocorrido,simulated_loss
```

| Campo | Significado |
|---|---|
| `seq` / `bytes` | Número da sequência, a partir de zero, e quantidade de bytes úteis. |
| `rtt_ms` | Tempo do primeiro REQ até o DATA aceito, somente quando não houve retransmissão; fica vazio nos demais casos. |
| `tempo_segmento_ms` | Tempo do primeiro REQ até o DATA aceito, incluindo esperas e retransmissões. No SR, não inclui a espera posterior no buffer para gravar em ordem. |
| `throughput_bps` | Bits úteis do segmento divididos por seu tempo, em segundos. |
| `retransmissoes` | Quantidade de REQs adicionais para a sequência. |
| `timeout_ocorrido` | 0 ou 1; no GBN, também marca segmentos retransmitidos junto com a base da janela. |
| `simulated_loss` | Quantidade de descartes simulados de DATA daquela sequência; pode ser maior que 1. |

O CSV gerado diretamente por `cliente.py` tem os sete primeiros campos;
`run_experiments.py` acrescenta `simulated_loss` ao SAW e preenche o campo
com os registros do proxy em todos os protocolos.

`resumo.json` contém os MD5 esperado e recebido, `checksum_ok`, `done_ok`,
duração, throughput agregado e retransmissões. Na matriz, também identifica
protocolo, janela, taxa de perda e total de perdas simuladas.

- **Throughput medido:** total de bits úteis dividido por `duracao_s`, que
  mede a fase de transferência, incluindo processamento e gravação, sem
  handshake e finalização. Não é a média das taxas por segmento.
- **Throughput teórico do SAW:** `segment_size × 8 / RTT_médio`, com RTT em
  segundos. Como o SAW espera uma resposta antes de solicitar o próximo
  segmento, o RTT limita a quantidade de dados úteis transferida por segundo.

[graficos.py](graficos.py) gera os gráficos de throughput, RTT e timeouts
por segmento da Entrega 1, além do comparativo teórico versus medido em CSV,
PNG e PDF. A média móvel padrão é de 100 segmentos; ajuste com `--janela 50`.

[analyze_data.py](analyze_data.py) gera `comparativo.csv`, imprime a análise
das janelas e das retransmissões por perda e produz
`graficos/grafico_throughput_gbn_sr_w16_loss10.png`, com dois painéis:
throughput por segmento e retransmissões acumuladas de GBN e SR, ambos com
janela 16 e perda de 10%. O script verifica a presença dos 21 cenários e os
campos de integridade dos resumos.

## Resultados preservados

### Entrega 1 — servidor da disciplina

[resultados/](resultados/) contém CSVs, resumos e gráficos das transferências
reais de `small`, `medium` e `large`. Os arquivos recebidos e parciais desse
diretório são ignorados pelo Git. A comparação completa está em
[resultados/comparativo.csv](resultados/comparativo.csv).

| Arquivo | Tamanho | MD5 recebido | Teórico (kbit/s) | Medido (kbit/s) |
|---|---:|---|---:|---:|
| small | 1 MiB | `fcf4063229a9de6d5ff20f985016a7d6` | 96,10 | 95,37 |
| medium | 5 MiB | `7901c7de406ce5078e146f6c4e5724cd` | 97,48 | 96,74 |
| large | 10 MiB | `e4de8c5bbc4161ed42b7af19bc05e188` | 96,23 | 94,80 |

### Entrega 2 — servidor local e proxy de perda

A matriz versionada em [entrega-2-v2/](entrega-2-v2/) contém os **21 cenários
com `checksum_ok=true` e `done_ok=true`**. Todos receberam o arquivo sintético
com MD5 `9cc60713923528a1dd94e1c1ab0ebc9e`. Os arquivos `.bin` dessa matriz
estão versionados e podem ser conferidos com:

```bash
for cenario in entrega-2-v2/*-w*-loss*; do
  python3 check_md5.py --original entrega-2-v2/_servidor-local/small/arquivo.bin --received-dir "$cenario"
done
```

As pastas `teste-local/` e `teste-test-localserver/` guardam testes auxiliares
com outro arquivo de origem e ficam fora dessa matriz.

Dados de [entrega-2-v2/comparativo.csv](entrega-2-v2/comparativo.csv), com
throughput em Mbit/s (1 Mbit/s = 1.000.000 bit/s) e duração em segundos:

| Protocolo | Janela | Perda configurada | Throughput (Mbit/s) | Retransmissões | Tempo (s) |
|---|---:|---:|---:|---:|---:|
| SAW | 1 | 0% | 16,944 | 0 | 0,031 |
| SAW | 1 | 5% | 1,137 | 2 | 0,461 |
| SAW | 1 | 10% | 0,157 | 16 | 3,345 |
| GBN | 4 | 0% | 59,888 | 0 | 0,009 |
| GBN | 4 | 5% | 0,422 | 21 | 1,243 |
| GBN | 4 | 10% | 0,158 | 63 | 3,318 |
| GBN | 8 | 0% | 73,871 | 0 | 0,007 |
| GBN | 8 | 5% | 0,423 | 48 | 1,238 |
| GBN | 8 | 10% | 0,317 | 64 | 1,656 |
| GBN | 16 | 0% | 74,342 | 0 | 0,007 |
| GBN | 16 | 5% | 0,419 | 88 | 1,252 |
| GBN | 16 | 10% | 0,181 | 212 | 2,904 |
| SR | 4 | 0% | 61,081 | 0 | 0,009 |
| SR | 4 | 5% | 1,239 | 2 | 0,423 |
| SR | 4 | 10% | 0,418 | 9 | 1,255 |
| SR | 8 | 0% | 66,271 | 0 | 0,008 |
| SR | 8 | 5% | 0,363 | 10 | 1,444 |
| SR | 8 | 10% | 0,228 | 16 | 2,295 |
| SR | 16 | 0% | 72,630 | 0 | 0,007 |
| SR | 16 | 5% | 1,271 | 2 | 0,412 |
| SR | 16 | 10% | 0,498 | 13 | 1,053 |

Sem perda simulada, o ganho do GBN diminui de janela 8 para 16
(73,87 para 74,34 Mbit/s); o SR ainda apresenta aumento nessa faixa
(66,27 para 72,63 Mbit/s). Com janela 16 e 10% de perda, o GBN registra
**212 retransmissões para 33 descartes simulados** (6,42 retransmissões por
descarte), enquanto o SR registra **13 para 13** (1,00). Nessa execução,
a retransmissão da janela inteira no GBN aumenta o trabalho repetido e
acompanha um tempo de transferência maior: 2,904 s contra 1,053 s no SR.

Essas medidas descrevem uma coleta local por cenário, com arquivo pequeno
e perdas aleatórias sem semente fixa. A taxa configurada é uma probabilidade,
e os descartes efetivos variam entre execuções. Os dados não estabelecem um
limiar universal de saturação da janela nem são diretamente comparáveis
às vazões medidas no servidor remoto na Entrega 1.

Os gráficos já versionados incluem o
[comparativo de throughput e retransmissões acumuladas](entrega-2-v2/graficos/grafico_throughput_gbn_sr_w16_loss10.png)
e o [gráfico complementar de retransmissões](entrega-2-v2/graficos/grafico_retransmissoes_gbn_sr_w16_loss10.png).
O analisador atual regenera o primeiro arquivo.

## Verificação e relatório

### Testes automatizados

```bash
python3 -m unittest discover -s testes -p 'test_*rtt*.py' -v
```

Os testes da Entrega 3 cobrem EWMA, Karn, temporizadores SAW/GBN/SR,
integridade, retomada da matriz e correlação de capturas. Eles usam relógios
e datagramas em memória e não medem desempenho. Os testes antigos do SAW
estão em `testes/test_protocolo.py`; `test_udp_com_perda_e_sequencia_errada`
abre um servidor localhost e não foi executado na validação desta entrega.
Os dados e gráficos anteriores estão em `resultados/` e `entrega-2-v2/`.
O gerador da Entrega 3 produz o [PDF](entrega-3/relatorio/relatorio_final.pdf),
a fonte LaTeX editável para o Overleaf e os anexos em `entrega-3/relatorio/`.
O título e `status.json` indicam se ainda há requisitos pendentes.
