"""Read a case folder (including Office documents and PDFs) as labelled plain text."""
import json
import pathlib
import posixpath
import warnings
import zipfile
import xml.etree.ElementTree as ET


WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}


def _word_text(node):
    return "".join(el.text or "" if el.tag == WORD + "t" else "\t" if el.tag == WORD + "tab" else "\n"
                   for el in node.iter() if el.tag in {WORD + "t", WORD + "tab", WORD + "br"})


def _docx(path):
    with zipfile.ZipFile(path) as archive:
        body = ET.fromstring(archive.read("word/document.xml")).find(WORD + "body")
    lines = []
    for node in body if body is not None else []:
        if node.tag == WORD + "p":
            lines.append(_word_text(node))
        elif node.tag == WORD + "tbl":
            for row in node.findall(WORD + "tr"):
                lines.append(" | ".join("\n".join(_word_text(p) for p in cell.findall(WORD + "p"))
                                        for cell in row.findall(WORD + "tc")))
    return "\n".join(lines)


def _xlsx(path):
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(t.text or "" for t in si.iter(SHEET + "t"))
                      for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target") for rel in rels if rel.get("TargetMode") != "External"}
        lines = []
        for sheet in workbook.findall(SHEET + "sheets/" + SHEET + "sheet"):
            lines.append("## SHEET: " + sheet.get("name", ""))
            target = targets[sheet.get(REL + "id")]
            member = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            root = ET.fromstring(archive.read(member))
            for row in root.findall(SHEET + "sheetData/" + SHEET + "row"):
                cells = []
                for cell in row.findall(SHEET + "c"):
                    column = 0
                    for char in cell.get("r", ""):
                        if char.isalpha():
                            column = column * 26 + ord(char.upper()) - ord("A") + 1
                        else:
                            break
                    while len(cells) < column - 1:
                        cells.append("")
                    value = cell.findtext(SHEET + "v", "")
                    if cell.get("t") == "s":
                        value = shared[int(value)] if value else ""
                    elif cell.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.iter(SHEET + "t"))
                    elif not value and cell.find(SHEET + "f") is not None:
                        value = "=" + cell.findtext(SHEET + "f", "")
                    cells.append(value)
                lines.append(" | ".join(cells))
        return "\n".join(lines)


def _openapi(text, suffix):
    if suffix not in {".json", ".yaml", ".yml"}:
        return None
    if suffix == ".json":
        try:
            doc = json.loads(text)
        except ValueError:
            return None
    else:
        try:
            import yaml
        except ImportError:
            return None
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            return None
    if isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc) and isinstance(doc.get("paths"), dict):
        return doc
    return None


def load_case(paths):
    """Return text, relative file names, an optional API document, and all contract context."""
    if isinstance(paths, (str, pathlib.Path)):
        paths = [paths]
    files, chunks, openapi, seen = [], [], None, set()
    for entry in paths:
        entry = pathlib.Path(entry)
        if not entry.exists():
            raise FileNotFoundError(entry)
        root = entry if entry.is_dir() else entry.parent
        candidates = sorted(entry.rglob("*")) if entry.is_dir() else [entry]
        for path in candidates:
            if not path.is_file() or path.resolve() in seen:
                continue
            seen.add(path.resolve())
            suffix = path.suffix.lower()
            if suffix in TEXT_SUFFIXES:
                text = path.read_text(encoding="utf-8-sig")
            elif suffix == ".docx":
                text = _docx(path)
            elif suffix == ".xlsx":
                text = _xlsx(path)
            elif suffix == ".pdf":
                try:
                    import pymupdf
                    with pymupdf.open(path) as doc:
                        text = "\n".join(page.get_text() for page in doc)
                except Exception as exc:
                    warnings.warn("Skipping PDF %s: %s" % (path, exc), stacklevel=2)
                    continue
            else:
                continue
            name = path.relative_to(root).as_posix()
            files.append(name)
            chunks.append("=== FILE: " + name + " ===\n" + text)
            if openapi is None:
                openapi = _openapi(text, suffix)
    text = "\n\n".join(chunks)
    return {"text": text, "files": files, "openapi": openapi, "contract_text": text}
