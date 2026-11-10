from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "entrega-3" / "relatorio" / "anexos"
OUTPUT = ROOT / "entrega-3" / "para_upload" / "resumo_entregas_1_2_3.xlsx"

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
        if math.isfinite(number):
            return f'<c r="{ref}"{sty}><v>{escape(value)}</v></c>'
    except (ValueError, TypeError):
        pass
    return f'<c r="{ref}"{sty} t="inlineStr"><is><t>{escape(value)}</t></is></c>'

def sheet_xml(rows, title="", description="", readme=False):
    if not readme:
        rows = [[title], [description], [], *rows]
    max_col = max((len(r) for r in rows), default=1)
    body = []
    for ri, row in enumerate(rows, 1):
        if readme:
            style = 1 if ri == 1 else (4 if ri % 2 == 0 else 0)
        else:
            style = 2 if ri == 1 else (3 if ri == 2 else (1 if ri == 4 else (4 if ri % 2 else 0)))
        body.append(f'<row r="{ri}">' + ''.join(cell(f'{col(ci)}{ri}', v, style) for ci, v in enumerate(row, 1)) + '</row>')
    max_ref = f'{col(max_col)}{len(rows)}'
    top, split = ("A1", 0) if readme else ("A5", 4)
    filt = f'A1:{max_ref}' if readme else f'A4:{max_ref}'
    merges = "" if readme else f'<mergeCells count="2"><mergeCell ref="A1:{col(max_col)}1"/><mergeCell ref="A2:{col(max_col)}2"/></mergeCells>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="A1:{max_ref}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="{split}" topLeftCell="{top}" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="{top}" sqref="{top}"/></sheetView></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/><cols><col min="1" max="1" width="24" customWidth="1"/><col min="2" max="200" width="18" customWidth="1"/></cols>'
            f'<sheetData>{"".join(body)}</sheetData><autoFilter ref="{filt}"/>{merges}<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.3" footer="0.3"/></worksheet>')

def num(values):
    out = []
    for v in values:
        try:
            x = float(v)
            if math.isfinite(x): out.append(x)
        except (ValueError, TypeError):
            pass
    return out

def infer_size(rows, header):
    if "arquivo" in header:
        i = header.index("arquivo")
        vals = {r[i].lower() for r in rows if len(r) > i and r[i].lower() in {"small", "medium", "large"}}
        if vals: return sorted(vals)[0]
    n = len(rows)
    return "large" if n >= 18000 else ("medium" if n >= 8000 else ("small" if n >= 1500 else "auxiliar/legado"))

