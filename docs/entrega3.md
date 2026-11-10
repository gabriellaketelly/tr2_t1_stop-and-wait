# Entrega 3 — RTT adaptativo no servidor remoto

As novas coletas usam exclusivamente `137.131.178.229:8080`, com o grupo
`grupo08`. O executor desta entrega não inicia servidor local nem proxy.
Os resultados históricos em `entrega-2-v2/` foram obtidos em loopback e
permanecem identificados como histórico: não são evidência de desempenho
no servidor da disciplina.

## Organização e convenções do código

Os identificadores autorais usam português sem acentos: funções e variáveis
em `snake_case`, classes em `PascalCase`. Os métodos de teste mantêm o
prefixo `test_`, exigido pela descoberta automática do `unittest`, e usam
uma descrição em português depois dele. Nomes das APIs de Python, como
`send`, `recv`, `assertEqual` e `parse_args`, seguem o contrato da biblioteca.
As opções de linha de comando e as colunas dos CSVs/JSONs preservam o
formato existente para continuar aceitando os comandos e dados anteriores.

| Módulo | Responsabilidade |
|---|---|
| `protocolo_rdt.py` | `ErroProtocolo`, `negociar_sessao`, `interpretar_dados` e validação das mensagens UDP. |
| `cliente.py` | `receber_segmento` e `baixar_com_stop_and_wait` para SAW. |
| `rtt.py` | `EstimadorRTT`: EWMA, desvio e cálculo do timeout. |
| `simulacao_perdas.py` | `SimuladorPerdas`: decisão reproduzível de descarte. |
| `registro_metricas.py` | `RegistroEventos` e definição das colunas de métricas. |
| `configuracao_clientes.py` | Argumentos e configurações compartilhadas de GBN/SR. |
| `cliente_gbn.py`, `cliente_sr.py` | `baixar_com_go_back_n` e `baixar_com_repeticao_seletiva`: estado da janela e transferência. |
| `executar_experimentos_rtt.py` | Execução sequencial da matriz remota e retomada. |
| `analisar_rtt.py` | Validação, agrupamento e seleção dos parâmetros medidos. |
| `graficos_rtt.py` | Geração dos gráficos a partir da análise. |
| `validacao_metricas.py` | Integridade estrutural dos CSVs de segmentos. |
| `correlacionar_captura.py` | Associação entre captura Wireshark e registros do cliente. |
| `relatorio_rtt/` | Formatação LaTeX, anexos, comparações, conteúdo e compilação do PDF. |
| `gerar_relatorio_rtt.py` | Interface de linha de comando para gerar o relatório. |
| `testes/apoio_rtt.py` | Relógio e datagramas em memória compartilhados pelos testes. |

Os nomes antigos `run_rtt_experiments.py` e `analyze_rtt.py` são entradas
compatíveis de linha de comando; a implementação fica nos módulos em português.

## Implementação e medidas

GBN e SR aceitam `--timeout-mode fixed` e `--timeout-mode adaptive`.
`--timeout` é o timeout constante no modo fixo e o valor inicial no modo
adaptativo. HELLO/OK e FIN/DONE continuam usando esse timeout de controle.
As medições de duração usam o relógio monotônico `time.perf_counter()`;
timestamps Unix adicionais permitem localizar os mesmos pacotes na captura.

O padrão SAW foi ajustado para 0,5 s: no arquivo atual de 10 MiB, o p99 do RTT
medido foi 124,94 ms, portanto 4×p99 ≈ 0,5 s. O piloto com 0,25 s expirou 194
vezes. O timeout de 2 s da coleta histórica não tinha justificativa baseada
no RTT e não é a configuração recomendada.

Para cada DATA válido, recebido sem retransmissão do REQ correspondente:

```text
RTT_medido = instante_DATA - instante_REQ
RTT_est_n = (1 - alpha) * RTT_est_(n-1) + alpha * RTT_medido
DevRTT_n = (1 - beta) * DevRTT_(n-1) + beta * abs(RTT_medido - RTT_est_n)
RTO_n = RTT_est_n + 4 * DevRTT_n
```

