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
MAX_FILE_CHARS = int(__import__("os").environ.get("BUILDER_MAX_FILE_CHARS", "24000"))
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml", ".eml", ".xml", ".log"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
VISION_MODEL = "anthropic/claude-opus-5.5"
DESCRIBE = ("This image is part of a bank's documents for building a phone agent (for example a call flow drawing, a table, "
            "a screenshot or a scanned page). Transcribe ALL text in it exactly, in its original language. If it is a diagram or "
            "flowchart, then describe every box and every arrow as a list: 'from step -> to step [condition on the arrow]', "
            "so that the whole flow can be rebuilt from your text. Do not summarise or leave anything out.")


def _describe(data, mime, name, trace=None):
    """Turn an image into text with a vision model (flow drawings and scans carry rules too)."""
    import base64
    import llm
    url = "data:" + mime + ";base64," + base64.b64encode(data).decode()
    try:
        return llm.call([{"role": "user", "content": [{"type": "text", "text": DESCRIBE},
                                                      {"type": "image_url", "image_url": {"url": url}}]}],
                        model=VISION_MODEL, purpose="read image " + name, max_tokens=6000, trace=trace)
    except Exception as exc:
        warnings.warn("Could not read image %s: %s" % (name, exc), stacklevel=2)
        return ""


def _describe_page(page, name, trace=None):
    """Tall pages (long flow drawings) are read in overlapping slices so small labels stay legible."""
    import pymupdf
    r = page.rect
    parts = max(1, min(6, int(round(r.height / max(r.width, 1)))))
    if parts == 1:
        return _describe(page.get_pixmap(dpi=110).tobytes("png"), "image/png", name, trace)
    out = []
    for k in range(parts):
        y0, y1 = max(0, r.height * k / parts - 40), min(r.height, r.height * (k + 1) / parts + 40)
        png = page.get_pixmap(dpi=110, clip=pymupdf.Rect(0, y0, r.width, y1)).tobytes("png")
        out.append("[part %d of %d, top to bottom; arrows may continue from the previous part]\n" % (k + 1, parts)
                   + _describe(png, "image/png", "%s part %d/%d" % (name, k + 1, parts), trace))
    return "\n".join(out)


def _html(text):
    import html, re
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def _office_media(path, trace):
    """Images embedded in a Word/PowerPoint file (a flow drawing pasted into a document)."""
    out = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            ext = posixpath.splitext(n)[1].lower()
            if "/media/" in n and ext in IMAGE_TYPES and z.getinfo(n).file_size > 2000:
                d = _describe(z.read(n), IMAGE_TYPES[ext], path.name + ":" + posixpath.basename(n), trace)
                if d:
                    out.append("[image " + posixpath.basename(n) + "]\n" + d)
    return out


def _pptx(path):
    import re
    out = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
        for i, n in enumerate(slides, 1):
            root = ET.fromstring(z.read(n))
            words = [t.text for t in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t") if t.text]
            out.append("## Slide %d\n%s" % (i, " ".join(words)))
    return "\n".join(out)


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


def load_case(paths, trace=None):
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
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            elif suffix in (".html", ".htm"):
                text = _html(path.read_text(encoding="utf-8-sig", errors="replace"))
            elif suffix == ".svg":
                text = _html(path.read_text(encoding="utf-8-sig", errors="replace"))
            elif suffix in IMAGE_TYPES:
                text = _describe(path.read_bytes(), IMAGE_TYPES[suffix], path.name, trace)
                if not text:
                    continue
            elif suffix == ".docx":
                text = "\n\n".join([_docx(path)] + _office_media(path, trace))
            elif suffix == ".pptx":
                text = "\n\n".join([_pptx(path)] + _office_media(path, trace))
            elif suffix == ".xlsx":
                text = _xlsx(path)
            elif suffix == ".pdf":
                try:
                    import pymupdf
                    pages = []
                    with pymupdf.open(path) as doc:
                        for i, page in enumerate(doc, 1):
                            t = page.get_text()
                            # a page that is mostly a drawing (flowchart, scan) is read by a vision model
                            # a flowchart keeps its box labels as text but its arrows only as drawings: read those pages too
                            if (len(t.strip()) < 200 and (page.get_images() or page.get_drawings())) or len(page.get_drawings()) > 30:
                                d = _describe_page(page, "%s page %d" % (path.name, i), trace)
                                t = (t + "\n[page drawing]\n" + d) if d else t
                            pages.append(t)
                    text = "\n".join(pages)
                except Exception as exc:
                    warnings.warn("Skipping PDF %s: %s" % (path, exc), stacklevel=2)
                    continue
            else:
                raw = path.read_bytes()[:200000]
                try:                                     # unknown extension: keep it if it is text
                    text = raw.decode("utf-8")
                    if sum(ch.isprintable() or ch in "\n\r\t" for ch in text) < 0.95 * max(1, len(text)):
                        raise ValueError
                except ValueError:
                    warnings.warn("Skipping unreadable file %s" % path, stacklevel=2)
                    continue
            name = path.relative_to(root).as_posix()
            if len(text) > MAX_FILE_CHARS:
                # a bulk data file (test records, exports) would drown the documents: keep its head as a sample
                text = (text[:MAX_FILE_CHARS] + "\n[... file truncated: %d of %d characters shown. It is bulk data; read "
                        "its structure from the sample above and its overview documents.]" % (MAX_FILE_CHARS, len(text)))
            files.append(name)
            chunks.append("=== FILE: " + name + " ===\n" + text)
            if openapi is None:
                openapi = _openapi(text, suffix)
    text = "\n\n".join(chunks)
    return {"text": text, "files": files, "openapi": openapi, "contract_text": text}