def main():
    files = sorted(p for p in SOURCE.rglob("metrics_*.csv") if p.parent != SOURCE)
    if not files: raise SystemExit("Nenhum CSV bruto encontrado")
    raw_count = len(files)
    headers = set()
    summary = []
    for order, path in enumerate(files, 1):
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        headers.update(fieldnames)
        key = path.relative_to(SOURCE).parts[0]
        delivery = {"entrega1": "Entrega 1", "entrega2_historica": "Entrega 2 (auxiliar)", "entrega2_remota": "Entrega 2", "entrega3": "Entrega 3"}.get(key, key)
        proto = (next((r.get("protocolo") for r in rows if r.get("protocolo")), "") or path.stem.split("_")[2]).upper()
        size = infer_size([list(r.values()) for r in rows], fieldnames)
        if fieldnames and "arquivo" in fieldnames:
            vals = {r.get("arquivo", "").lower() for r in rows if r.get("arquivo", "").lower() in {"small", "medium", "large"}}
            if vals: size = sorted(vals)[0]
        def vals(*names): return num([r.get(n, "") for r in rows for n in names])
        rtt, est, dev = vals("rtt_ms"), vals("rtt_estimated_ms", "rtt_est_ms"), vals("dev_rtt_ms")
        thr = vals("throughput_kbps")
        if not thr: thr = [x / 1000 for x in vals("throughput_bps")]
        retrans = vals("retransmissoes", "retransmissions")
        timeout = vals("timeout_ms", "timeout_used_ms", "timeout_usado_ms")
        elapsed = vals("elapsed_s", "received_elapsed_s", "duracao_s")
        def avg(a): return sum(a) / len(a) if a else ""
        first = rows[0] if rows else {}
        env = "servidor_indisponivel" if "servidor_indisponivel" in str(path) else "remoto"
        summary.append([order, delivery, size, proto, env, path.name, len(rows), len(fieldnames), first.get("grupo", ""), first.get("servidor", ""), first.get("janela", first.get("window_size", "")), first.get("timeout_mode", ""), first.get("timeout_s", ""), first.get("loss_rate", first.get("simulated_loss", "")), avg(thr), avg(elapsed), avg(retrans), avg(rtt), avg(est), avg(dev), avg(timeout), sum(1 for r in rows if str(r.get("timeout_ocorrido", r.get("timeout_occurred", ""))).lower() in {"1", "true"}), first.get("md5", "")])

    detail_header = ["ordem", "entrega", "tamanho", "protocolo", "ambiente", "csv", "segmentos", "colunas", "grupo", "servidor", "janela", "timeout_mode", "timeout_s", "loss_rate", "throughput_medio_kbps", "tempo_medio_s", "retransmissoes_media", "rtt_medio_ms", "rtt_estimado_medio_ms", "dev_rtt_medio_ms", "timeout_medio_ms", "timeouts", "md5"]
    grouped = defaultdict(list)
    for row in summary: grouped[(row[1], row[2], row[3])].append(row)
    agg = [["entrega", "tamanho", "protocolo", "arquivos", "segmentos", "throughput_medio_kbps", "tempo_medio_s", "retransmissoes_media", "rtt_medio_ms", "rtt_estimado_medio_ms", "dev_rtt_medio_ms", "timeout_medio_ms", "timeouts"]]
    for key, rows in sorted(grouped.items()):
        def av(i):
            a = num([r[i] for r in rows]); return round(sum(a)/len(a), 6) if a else ""
        agg.append([*key, len(rows), sum(int(r[6]) for r in rows), av(14), av(15), av(16), av(17), av(18), av(19), av(20), sum(int(r[21]) for r in rows)])
    coverage = [["entrega", "small", "medium", "large", "observação"]]
    for d in ("Entrega 1", "Entrega 2", "Entrega 3"):
        counts = {s: sum(1 for r in summary if r[1] == d and r[2] == s) for s in ("small", "medium", "large")}
        coverage.append([d, counts["small"], counts["medium"], counts["large"], "Entrega 2 auxiliar separado" if d == "Entrega 2" else "dados resumidos dos 149 CSVs"])
    readme = [["Aba", "Conteúdo", "Como ler"], ["01_Resumo_149", f"Uma linha para cada CSV bruto ({raw_count} arquivos)", "Todos os arquivos estão representados"], ["02_Agregado", "Médias por entrega, tamanho e protocolo", "Visão compacta para comparação"], ["03_Cobertura", "Presença de small/medium/large", "Confere a cobertura das três entregas"], ["Observação", "Entrega 2 auxiliar", "Feita durante indisponibilidade do servidor; não usar nas médias principais"], ["Métricas", "RTT/RTO, vazão, tempo, retransmissões e timeouts", "Médias calculadas apenas quando o campo existia no CSV"]]
    sheets = [("00_Leia-me", readme, "Resumo leve das Entregas 1, 2 e 3", "", True), ("01_Resumo_149", [detail_header, *summary], "149 CSVs brutos resumidos", "Uma linha por CSV; nenhum arquivo omitido", False), ("02_Agregado", agg, "Médias por entrega, tamanho e protocolo", "Dados agregados dos 149 CSVs", False), ("03_Cobertura", coverage, "Cobertura por entrega e tamanho", "small, medium e large", False)]
    rels = ''.join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets)+1))
    wb_sheets = ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i+1}"/>' for i, (name, *_rest) in enumerate(sheets, 1))
    workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + wb_sheets + '</sheets></workbook>'
    package_rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' + rels + '</Relationships>'
    wrels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels + f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    content = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets)+1)) + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>'
    styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="4"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/><color rgb="FFFFFF"/></font><font><b/><sz val="14"/><name val="Arial"/><color rgb="FFFFFF"/></font><font><i/><sz val="10"/><name val="Arial"/><color rgb="1F4E78"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="1F4E78"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="D9EAF7"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="EEF5FB"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="0" fontId="1" fillId="1" borderId="0"/><xf numFmtId="0" fontId="2" fillId="1" borderId="0"/><xf numFmtId="0" fontId="3" fillId="2" borderId="0"/><xf numFmtId="0" fontId="0" fillId="3" borderId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content); z.writestr("_rels/.rels", package_rels); z.writestr("xl/workbook.xml", workbook); z.writestr("xl/_rels/workbook.xml.rels", wrels); z.writestr("xl/styles.xml", styles)
        for i, (_, rows, title, desc, readme_flag) in enumerate(sheets, 1): z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows, title, desc, readme_flag))
    print(OUTPUT)

if __name__ == "__main__": main()