A primeira amostra inicializa `RTT_est = RTT_medido` e
`DevRTT = RTT_medido / 2`. Os limites configuráveis de RTO evitam timeout
nulo e esperas sem limite. Os padrões são `--rto-min 0.01` e
`--rto-max 60`, em segundos. No timeout adaptativo há recuo exponencial;
uma nova medição não ambígua permite retornar ao valor do estimador.
No SR cada REQ mantém o prazo armado no envio. Atualizar a EWMA não muda
retroativamente os prazos dos demais segmentos em trânsito.

O backoff do SR é individual por segmento. O GBN mantém o temporizador
compartilhado da base e o reinicia quando ela avança. Seu
`timeout_usado_ms` registra o RTO no envio da REQ; o intervalo até uma
retransmissão pode ser maior devido aos reinícios. Consulte o evento
`TIMEOUT` para localizar a expiração efetiva. A EWMA é atualizada por DATA
elegível, de modo que podem existir várias amostras durante um mesmo RTT.

**Amostras ambíguas:** após retransmitir um REQ, o protocolo não identifica
qual tentativa originou o DATA. A regra de Karn exclui esse segmento do
estimador: `rtt_ms` fica vazio e `rtt_sample_valid = 0`. Seu tempo total e
suas retransmissões continuam contabilizados. No SR, medir no recebimento,
antes de esperar a ordenação do buffer, evita incluir espera de gravação no RTT.

