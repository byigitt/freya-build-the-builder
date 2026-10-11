"""Print every table in a test-customer file (xlsx, csv, md, docx) as JSON rows keyed by the header row.

    python3 mock/tools/table_rows.py <file> > /tmp/rows.json
Used to fill mock/src/customers.js from the case's test customers.
"""
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "builder"))
import ingest


def num(v):
    s = v.strip()
    try:
        return int(s) if s.lstrip("-").isdigit() and not (len(s) > 1 and s.startswith("0")) else float(s) if "." in s and s.replace(".", "", 1).lstrip("-").isdigit() else s
    except ValueError:
        return s


def tables(text):
    out, cur, header, name = {}, None, None, "table"
    for line in text.splitlines():
        if line.startswith("## SHEET:") or line.startswith("=== FILE:"):
            name, header = line.split(":", 1)[1].strip(" ="), None
            continue
        if "|" not in line or set(line.replace("|", "").strip()) <= set("-: "):
            if not line.strip():
                header = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            cur = out.setdefault(name, [])
            continue
        cur.append({h or ("col%d" % i): num(c) for i, (h, c) in enumerate(zip(header, cells))})
    return out


if __name__ == "__main__":
    print(json.dumps(tables(ingest.load_case([sys.argv[1]])["text"]), ensure_ascii=False, indent=1))
