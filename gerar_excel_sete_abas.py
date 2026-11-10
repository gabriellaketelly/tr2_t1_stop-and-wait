"""Converte os sete CSVs anexados ao relatório em um XLSX com sete abas."""
from __future__ import annotations

import csv
from pathlib import Path
import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "entrega-3" / "relatorio" / "anexos"
OUTPUT = ROOT / "entrega-3" / "para_upload" / "dados_relatorio_final_todas_entregas.xlsx"


def column_name(index: int) -> str:
    result = ""
    while index:
        index, rest = divmod(index - 1, 26)
        result = chr(65 + rest) + result
    return result


def cell(ref: str, value: str, style_id: int = 0) -> str:
    style = f' s="{style_id}"' if style_id else ""
    if value == "":
        return f'<c r="{ref}"{style} t="inlineStr"><is><t></t></is></c>'
    try:
        number = float(value)
        if number == number and abs(number) != float("inf"):
            return f'<c r="{ref}"{style}><v>{escape(value)}</v></c>'
    except ValueError:
        pass
    preserve = ' xml:space="preserve"' if value[:1].isspace() or value[-1:].isspace() else ""
    return f'<c r="{ref}"{style} t="inlineStr"><is><t{preserve}>{escape(value)}</t></is></c>'


def sheet_xml(rows: list[list[str]], title: str = "", description: str = "", readme: bool = False) -> str:
    if not readme:
        rows = [[title], [description], [], *rows]
    max_col = max((len(row) for row in rows), default=1)
    max_ref = f"{column_name(max_col)}{len(rows)}"
    body = []
    for row_index, row in enumerate(rows, 1):
        if readme:
            style_id = 1 if row_index == 1 else (4 if row_index % 2 == 0 else 0)
        elif row_index == 1:
            style_id = 2
        elif row_index == 2:
            style_id = 3
        elif row_index == 4:
            style_id = 1
        else:
            style_id = 4 if row_index % 2 else 0
        cells = "".join(cell(f"{column_name(col_index)}{row_index}", value, style_id=style_id)
                         for col_index, value in enumerate(row, 1))
        body.append(f'<row r="{row_index}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{max_ref}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="{0 if readme else 4}" topLeftCell="{"A1" if readme else "A5"}" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="{"A1" if readme else "A5"}" sqref="{"A1" if readme else "A5"}"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/><cols><col min="1" max="1" width="24" bestFit="1" customWidth="1"/><col min="2" max="200" width="18" bestFit="1" customWidth="1"/></cols>'
            f'<sheetData>{"".join(body)}</sheetData>'
            f'<autoFilter ref="{"A1:" + max_ref if readme else "A4:" + max_ref}"/>'
            + (f'<mergeCells count="2"><mergeCell ref="A1:{column_name(max_col)}1"/><mergeCell ref="A2:{column_name(max_col)}2"/></mergeCells>' if not readme else '')
            + '<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
            '</worksheet>')


