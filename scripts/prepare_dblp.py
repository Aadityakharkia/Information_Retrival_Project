"""Build the "DBLP Citation Network" collection from the DBLP-Citation-network V12 dump (Tang et al., AMiner).

    python scripts/prepare_dblp.py --input /path/to/dblp.v12.json

The dump (4.9 M papers, 45.6 M citations, ~12 GB) is far too large to index here, so this script cuts out a
labelled, densely linked sample:

  1. stream the file once and keep, for every paper with a title and an abstract from 2000 on whose fields of
     study include one of CLASSES, only its id, class and reference list (abstracts are not held in memory);
     the class is the CLASSES field with the highest field-of-study weight;
  2. rank papers in each class by how often the other candidates cite them and keep the top --per-class, so
     the sample is made of papers that cite each other (PageRank and HITS need a connected graph);
  3. stream the file again and write the chosen papers, with their abstracts rebuilt from DBLP's inverted
     index and only the citations that point inside the sample, to data/dblp/papers.jsonl.gz.

Source: https://www.aminer.org/citation (also on Kaggle as "Citation Network Dataset"), CC BY-NC-SA 4.0.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from array import array
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/dblp/papers.jsonl.gz"
CLASSES = ["Information retrieval", "Computer vision", "Natural language processing", "Computer network",
           "Computer security", "Database"]
# fields of study too broad to be useful as keyword tags
GENERIC = {"Computer science", "Artificial intelligence", "Mathematics", "Engineering", "Machine learning",
           "Data mining", "Pattern recognition", "Theoretical computer science", "Algorithm", "Business",
           "Knowledge management", "World Wide Web", "Distributed computing", "Physics", "Biology", "Medicine"}


def records(path: Path):
    """The dump is one JSON array with one paper per line (lines after the first start with a comma)."""
    with open(path, "rb") as f:
        for line in f:
            line = line.strip()
            if line.startswith(b","):
                line = line[1:]
            if not line or line in (b"[", b"]"):
                continue
            yield json.loads(line)


_ESCAPE = re.compile(r"u00([0-9a-f]{2})")


def clean(text: str) -> str:
    """DBLP V12 writes some characters as literal escapes ("Todayu0027s", "Ru0026D"); decode them."""
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)) if m.group(1) != "00" else "", text)


def abstract_text(r: dict) -> str:
    ia = r.get("indexed_abstract") or {}
    inv = ia.get("InvertedIndex") or {}
    words = [""] * int(ia.get("IndexLength") or 0)
    for w, positions in inv.items():
        for p in positions:
            if 0 <= p < len(words):
                words[p] = w
    return clean(" ".join(w for w in words if w))


def label(r: dict) -> str | None:
    fos = {x["name"]: x.get("w", 0.0) for x in r.get("fos") or []}
    hits = [(fos[c], c) for c in CLASSES if c in fos]
    return max(hits)[1] if hits else None


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--per-class", type=int, default=3500)
    ap.add_argument("--min-year", type=int, default=2000)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)

    t0 = time.time()
    cls_of: dict = {}                 # paper id -> class index
    refs_of: dict = {}                # paper id -> array of referenced ids
    seen = 0
    for r in records(a.input):
        seen += 1
        if seen % 500_000 == 0:
            print(f"  pass 1: {seen:,} papers read, {len(cls_of):,} candidates ({time.time() - t0:.0f}s)", flush=True)
        if (r.get("year") or 0) < a.min_year or not r.get("title") or "indexed_abstract" not in r:
            continue
        c = label(r)
        if c is None:
            continue
        cls_of[r["id"]] = CLASSES.index(c)
        refs_of[r["id"]] = array("q", r.get("references") or [])
    print(f"pass 1 done: {seen:,} papers, {len(cls_of):,} candidates ({time.time() - t0:.0f}s)")

    indeg: Counter = Counter()
    for pid, refs in refs_of.items():
        for x in refs:
            if x in cls_of and x != pid:
                indeg[x] += 1
    by_class = defaultdict(list)
    for pid, c in cls_of.items():
        by_class[c].append(pid)
    chosen = set()
    for c, ids in by_class.items():
        ids.sort(key=lambda p: -indeg[p])
        chosen.update(ids[: a.per_class])
    links = {pid: sorted({x for x in refs_of[pid] if x in chosen and x != pid}) for pid in chosen}
    del refs_of
    n_links = sum(map(len, links.values()))
    linked = {p for p, ls in links.items() if ls} | {x for ls in links.values() for x in ls}
    print(f"selected {len(chosen):,} papers with {n_links:,} internal citations; "
          f"{len(linked) / len(chosen):.1%} of papers have a citation link")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    counts: Counter = Counter()
    tmp = a.out.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as out:
        for r in records(a.input):
            pid = r["id"]
            if pid not in chosen:
                continue
            text = abstract_text(r)
            if not text:
                continue
            cat = CLASSES[cls_of[pid]]
            venue = (r.get("venue") or {}).get("raw", "")
            fos = sorted(r.get("fos") or [], key=lambda x: -x.get("w", 0))
            tags = [x["name"] for x in fos if x["name"] not in GENERIC and x["name"] not in CLASSES][:6]
            doi = r.get("doi") or ""
            out.write(json.dumps({
                "id": f"dblp-{pid}", "title": clean(r["title"].strip()), "text": text, "abstract": text,
                "links": [f"dblp-{x}" for x in links[pid]], "tags": tags,
                "category": cat, "author": ", ".join(x.get("name", "") for x in (r.get("authors") or [])[:8]),
                "year": str(r.get("year", "")), "venue": venue, "type": r.get("doc_type") or "Paper",
                "n_citation": str(r.get("n_citation", 0)), "source": f"https://doi.org/{doi}" if doi else "DBLP",
            }, ensure_ascii=False) + "\n")
            written += 1
            counts[cat] += 1
    tmp.replace(a.out)
    stats = {"papers": written, "internal_citations": n_links, "link_coverage": round(len(linked) / len(chosen), 4),
             "classes": dict(counts), "per_class": a.per_class, "min_year": a.min_year, "source_papers": seen,
             "seconds": round(time.time() - t0)}
    (a.out.parent / "stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    sys.exit(main())
