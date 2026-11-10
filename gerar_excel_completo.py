from __future__ import annotations

import csv
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "entrega-3" / "relatorio" / "anexos"
OUTPUT = ROOT / "entrega-3" / "para_upload" / "dados_completos_149_csvs.xlsx"

def col(n):
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out

def cell(ref, value, style=0):
    value = "" if value is None else str(value)
    sty = f' s="{style}"' if style else ""
    if value == "":
        return f'<c r="{ref}"{sty} t="inlineStr"><is><t></t></is></c>'
    try:
        number = float(value)
        if number == number and abs(number) != float("inf"):
            return f'<c r="{ref}"{sty}><v>{escape(value)}</v></c>'
    except ValueError:
        pass
    return f'<c r="{ref}"{sty} t="inlineStr"><is><t>{escape(value)}</t></is></c>'

def sheet_xml(rows, title="", description="", readme=False):
    if not readme:
        rows = [[title], [description], [], *rows]
    max_col = max((len(r) for r in rows), default=1)
    body = []
    for ri, row in enumerate(rows, 1):
        style = (1 if ri == 1 else (4 if ri % 2 == 0 else 0)) if readme else (2 if ri == 1 else (3 if ri == 2 else (1 if ri == 4 else (4 if ri % 2 else 0))))
        body.append(f'<row r="{ri}">' + ''.join(cell(f'{col(ci)}{ri}', v, style) for ci, v in enumerate(row, 1)) + '</row>')
    max_ref = f'{col(max_col)}{len(rows)}'
    top, split = ("A1", 0) if readme else ("A5", 4)
    filt = f'A1:{max_ref}' if readme else f'A4:{max_ref}'
    merges = "" if readme else f'<mergeCells count="2"><mergeCell ref="A1:{col(max_col)}1"/><mergeCell ref="A2:{col(max_col)}2"/></mergeCells>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{max_ref}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="{split}" topLeftCell="{top}" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="{top}" sqref="{top}"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/><cols><col min="1" max="1" width="24" customWidth="1"/><col min="2" max="200" width="18" customWidth="1"/></cols>'
            f'<sheetData>{"".join(body)}</sheetData><autoFilter ref="{filt}"/>{merges}<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.3" footer="0.3"/></worksheet>')

def infer_size(data_rows, path, header):
    if "arquivo" in header:
        i = header.index("arquivo")
        vals = {r[i] for r in data_rows if len(r) > i and r[i]}
        if vals:
            return sorted(vals)[0]
    n = len(data_rows)
    return "large" if n >= 18000 else ("medium" if n >= 8000 else ("small" if n >= 1500 else "auxiliar/legado"))

def main():
    raw_files = sorted(p for p in SOURCE.rglob("metrics_*.csv") if p.parent != SOURCE)
    if len(raw_files) != 149:
        raise SystemExit(f"Esperados 149 CSVs brutos; encontrados {len(raw_files)}")
    info = []
    for idx, path in enumerate(raw_files, 1):
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        header, data = rows[0], rows[1:]
        key = path.relative_to(SOURCE).parts[0]
        delivery = {"entrega1": "Entrega 1", "entrega2_historica": "Entrega 2 (auxiliar)", "entrega2_remota": "Entrega 2", "entrega3": "Entrega 3"}.get(key, key)
        proto = path.stem.split("_")[2].upper()
        size = infer_size(data, path, header)
        short_delivery = {"entrega1": "E1", "entrega2_historica": "E2A", "entrega2_remota": "E2", "entrega3": "E3"}.get(key, key[:3])
        sheet = f"{idx:03d}_{short_delivery}_{proto}_{size}"[:31]
        info.append((sheet, path, rows, delivery, proto, size, len(header), len(data)))
    readme = [["Aba", "Conteúdo", "Observação"], ["01_Resumo_149", "Inventário dos 149 CSVs brutos", "Ordenado por entrega, tamanho e protocolo"], ["002–150", "Um CSV completo por aba", "Nenhuma linha ou coluna foi removida"], ["Nota", "Entrega 2 (auxiliar)", "Servidor indisponível; excluir das comparações principais"], ["Campos", "RTT/RTO", "rtt_ms, rtt_estimated_ms, dev_rtt_ms, timeout_ms e timeout_used_ms quando registrados"], ["Campos", "Integridade", "MD5 e checksums quando registrados"]]
    summary = [["ordem", "aba", "entrega", "tamanho", "protocolo", "arquivo_csv", "linhas_dados", "colunas", "ambiente", "observacao"]]
    for idx, (sheet, path, rows, delivery, proto, size, ncols, nrows) in enumerate(info, 1):
        env = "servidor_indisponivel" if "servidor_indisponivel" in str(path) else "remoto"
        obs = "auxiliar; excluir das comparações principais" if "auxiliar" in delivery else "dados brutos preservados"
        summary.append([idx, sheet, delivery, size, proto, str(path.relative_to(SOURCE)), nrows, ncols, env, obs])
    sheets = [("00_Leia-me", readme, "", "", True), ("01_Resumo_149", summary, "Inventário dos 149 CSVs brutos", "Todos preservados", False)]
    sheets.extend((sheet, rows, f"CSV bruto completo: {path.name}", f"{delivery} | {proto} | {size}", False) for sheet, path, rows, delivery, proto, size, _, _ in info)
    rels = ''.join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1))
    workbook_sheets = ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i+1}"/>' for i, (name, *_rest) in enumerate(sheets, 1))
    workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + workbook_sheets + '</sheets></workbook>'
    package_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' + rels + '</Relationships>'
    workbook_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels + f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    content = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1)) + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'
    styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="4"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/><color rgb="FFFFFF"/></font><font><b/><sz val="14"/><name val="Arial"/><color rgb="FFFFFF"/></font><font><i/><sz val="10"/><name val="Arial"/><color rgb="1F4E78"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="1F4E78"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="D9EAF7"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="EEF5FB"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="1" borderId="0"/><xf numFmtId="0" fontId="2" fillId="1" borderId="0"/><xf numFmtId="0" fontId="3" fillId="2" borderId="0"/><xf numFmtId="0" fontId="0" fillId="3" borderId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content); z.writestr("_rels/.rels", package_rels); z.writestr("xl/workbook.xml", workbook); z.writestr("xl/_rels/workbook.xml.rels", workbook_rels); z.writestr("xl/styles.xml", styles)
        for i, (_, rows, title, desc, is_readme) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows, title, desc, is_readme))
    print(OUTPUT)

if __name__ == "__main__":
    main()