def main() -> None:
    files = sorted(SOURCE.glob("metrics_*.csv"))
    if len(files) != 7:
        raise SystemExit(f"Esperados 7 CSVs no relatório; encontrados {len(files)}")
    sheets = [("00_Leia-me", [["Aba", "O que contém", "Origem"]], "", "", True)]
    nomes = {
        "metrics_grupo08_gbn_20261110_162339_787907.csv": ("01_E2_GBN_Janela", "Médias de GBN na Entrega 2, com janela, perda, vazão, tempo e retransmissões.", "Entrega 2 remota"),
        "metrics_grupo08_gbn_20261110_162339_789117.csv": ("02_E3_GBN_Integrado", "Comparação integrada do GBN na Entrega 3, arquivo small.", "Entrega 3 remota"),
        "metrics_grupo08_saw_20261110_162339_787426.csv": ("03_E1_SAW_Historico", "Medição histórica do Stop-and-Wait na Entrega 1.", "Entrega 1 remota"),
        "metrics_grupo08_saw_20261110_162339_788473.csv": ("04_E2_MD5_Auxiliar", "Verificações MD5 dos testes auxiliares feitos enquanto o servidor estava indisponível; não entram nos resultados principais.", "Entrega 2 — servidor indisponível"),
        "metrics_grupo08_saw_20261110_162339_789527.csv": ("05_E3_SAW_Integrado", "Comparação integrada do Stop-and-Wait na Entrega 3, arquivo large.", "Entrega 3 remota"),
        "metrics_grupo08_sr_20261110_162339_788688.csv": ("06_E2_SR_Janela", "Médias de Selective Repeat na Entrega 2, com janela, perda, vazão, tempo e retransmissões.", "Entrega 2 remota"),
        "metrics_grupo08_sr_20261110_162339_789786.csv": ("07_E3_SR_Integrado", "Comparação integrada do Selective Repeat na Entrega 3, arquivo small.", "Entrega 3 remota"),
    }
    for index, path in enumerate(files, 1):
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.reader(stream))
        registro = dict(zip(rows[0], rows[1])) if len(rows) > 1 else {}
        tipo = registro.get("tipo_dado", "")
        protocolo = registro.get("protocolo", "")
        if tipo == "md5_integridade":
            nome, descricao, origem = "04_E2_MD5_Auxiliar", "Verificações MD5 dos testes auxiliares feitos enquanto o servidor estava indisponível; não entram nos resultados principais.", "Entrega 2 — servidor indisponível"
        elif tipo == "entrega1_saw_historico":
            nome, descricao, origem = "03_E1_SAW_Historico", "Medição histórica do Stop-and-Wait na Entrega 1.", "Entrega 1 remota"
        elif tipo == "janela_perda" and protocolo == "GBN":
            nome, descricao, origem = "01_E2_GBN_Janela", "Médias de GBN na Entrega 2, com janela, perda, vazão, tempo e retransmissões.", "Entrega 2 remota"
        elif tipo == "janela_perda" and protocolo == "SR":
            nome, descricao, origem = "06_E2_SR_Janela", "Médias de Selective Repeat na Entrega 2, com janela, perda, vazão, tempo e retransmissões.", "Entrega 2 remota"
        elif tipo == "janela_perda" and protocolo == "SAW":
            nome, descricao, origem = "05_E2_SAW_Janela", "Médias de Stop-and-Wait na Entrega 2, com perda, vazão, tempo e retransmissões.", "Entrega 2 remota"
        elif tipo == "throughput_integrado" and protocolo == "GBN":
            nome, descricao, origem = "02_E3_GBN_Integrado", "Comparação integrada do GBN na Entrega 3, arquivo small.", "Entrega 3 remota"
        elif tipo == "throughput_integrado" and protocolo == "SAW":
            nome, descricao, origem = "07_E3_SAW_Integrado", "Comparação integrada do Stop-and-Wait na Entrega 3, arquivo large.", "Entrega 3 remota"
        elif tipo == "throughput_integrado" and protocolo == "SR":
            nome, descricao, origem = "08_E3_SR_Integrado", "Comparação integrada do Selective Repeat na Entrega 3, arquivo small.", "Entrega 3 remota"
        else:
            raise SystemExit(f"Não foi possível classificar {path.name}: {tipo}/{protocolo}")
        sheets.append((nome, rows, descricao, origem, False))
    ordem = {
        "03_E1_SAW_Historico": 1,
        "01_E2_GBN_Janela": 2,
        "04_E2_MD5_Auxiliar": 3,
        "05_E2_SAW_Janela": 4,
        "06_E2_SR_Janela": 5,
        "02_E3_GBN_Integrado": 6,
        "07_E3_SAW_Integrado": 7,
        "08_E3_SR_Integrado": 8,
    }
    sheets[1:] = sorted(sheets[1:], key=lambda item: ordem[item[0]])
    readme_rows = [[nome, descricao, origem] for nome, _, descricao, origem, _ in sheets[1:]]
    legenda = [
        [],
        ["Legenda das colunas", "Descrição", ""],
        ["tipo_dado / fonte", "Classifica o tipo de registro e sua origem.", ""],
        ["protocolo / arquivo / janela", "Identifica o protocolo, o tamanho do arquivo e a janela usada.", ""],
        ["timeout_mode / timeout_s", "Indica timeout fixo ou adaptativo e o valor inicial em segundos.", ""],
        ["loss_rate / n", "Taxa de perda configurada e número de execuções agregadas.", ""],
        ["throughput_kbps / duracao_s", "Vazão média em kbit/s e duração média em segundos.", ""],
        ["retransmissoes / rtt_medio_ms", "Custo de recuperação e RTT médio, quando disponível.", ""],
        ["md5_* / checksum_verificado", "Valores de integridade e resultado da verificação MD5.", ""],
        ["Observação", "Os testes auxiliares feitos enquanto o servidor estava indisponível ficam identificados e não devem ser usados nos resultados principais.", ""],
    ]
    sheets[0] = ("00_Leia-me", [["Aba", "O que contém", "Origem"], *readme_rows, *legenda], "", "", True)
    workbook_sheets = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i+1}"/>' for i, (name, *_rest) in enumerate(sheets, 1))
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<sheets>{workbook_sheets}</sheets></workbook>')
    relationships = ''.join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>{relationships}'
            '</Relationships>')
    workbook_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     + ''.join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                     + f'<Relationship Id="rId{len(sheets)+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    content = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
               + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
               + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="4"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/><color rgb="FFFFFF"/></font><font><b/><sz val="14"/><name val="Arial"/><color rgb="FFFFFF"/></font><font><i/><sz val="10"/><name val="Arial"/><color rgb="1F4E78"/></font></fonts>'
              '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="1F4E78"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="D9EAF7"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="EEF5FB"/><bgColor indexed="64"/></patternFill></fill></fills>'
              '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="1" borderId="0" applyFont="1" applyFill="1"/><xf numFmtId="0" fontId="2" fillId="1" borderId="0" applyFont="1" applyFill="1"/><xf numFmtId="0" fontId="3" fillId="2" borderId="0" applyFont="1" applyFill="1"/><xf numFmtId="0" fontId="0" fillId="3" borderId="0" applyFill="1"/></cellXfs>'
              '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/styles.xml", styles)
        for index, (_, rows, descricao, origem, readme) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows, descricao, origem, readme))
    print(OUTPUT)


if __name__ == "__main__":
    main()
