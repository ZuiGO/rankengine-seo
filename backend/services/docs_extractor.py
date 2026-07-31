import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS_DOC = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_PPT = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_CORE = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
NS_DC = "{http://purl.org/dc/elements/1.1/}"
NS_DCTERMS = "{http://purl.org/dc/terms/}"
NS_EP = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"


def _core_metadata(zf: zipfile.ZipFile) -> dict:
    meta = {}
    try:
        root = ET.fromstring(zf.read("docProps/core.xml"))
    except (KeyError, ET.ParseError):
        return meta
    for tag, key in [
        (NS_DC + "title", "title"),
        (NS_DC + "creator", "author"),
        (NS_DC + "subject", "subject"),
        (NS_DC + "description", "description"),
        (NS_DCTERMS + "created", "created"),
        (NS_DCTERMS + "modified", "modified"),
    ]:
        el = root.find(tag)
        if el is not None and el.text:
            meta[key] = el.text.strip()
    try:
        app_root = ET.fromstring(zf.read("docProps/app.xml"))
        pages = app_root.find(NS_EP + "Pages")
        words = app_root.find(NS_EP + "Words")
        if pages is not None and pages.text:
            meta["pages"] = int(pages.text)
        if words is not None and words.text:
            meta["word_count_estimate"] = int(words.text)
    except (KeyError, ET.ParseError):
        pass
    return meta


def _extract_text_with_breaks(root, text_tag, para_tag):
    paragraphs = []
    for p in root.iter(para_tag):
        texts = [t.text or "" for t in p.iter(text_tag)]
        paragraphs.append("".join(texts).strip())
    return "\n".join(paragraphs).strip()


def extract_docx(file_path: str) -> dict:
    with zipfile.ZipFile(file_path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
        body = root.find(NS_DOC + "body")
        body = body if body is not None else root

        paragraphs = []
        tables = []
        for element in body:
            tag = element.tag
            if tag == NS_DOC + "p":
                text = "".join(t.text or "" for t in element.iter(NS_DOC + "t")).strip()
                if text:
                    paragraphs.append(text)
            elif tag == NS_DOC + "tbl":
                rows = []
                for tr in element.iter(NS_DOC + "tr"):
                    cells = []
                    for tc in tr.iter(NS_DOC + "tc"):
                        cell_text = " ".join(
                            "".join(t.text or "" for t in tc.iter(NS_DOC + "t")).strip()
                            for _ in [0]
                        )
                        cells.append(cell_text)
                    rows.append(cells)
                if rows:
                    tables.append({"rows": len(rows), "cols": max(len(r) for r in rows), "headers": rows[0], "data": rows})

        text = "\n".join(paragraphs)
        return {
            "text": text,
            "word_count": len(text.split()),
            "text_chunks": _chunk_text(text),
            "tables": tables,
            "metadata": _core_metadata(zf),
        }


def extract_xlsx(file_path: str) -> dict:
    with zipfile.ZipFile(file_path) as zf:
        shared = []
        try:
            shared_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in shared_root.iter(NS_SHEET + "si"):
                shared.append("".join(t.text or "" for t in si.iter(NS_SHEET + "t")).strip())
        except (KeyError, ET.ParseError):
            pass

        sheets = []
        sheet_files = sorted(
            (n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")),
            key=lambda n: int("".join(ch for ch in n.split("/")[-1] if ch.isdigit())),
        )
        for sheet_file in sheet_files:
            try:
                root = ET.fromstring(zf.read(sheet_file))
            except ET.ParseError:
                continue
            rows = []
            for row in root.iter(NS_SHEET + "row"):
                row_values = []
                for c in row.iter(NS_SHEET + "c"):
                    v = c.find(NS_SHEET + "v")
                    val = ""
                    if v is not None and v.text:
                        val = v.text
                        if c.get("t") == "s":
                            idx = int(val)
                            val = shared[idx] if idx < len(shared) else ""
                    row_values.append(val)
                if any(row_values):
                    rows.append(row_values)
            if rows:
                sheets.append({"name": sheet_file.split("/")[-1], "rows": len(rows), "cols": max(len(r) for r in rows), "headers": rows[0], "data": rows})

        text = "\n".join("\t".join(r) for s in sheets for r in s["data"])
        return {
            "text": text,
            "word_count": len(text.split()),
            "text_chunks": _chunk_text(text),
            "tables": sheets,
            "metadata": _core_metadata(zf),
        }


def extract_pptx(file_path: str) -> dict:
    with zipfile.ZipFile(file_path) as zf:
        slides = []
        slide_files = sorted(
            (n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")),
            key=lambda n: int("".join(ch for ch in n.split("/")[-1] if ch.isdigit())),
        )
        for slide_file in slide_files:
            try:
                root = ET.fromstring(zf.read(slide_file))
            except ET.ParseError:
                continue
            texts = [t.text or "" for t in root.iter(NS_PPT + "t")]
            slide_text = "\n".join(t.strip() for t in texts if t.strip())
            if slide_text:
                slides.append({"index": slide_file.split("/")[-1], "text": slide_text})

        text = "\n\n".join(s["text"] for s in slides)
        return {
            "text": text,
            "word_count": len(text.split()),
            "text_chunks": _chunk_text(text),
            "slides": slides,
            "metadata": _core_metadata(zf),
        }


def extract_doc_file(file_path: str, content_type: str) -> dict:
    try:
        if content_type == "doc":
            return extract_docx(file_path)
        if content_type == "xlsx":
            return extract_xlsx(file_path)
        if content_type == "presentation":
            return extract_pptx(file_path)
    except (zipfile.BadZipFile, ET.ParseError, KeyError):
        return {"error": "Failed to parse document"}
    return {"error": "Unsupported type"}


def _chunk_text(text: str, max_words: int = 500) -> list[dict]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_words):
        chunk = " ".join(words[i:i + max_words])
        chunks.append({"text": chunk, "word_count": len(chunk.split())})
    return chunks