**Relação com TCP:** a [RFC 6298](https://www.rfc-editor.org/rfc/rfc6298)
usa o SRTT anterior para atualizar o desvio, recomenda piso de 1 segundo
e estabelece Karn e recuo exponencial. Aqui a ordem segue as fórmulas
da implementação, com SRTT já atualizado, e o piso é configurável para o
experimento UDP. Portanto, trata-se de uma adaptação didática, não de uma
implementação completa do temporizador TCP.

## Experimentos reproduzíveis

Não execute clientes do mesmo grupo simultaneamente. Escolha uma pasta
nova para preservar cada coleta. Exemplo individual com o arquivo `large`:

```bash
python3 cliente_sr.py --server 137.131.178.229 --port 8080 \
  --group grupo08 --file large --window-size 16 \
  --timeout 0.2 --timeout-mode adaptive --alpha 0.125 --beta 0.25 \
  --loss-rate 0.05 --loss-seed 1 --output-dir entrega-3/sr-adaptativo-loss05
```

Execute o par fixo com os mesmos argumentos de arquivo, janela, perda e
semente, alterando o modo para `fixed` e usando outra pasta. Repita para
10%. A simulação descarta DATA recebidos no próprio cliente; os datagramas
trafegam até a máquina e aparecem no Wireshark. Isso é uma perda de
aplicação induzida sobre uma transferência remota real. Não significa que
5% ou 10% dos pacotes desapareceram fisicamente na rede.

A matriz automatizada experimenta pelo menos três pares de pesos:

| Par | alpha | beta | Hipótese a verificar nos dados |
|---|---:|---:|---|
| Referência | 0.125 | 0.25 | Equilíbrio entre estabilidade e resposta |
| Mais suave | 0.0625 | 0.125 | Menor influência de amostras isoladas |
| Mais rápido | 0.25 | 0.5 | Resposta mais rápida a mudanças |

As hipóteses não substituem medições. Escolha pesos pelo throughput médio
nas condições comuns, apresente também retransmissões, duração, número de
repetições e dispersão. Com uma única execução por cenário, descreva os
resultados como exploratórios. Se os pesos tiverem ganhos semelhantes à
variação entre repetições, não declare um vencedor conclusivo.

O CLI completo e os valores padrão estão em:

```bash
python3 executar_experimentos_rtt.py --help
python3 analisar_rtt.py --help
```

A matriz preparada em `entrega-3/manifesto.json` contém 75 cenários:
três repetições de SAW fixo sem perda e GBN/SR com janela 16, modos fixo
e três pares adaptativos, para perdas de 0%, 5% e 10%. Após recuperar a
comunicação com o servidor, retome com os mesmos argumentos que definiram
o manifesto:

```bash
python3 executar_experimentos_rtt.py --protocols GBN SR --baseline \
  --loss-rates 0 0.05 0.10 --file large --repetitions 3 \
  --output-dir entrega-3 --resume
python3 analisar_rtt.py --input-dir entrega-3
```

O diagnóstico inicial usa HELLO antes de iniciar os cenários. A opção
`--resume` preserva as execuções já concluídas e registra novas tentativas.
Não reduza ou altere a matriz dentro da mesma pasta; para uma configuração
diferente, selecione outro `--output-dir`.

O executor registra comandos, sementes, horários e falhas em
`manifesto.json`. Somente transferências completas, com MD5 correto e
`DONE|ok=1`, entram nas comparações. Falha de conectividade não é perda
experimental de 100% nem resultado válido de throughput.

## CSVs, relógios e integridade

Cada linha de `metricas.csv` identifica `grupo`, `servidor`, `porta`, `arquivo`
e `protocolo`; isso permite auditar o grupo mesmo quando o CSV é separado do
manifesto. Coletas antigas preservam esses dados no `resumo.json`, não nas
linhas do CSV.

O `metricas.csv` conserva as métricas anteriores e acrescenta:

| Campo | Interpretação |
|---|---|
| `req_timestamp_epoch` | Timestamp Unix do REQ associado à linha |
| `data_timestamp_epoch` | Timestamp Unix do DATA aceito |
| `received_elapsed_s` | Tempo monotônico desde o início até receber o DATA |
| `rtt_est_ms`, `dev_rtt_ms` | Estado da EWMA depois de processar o DATA |
| `timeout_ms` | Timeout calculado pelo estimador nesse instante |
| `timeout_usado_ms` | Timeout armado para a tentativa registrada |
| `rtt_sample_valid` | 1 quando a amostra pode atualizar o estimador |

Na coleta SAW legada, o CSV não tem timestamps absolutos. Somar
`tempo_segmento_ms` estima o tempo serial dos segmentos, mas não reproduz
exatamente `duracao_s`; o valor oficial vem do cronômetro monotônico registrado
em `resumo.json`. Em GBN/SR, os tempos por segmento se sobrepõem, então somá-los
contaria o mesmo intervalo várias vezes. Nas coletas novas, `received_elapsed_s`
e os timestamps REQ/DATA permitem reconstituir a linha do tempo; `duracao_s`
do resumo continua sendo a duração oficial da transferência de dados.

`eventos.csv` registra REQs, DATA, descartes e timeouts, incluindo tentativa,
sequência e timestamp. Para analisar a evolução do SR, use a ordem de
recebimento (`received_elapsed_s`), pois as linhas de `metricas.csv` são
gravadas em ordem de sequência.

O throughput agregado é `8 * bytes_uteis / duracao_s`, medido durante a
transferência de dados. Ele não é a média aritmética de
`throughput_bps` por segmento: em protocolos com janela, os tempos dos
segmentos se sobrepõem. HELLO e FIN não estão nessa duração. O checksum MD5
é comparado ao valor anunciado pelo servidor; o arquivo recebido só vira
`arquivo.bin` após essa validação e a confirmação DONE.

## Captura e análise Wireshark

Capture na interface que leva ao servidor (por exemplo, `en0` no macOS;
uma VPN pode usar outra interface). O filtro de **captura** solicitado é:

```text
udp and host 137.131.178.229
```

O equivalente no campo de filtro de **exibição** do Wireshark é:

```text
udp && ip.addr == 137.131.178.229
```

Inicie a captura antes de executar um cliente com `--file large` e
simulação de perda. Termine depois do `DONE`. Salve o `.pcapng` e o
comando exato do cliente. Como o protocolo é UDP, o Wireshark não marca
automaticamente esses REQs como retransmissões TCP: identifique a
repetição de `REQ|seq=N` no payload e a porta UDP da mesma sessão.

Exemplo no macOS, em dois terminais, sem executar a matriz ao mesmo tempo:

```bash
# Terminal 1: mantenha aberto; encerre com Ctrl+C depois do DONE do cliente.
mkdir -p entrega-3/wireshark
tcpdump -i en0 -n -U -w entrega-3/wireshark/large-sr.pcap \
  'udp and host 137.131.178.229'
```

```bash
# Terminal 2: transferência usada para a captura, em destino próprio.
python3 cliente_sr.py --server 137.131.178.229 --group grupo08 --file large \
  --window-size 16 --timeout 0.2 --timeout-mode adaptive \
  --alpha 0.125 --beta 0.25 --loss-rate 0.10 --loss-seed 20261109 \
  --output-dir resultados_captura_sr
# Depois de encerrar a captura:
python3 correlacionar_captura.py --capture entrega-3/wireshark/large-sr.pcap \
  --metrics resultados_captura_sr/sr/large/metricas.csv \
  --output-dir entrega-3/wireshark
```

O correlacionador usa o TShark instalado com o Wireshark e exporta
`pacotes.csv`, `retransmissoes.csv`, `correlacao.csv` e
`captura_resumo.json`. As tabelas indicam os frames a abrir no Wireshark;
não substituem os screenshots. Se houver múltiplas sessões, selecione
`--client-port` e, se a porta tiver sido reutilizada, delimite uma única
transferência com `--frame-start` e `--frame-end`.

Guarde três screenshots reais, com anotações legíveis:

1. `screenshot1_sessao.png`: HELLO, primeiros/últimos REQs, FIN e DONE.
   Se necessário, use um filtro de exibição que mantenha os eventos de
   controle e uma seleção representativa dos REQs; registre esse filtro.
2. `screenshot2_retransmissoes.png`: pelo menos dois pares de REQ original
   e retransmitido, com sequência, números de quadro e delta entre os REQs.
3. `screenshot3_correlacao.png`: um evento com timestamp Unix e sua linha
   correspondente em `eventos.csv` ou `metricas.csv`. Mostre o mesmo
   número de sequência e a mesma tentativa.

Para medir RTT, selecione uma sequência sem retransmissão e subtraia o
timestamp do REQ do timestamp do DATA. Compare ao `rtt_ms` do cliente.
Timestamp de captura ocorre no caminho do kernel; a aplicação marca antes
do envio/depois do recebimento. Agendamento, fila de socket e processamento
explicam pequenas diferenças. Não associe a uma tentativa um DATA cuja
origem seja ambígua após retransmissão.

O gerador de PDF aceita `--wireshark-dir` com as imagens e um
`correlacao.csv`. A correlação numérica deve incluir `seq`, `req_frame`,
`data_frame`, `rtt_wireshark_ms`, `rtt_cliente_ms` e `diferenca_ms`.
Uma captura contendo somente HELLO sem resposta comprova a tentativa de
conexão, mas não satisfaz os requisitos de sessão completa ou retransmissão.

## Relatório e anexos

Depois de analisar as coletas:

```bash
python3 gerar_relatorio_rtt.py --input-dir entrega-3 \
  --analysis-dir entrega-3/analise --wireshark-dir entrega-3/wireshark
```

O gerador usa LaTeX (`pdflatex`) e entrega o PDF, a fonte editável e
anexos com os CSVs e MD5. Ele não cria números, screenshots nem resultados
para lacunas da coleta. A presença de pendências mantém o título como
**relatório parcial**. O processo valida o limite de 15 páginas quando
`pdfinfo` está disponível.

As três entregas aparecem na narrativa, com sua origem explícita. A tabela
final usa somente execuções remotas comparáveis de `large`; uma linha
faltante permanece `N/D`. Os CSVs locais antigos da Entrega 2 ficam em
anexo histórico separado. Uma nova medição remota dos clientes fixos é
necessária para avaliar GBN/SR contra a melhoria sem confundir diferenças
de rede, tamanho de arquivo ou timeout inicial.
