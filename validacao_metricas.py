"""Validação estrutural das métricas de uma transferência completa."""

import csv
from pathlib import Path


def validar_csv_metricas(caminho: Path, resumo: dict) -> int:
    """Exige exatamente uma linha, com tamanho correto, para cada segmento.

    O checksum de um arquivo completo não garante que seu CSV também esteja
    completo: uma interrupção ou edição posterior pode truncar só as métricas.
    A validação aceita a ordem de chegada ou de sequência, mas não duplicatas.
    """
    tamanho_arquivo = resumo.get("file_size")
    tamanho_segmento = resumo.get("segment_size")
    for nome, valor in (("file_size", tamanho_arquivo), ("segment_size", tamanho_segmento)):
        if type(valor) is not int or valor <= 0:
            raise ValueError(f"{nome} deve ser um inteiro positivo")
    total = (tamanho_arquivo + tamanho_segmento - 1) // tamanho_segmento
    if "total_segments" in resumo:
        declarado = resumo["total_segments"]
        if type(declarado) is not int or declarado != total:
            raise ValueError("total_segments inconsistente com file_size e segment_size")
    if not caminho.is_file():
        raise ValueError("CSV por segmento ausente")
    encontrados = set()
    try:
        with caminho.open(newline="", encoding="utf-8") as origem:
            leitor = csv.DictReader(origem, strict=True)
            colunas = leitor.fieldnames or []
            if colunas.count("seq") != 1 or colunas.count("bytes") != 1:
                raise ValueError("CSV deve conter uma coluna seq e uma coluna bytes")
            for linha in leitor:
                if None in linha or any(valor is None for valor in linha.values()):
                    raise ValueError(f"CSV linha {leitor.line_num}: quantidade de campos inconsistente")
                try:
                    sequencia, tamanho = int(linha["seq"]), int(linha["bytes"])
                except (ValueError, TypeError) as erro:
                    raise ValueError(f"CSV linha {leitor.line_num}: seq/bytes inválido") from erro
                if not 0 <= sequencia < total:
                    raise ValueError(f"CSV linha {leitor.line_num}: seq={sequencia} fora do arquivo")
                if sequencia in encontrados:
                    raise ValueError(f"CSV linha {leitor.line_num}: seq={sequencia} duplicado")
                tamanho_esperado = min(tamanho_segmento, tamanho_arquivo - sequencia * tamanho_segmento)
                if tamanho != tamanho_esperado:
                    raise ValueError(f"CSV seq={sequencia}: bytes={tamanho}, esperado={tamanho_esperado}")
                encontrados.add(sequencia)
    except csv.Error as erro:
        raise ValueError(f"CSV inválido: {erro}") from erro
    if len(encontrados) != total:
        raise ValueError(f"CSV incompleto: {len(encontrados)} de {total} segmentos")
    return total
