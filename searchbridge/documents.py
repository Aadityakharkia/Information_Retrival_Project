"""Document model and loaders for PDFs, text, Markdown, HTML, JSON(L) and Cranfield."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple


@dataclass
class Document:
    doc_id: str
    title: str
    text: str
    meta: Dict[str, str] = field(default_factory=dict)
    links: List[str] = field(default_factory=list)  # outgoing links / citations (doc_ids or URLs)
    tags: List[str] = field(default_factory=list)   # author keyphrases / user tags

    @property
    def display_title(self) -> str:
        t = self.title.strip() or self.doc_id
        if t == t.lower():  # e.g. Cranfield titles are all lower-case
            small = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}
            t = " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(t.split()))
        return t

    @property
    def full_text(self) -> str:
        return f"{self.title}\n{self.text}" if self.title else self.text


# --------------------------------------------------------------------------- loaders
def _read_pdf_with_title(path: Path) -> Tuple[str, str]:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install pypdf to index PDFs") from e
    reader = PdfReader(str(path))
    title = ""
    try:
        title = (reader.metadata.title or "").strip() if reader.metadata else ""
    except Exception:
        title = ""
    return "\n".join((p.extract_text() or "") for p in reader.pages), title


_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r"""href=["']([^"'#]+)""", re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


_SKIP_TAGS = {"script", "style", "noscript", "template", "nav", "header", "footer", "aside", "form", "button",
              "select", "svg", "figure", "sup"}
_INLINE = {"a", "span", "b", "i", "em", "strong", "code", "sub", "abbr", "small", "mark", "cite", "q", "u", "s", "kbd", "var"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# navigation / layout blocks by class or id (generic names plus MediaWiki's)
_BOILER = re.compile(r"(^|[\s_-])(nav|navbar|navbox|menu|sidebar|breadcrumb|footer|header|toc|cookie|banner|share|social|"
                     r"mw-editsection|mw-jump-link|catlinks|printfooter|reflist|references|vector-[\w-]+|mw-indicators|"
                     r"hatnote|shortdescription|noprint|infobox-navigation|sistersitebox)($|[\s_-])", re.I)
_MAIN = re.compile(r"^(mw-content-text|bodycontent|main-content|maincontent|content-main|article-body)$", re.I)


class _ContentExtractor(HTMLParser):
    """Keeps the readable content of a page: text and links inside <main>/<article> (or the MediaWiki
    content block) when the page has one, skipping navigation, sidebars, footers and edit links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: List[Tuple[str, bool, bool]] = []    # (tag, skipping, main)
        self.skip = 0
        self.main_depth = 0
        self.all_text: List[str] = []
        self.main_text: List[str] = []
        self.all_links: List[str] = []
        self.main_links: List[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "a" and a.get("href") and not self.skip:
            (self.main_links if self.main_depth else self.all_links).append(a["href"])
        if tag in _VOID:
            if tag == "br" and not self.skip:
                (self.main_text if self.main_depth else self.all_text).append(" ")
            return
        cls = f"{a.get('class', '')} {a.get('id', '')}"
        skipping = tag in _SKIP_TAGS or a.get("role") in ("navigation", "banner", "contentinfo") or bool(_BOILER.search(cls))
        is_main = tag in ("main", "article") or a.get("role") == "main" or bool(_MAIN.match(a.get("id", "") or ""))
        self.stack.append((tag, skipping, is_main))
        self.skip += skipping
        self.main_depth += is_main
        self._space(tag)

    def _space(self, tag):
        if tag not in _INLINE and not self.skip:          # block boundaries separate words
            (self.main_text if self.main_depth else self.all_text).append(" ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _VOID:
            return
        self._space(tag)
        for i in range(len(self.stack) - 1, -1, -1):        # tolerate unclosed tags
            if self.stack[i][0] == tag:
                for _, sk, mn in self.stack[i:]:
                    self.skip -= sk
                    self.main_depth -= mn
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self.skip:
            (self.main_text if self.main_depth else self.all_text).append(data)
            if self.main_depth:
                self.all_text.append(data)


def parse_html(raw: str) -> Tuple[str, str, List[str]]:
    """Return (title, main_text, hrefs): the page's main content and the links inside it, without menus,
    sidebars and footers. Falls back to all visible text when no content block can be found."""
    p = _ContentExtractor()
    try:
        p.feed(raw)
        p.close()
    except Exception:  # pragma: no cover - malformed HTML
        pass
    main = re.sub(r"\s+", " ", "".join(p.main_text)).strip()
    if len(main) >= 200:
        text, links = main, p.main_links
    else:
        text = re.sub(r"\s+", " ", "".join(p.all_text)).strip()
        links = p.all_links + p.main_links
    title = re.sub(r"\s+", " ", p.title).strip()
    return title, text, links


def load_file(path: Path) -> Optional[Document]:
    suf = path.suffix.lower()
    if suf == ".pdf":
        text, meta_title = _read_pdf_with_title(path)
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 3]
        guess = next((ln for ln in lines[:15] if 15 <= len(ln) <= 200 and not re.search(r"(arxiv|doi|http|@|vol\.|proceedings)", ln, re.I)),
                     lines[0] if lines else path.stem)
        title = meta_title if meta_title and len(meta_title) > 8 and not meta_title.lower().startswith(("microsoft", "untitled")) else guess
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # de-hyphenate line breaks
        return Document(path.name, title[:200], text, {"source": str(path), "type": "PDF", "category": "My documents"})
    if suf in {".txt", ".md", ".rst"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        first = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), path.stem)
        return Document(path.name, first[:200], text, {"source": str(path), "type": suf[1:].upper(), "category": "My documents"})
    if suf in {".html", ".htm"}:
        title, text, links = parse_html(path.read_text(encoding="utf-8", errors="ignore"))
        return Document(path.name, title or path.stem, text, {"source": str(path), "type": "HTML", "category": "My documents"}, links)
    return None


def load_directory(root: str | Path) -> List[Document]:
    root = Path(root)
    docs: List[Document] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
            if p.suffix.lower() in {".json", ".jsonl"} or p.name.endswith(".jsonl.gz"):
                docs.extend(load_jsonl(p))
                continue
            d = load_file(p)
            if d and d.text.strip():
                d.doc_id = str(p.relative_to(root))
                docs.append(d)
    return docs


def load_jsonl(path: str | Path) -> List[Document]:
    """Each record: {"id", "title", "text", optional "links", "tags", other keys -> meta}.
    Accepts .json (list), .jsonl and .jsonl.gz."""
    import gzip
    path = Path(path)
    if path.suffix == ".gz":
        raw = gzip.open(path, "rt", encoding="utf-8").read()
    else:
        raw = path.read_text(encoding="utf-8")
    records = json.loads(raw) if path.suffix == ".json" else [json.loads(l) for l in raw.splitlines() if l.strip()]
    docs = []
    for r in records:
        meta = {k: str(v) for k, v in r.items() if k not in {"id", "title", "text", "links", "tags"}}
        docs.append(Document(str(r["id"]), r.get("title", ""), r.get("text", ""), meta,
                             list(r.get("links", [])), list(r.get("tags", []))))
    return docs


# --------------------------------------------------------------------------- Cranfield
def _field(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def cranfield_venue(bib: str) -> str:
    """Coarse publication-venue group from the Cranfield <bib> field.
    Used as a class label (venue classification) and as a group for exposure-fairness audits."""
    b = bib.lower()
    if b.startswith("naca"):
        return "NACA report (US)"
    if b.startswith("nasa"):
        return "NASA report (US)"
    if b.startswith(("arc", "rae", "a.r.c", "r.a.e", "cranfield", "coa")):
        return "ARC/RAE report (UK)"
    if re.match(r"(j\.|jnl|journal|proc|aiaa|aero\.|q\. ?j|asme|trans|phil|zamm|zamp|z\.)", b):
        return "Journal / proceedings"
    return "Other / unknown"


def load_cranfield(root: str | Path) -> Tuple[List[Document], Dict[str, str], Dict[str, Dict[str, int]]]:
    """Cranfield 1400 test collection (Cleverdon, 1967) in TREC-style XML.

    Returns docs, queries {qid: text}, qrels {qid: {doc_id: grade}}.
    Note: qrel query ids are the *sequential* position (1..225) of the query in cran.qry.xml.
    """
    root = Path(root)
    raw = (root / "cran.all.1400.xml").read_text(encoding="utf-8", errors="ignore")
    docs = []
    for block in re.findall(r"<doc>(.*?)</doc>", raw, re.S):
        did = _field(block, "docno")
        bib = _field(block, "bib")
        docs.append(Document(did, _field(block, "title").rstrip(" ."), _field(block, "text"),
                             {"author": _field(block, "author"), "bib": bib, "venue": cranfield_venue(bib),
                              "category": cranfield_venue(bib), "type": "Abstract"}))
    qraw = (root / "cran.qry.xml").read_text(encoding="utf-8", errors="ignore")
    queries = {str(i + 1): _field(b, "title") for i, b in enumerate(re.findall(r"<top>(.*?)</top>", qraw, re.S))}
    qrels: Dict[str, Dict[str, int]] = {}
    for line in (root / "cranqrel.trec.txt").read_text().splitlines():
        parts = line.split()
        if len(parts) == 4:  # keep grade-0 rows: they are *judged non-relevant* (needed by BPref)
            qrels.setdefault(parts[0], {})[parts[2]] = int(parts[3])
    return docs, queries, qrels


def iter_text(docs: List[Document]) -> Iterator[Tuple[str, str]]:
    for d in docs:
        yield d.doc_id, d.full_text
