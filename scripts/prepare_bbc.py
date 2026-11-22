"""Build the "BBC News" collection from the BBC full-text classification dataset (Greene & Cunningham, ICML 2006).

    python scripts/prepare_bbc.py --input /path/to/bbc_data.csv

The CSV has two columns, `data` (headline, two spaces, then the article) and `labels` (business,
entertainment, politics, sport, tech). The 2,225 articles are kept as they are, including the 99 articles
that appear twice in the original release: they are real duplicates for the near-duplicate detector to fold.
The pound sign, written in the CSV as the escaped bytes "xc2xa3", is restored.
Output: data/bbc/articles.jsonl.gz
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/bbc/articles.jsonl.gz"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    counts: Counter = Counter()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.input, newline="", encoding="utf-8") as f, gzip.open(a.out, "wt", encoding="utf-8") as out:
        for i, row in enumerate(csv.DictReader(f), 1):
            raw = row["data"].strip().replace("xc2xa3", "\u00a3")    # the CSV spells "£" as its escaped UTF-8 bytes
            title, _, body = raw.partition("  ")
            if not body:                                  # no double space: fall back to the first sentence
                title, _, body = raw.partition(". ")
            body = re.sub(r"\s{2,}", "\n", body.strip())
            cat = row["labels"].strip().capitalize()
            counts[cat] += 1
            out.write(json.dumps({"id": f"bbc-{i:04d}", "title": title.strip(), "text": body, "category": cat,
                                  "type": "News article", "source": "BBC News (2004-2005)"}, ensure_ascii=False) + "\n")
    stats = {"articles": sum(counts.values()), "classes": dict(counts)}
    (a.out.parent / "stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
