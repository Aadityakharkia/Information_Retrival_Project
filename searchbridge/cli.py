"""Command-line interface.

    searchbridge index  <folder|cranfield> -o index.pkl [--encoder lsa|sbert|auto]
    searchbridge search index.pkl "boundary layer heat transfer" [-m bridge] [-k 10] [--explain]
    searchbridge related index.pkl <doc_id>
    searchbridge stats  index.pkl
    searchbridge crawl  https://example.edu --max-pages 50 -o crawled.jsonl
    searchbridge benchmark [--encoder sbert]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .engine import MODES, EngineConfig, SearchEngine


def _load_docs(src: str):
    from .documents import load_cranfield, load_directory, load_jsonl
    p = Path(src)
    if src == "cranfield" or (p / "cran.all.1400.xml").exists():
        root = p if p.exists() else Path(__file__).resolve().parents[1] / "data/cranfield"
        return load_cranfield(root)[0]
    if p.suffix in {".jsonl", ".json"}:
        return load_jsonl(p)
    return load_directory(p)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="searchbridge", description="SearchBridge AI — intelligent document search")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("index", help="build an index from a folder of PDFs/TXT/MD/HTML, a .jsonl, or 'cranfield'")
    a.add_argument("source"); a.add_argument("-o", "--output", default="index.pkl")
    a.add_argument("--encoder", default="lsa", choices=["lsa", "sbert", "auto"])
    a.add_argument("--ontology", default=None)

    s = sub.add_parser("search"); s.add_argument("index"); s.add_argument("query")
    s.add_argument("-m", "--mode", default="bridge", choices=MODES); s.add_argument("-k", type=int, default=10)
    s.add_argument("--explain", action="store_true"); s.add_argument("--diversify", action="store_true")
    s.add_argument("--json", action="store_true")

    r = sub.add_parser("related"); r.add_argument("index"); r.add_argument("doc_id"); r.add_argument("-k", type=int, default=5)
    st = sub.add_parser("stats"); st.add_argument("index")

    c = sub.add_parser("crawl"); c.add_argument("seeds", nargs="+"); c.add_argument("--max-pages", type=int, default=50)
    c.add_argument("--delay", type=float, default=1.0); c.add_argument("-o", "--output", default="crawled.jsonl")

    b = sub.add_parser("benchmark"); b.add_argument("--encoder", default="lsa", choices=["lsa", "sbert"])

    args = ap.parse_args(argv)

    if args.cmd == "index":
        docs = _load_docs(args.source)
        onto = args.ontology or str(Path(__file__).resolve().parents[1] / "data/ontology.json")
        eng = SearchEngine.from_documents(docs, EngineConfig(encoder=args.encoder,
                                                            ontology_path=onto if Path(onto).exists() else None))
        eng.save(args.output)
        print(json.dumps(eng.stats(), indent=2)); print(f"saved -> {args.output}")
    elif args.cmd == "search":
        eng = SearchEngine.load(args.index)
        resp = eng.search(args.query, mode=args.mode, k=args.k, diversify=args.diversify)
        if args.json:
            from dataclasses import asdict
            print(json.dumps(asdict(resp), indent=2, default=str)); return
        if resp.corrected_query:
            print(f"Showing results for: {resp.corrected_query}")
        print(f"{resp.total_matches} matches in {resp.took_ms} ms  [mode={resp.mode}]")
        if resp.expansion_terms:
            print("expanded with:", ", ".join(t for t, _ in resp.expansion_terms))
        for h in resp.hits:
            flag = f"  ⚠ {', '.join(h.flags)}" if h.flags else ""
            print(f"\n{h.rank:>2}. [{h.doc_id}] {h.title[:90]}  (score {h.score}, credibility {h.credibility}){flag}")
            print(f"    {h.snippet}")
            if args.explain:
                print("    why: " + ", ".join(f"{t}(tf={tf}, idf={idf:.2f}) +{c:.2f}" for t, tf, idf, c in h.explanation if c))
        if resp.related_concepts:
            print("\nRelated concepts:", ", ".join(n for n, _ in resp.related_concepts))
    elif args.cmd == "related":
        eng = SearchEngine.load(args.index)
        for did, title, sc, parts in eng.related_documents(args.doc_id, args.k):
            print(f"[{did}] {title[:80]}  score={sc}  {parts}")
    elif args.cmd == "stats":
        print(json.dumps(SearchEngine.load(args.index).stats(), indent=2))
    elif args.cmd == "crawl":
        from .web.crawler import CrawlConfig, Crawler
        cr = Crawler(CrawlConfig(max_pages=args.max_pages, delay_s=args.delay))
        docs = cr.crawl(args.seeds)
        with open(args.output, "w") as f:
            for d in docs:
                f.write(json.dumps({"id": d.doc_id, "title": d.title, "text": d.text, "links": d.links, **d.meta}) + "\n")
        print(cr.stats, f"-> {args.output}")
    elif args.cmd == "benchmark":
        script = Path(__file__).resolve().parents[1] / "experiments/run_benchmark.py"
        sys.exit(subprocess.call([sys.executable, str(script), "--encoder", args.encoder]))


if __name__ == "__main__":
    main()
