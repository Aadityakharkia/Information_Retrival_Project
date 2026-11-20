"""Build the "CS Research Library" demo collection.

Sources (public keyphrase-extraction benchmarks, via github.com/LIAAD/KeywordExtractor-Datasets):
  * SemEval-2010 Task 5 (Kim et al., 2010): 243 full-text ACM conference papers
  * Inspec (Hulth, 2003): 2,000 abstracts of computer-science / IT journal papers
Author-assigned keyphrases become document tags; ACM CCS categories become class labels;
reference lists are matched against other titles to build a real citation graph.

    python scripts/prepare_cs_library.py      -> data/cs_papers/papers.jsonl.gz
"""
from __future__ import annotations

import gzip
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://raw.githubusercontent.com/LIAAD/KeywordExtractor-Datasets/master/datasets/"
OUT = Path(__file__).resolve().parents[1] / "data/cs_papers/papers.jsonl.gz"
ACM = {"C": "Distributed Systems", "H": "Information Retrieval", "I": "Multi-Agent Systems", "J": "E-Commerce & Economics"}


def fetch(name: str) -> zipfile.ZipFile:
    local = Path(sys.argv[1]) / f"{name}.zip" if len(sys.argv) > 1 else None
    data = local.read_bytes() if local and local.exists() else urllib.request.urlopen(BASE + name + ".zip").read()
    return zipfile.ZipFile(io.BytesIO(data))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def keys(z: zipfile.ZipFile, path: str):
    try:
        raw = z.read(path).decode("utf-8", "ignore")
    except KeyError:
        return []
    out, seen = [], set()
    for k in raw.splitlines():
        k = norm(k)
        if k and k.lower() not in seen and len(k) < 60:
            seen.add(k.lower()); out.append(k)
    return out[:12]


_FUNC = {"of", "and", "for", "the", "in", "on", "with", "to", "a", "an", "via", "from", "using", "by", "under", "over"}


def _continues_title(l1: str, l2: str) -> bool:
    """SemEval titles may wrap onto a second line; the author line usually follows."""
    w1, w2 = l1.split(), l2.strip("*$† ").split()
    if not w2 or l2.strip() in {"*", "$"}:
        return False
    if w1 and (w1[-1].lower() in _FUNC or l1.rstrip().endswith((":", "-", ","))):
        return True
    if any(w[0].islower() for w in w2 if w[0].isalpha()) and "," not in l2 and "@" not in l2:
        return True
    return len(w2) >= 4 and "," not in l2 and "." not in l2 and not any(ch.isdigit() for ch in l2)


def main():
    records = []
    z = fetch("SemEval2010")
    for name in sorted(n for n in z.namelist() if "/docsutf8/" in n and n.endswith(".txt")):
        raw = z.read(name).decode("utf-8", "ignore")
        lines = [l.strip() for l in raw.splitlines()]
        title = norm(lines[0].rstrip("*"))
        aff = next((i for i, l in enumerate(lines[:12]) if i >= 2 and re.search(
            r"\b(University|Universit|Research|Department|Dept|Labs?|Institute|Inc|Corporation|School|College|Laboratory|Microsoft|IBM|Google|Yahoo)\b", l)), None)
        second = lines[1] if len(lines) > 1 else ""
        sw = second.strip("*$†∗ ").split()
        looks_name = ("," in second or re.search(r"\d", second) or re.search(r"\b[A-Z]\.", second)
                      or (len(sw) == 2 and all(w[:1].isupper() for w in sw) and lines[0].split()[-1].lower() not in _FUNC))
        junk = (not sw) or "@" in second or second.lower().startswith("author") or looks_name
        if not junk and ((aff is not None and aff - 1 >= 2) or (aff is None and _continues_title(lines[0], second))):
            title = norm(f"{title} {second.rstrip('*')}")
        m = re.search(r"\bABSTRACT\b", raw)
        body = raw[m.end():] if m else raw
        header = raw[: m.start()] if m else ""
        stem = Path(name).stem
        abstract = norm(re.split(r"\n\s*(Categories and Subject Descriptors|General Terms|Keywords|1\.?\s+INTRODUCTION)", body)[0])[:1500]
        title = norm(title.replace("∗", "").replace("*", ""))
        records.append({"id": f"acm-{stem}", "title": title, "text": norm(body), "abstract": abstract,
                        "category": ACM.get(stem[0], "Other"), "type": "Full paper (ACM)", "source": "SemEval-2010",
                        "tags": keys(z, name.replace("docsutf8", "keys").replace(".txt", ".key")),
                        "affiliation_text": norm(header)[:400]})
    z = fetch("Inspec")
    for name in sorted(n for n in z.namelist() if "/docsutf8/" in n and n.endswith(".txt")):
        raw = z.read(name).decode("utf-8", "ignore")
        title, _, body = raw.partition("\n")
        records.append({"id": f"inspec-{Path(name).stem}", "title": norm(title), "text": norm(body), "abstract": norm(body),
                        "category": "Journal abstract (Inspec)", "type": "Abstract", "source": "Inspec",
                        "tags": keys(z, name.replace("docsutf8", "keys").replace(".txt", ".key"))})
    # citation links: a paper cites another if the other's title appears in its reference section
    titles = {r["id"]: re.sub(r"[^a-z0-9 ]", "", r["title"].lower()) for r in records if len(r["title"]) > 25}
    n_links = 0
    for r in records:
        if r["type"].startswith("Full"):
            refs = r["text"].lower()
            i = refs.rfind("references")
            refs = re.sub(r"[^a-z0-9 ]", "", refs[i:] if i > 0 else "")
            r["links"] = [oid for oid, t in titles.items() if oid != r["id"] and t in refs]
            n_links += len(r["links"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"{len(records)} papers, {n_links} citation links -> {OUT}")


if __name__ == "__main__":
    main()
