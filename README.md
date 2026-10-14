# tr2_t1_stop-and-wait
Entrega 1 (Parcial) do Trabalho Final da disciplina Teleinformática e Redes II. Implementação do protocolo mais simples de transferência confiável. O cliente envia um REQ, aguarda o pacote de DATA, envia ACK e só então solicita o próximo segmento. Se o DATA não chegar antes do timeout, retransmite o REQ.
