"""Crawl a website politely and save it as a searchable collection with its real hyperlinks.

    python scripts/crawl_web.py --seed https://en.wikipedia.org/wiki/Information_retrieval \
        --prefix /wiki/ --exclude : --max-pages 300

The crawler obeys robots.txt (including Crawl-delay), waits at least --delay seconds between requests
to the same host, skips exact and near-duplicate pages (MinHash + LSH) and keeps only out-links that
point to other crawled pages. Output: data/web/pages.jsonl.gz (the "Web pages" collection).
Check the site's terms of use before crawling; Wikipedia text is CC BY-SA, attribute it if you share it.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from searchbridge.web.crawler import CrawlConfig, Crawler  # noqa: E402

OUT = ROOT / "data/web/pages.jsonl.gz"


def crawl(seeds, max_pages=300, depth=2, delay=1.0, prefix=None, exclude=(), out=OUT, fetch=None, robots_fetch=None, log=print,
          progress=None):
    host_domains = {s.split("/")[2] for s in seeds}
    cfg = CrawlConfig(max_pages=max_pages, max_depth=depth, delay_s=delay, allowed_domains=host_domains,
                      path_prefix=prefix, exclude=tuple(exclude))
    kw = {"config": cfg}
    if fetch:
        kw["fetch"] = fetch
    if robots_fetch:
        kw["robots_fetch"] = robots_fetch
    c = Crawler(**kw)
    if progress:      # live status for the UI: called after every page that is kept
        c.on_page = lambda url, html, links: progress(dict(c.stats, last_url=url))
    t0 = time.time()
    docs = c.crawl(seeds)
    ids = {d.doc_id for d in docs}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not docs:      # keep the previous collection rather than replacing it with nothing
        stats = dict(c.stats, pages=0, links=0, error_examples=c.error_examples, blocked_examples=c.blocked_urls[:5],
                     seconds=round(time.time() - t0, 1), seeds=list(seeds))
        (out.parent / "crawl_stats.json").write_text(json.dumps(stats, indent=1))
        log(f"Crawl fetched no pages: {stats}")
        return stats
    with gzip.open(out, "wt", encoding="utf-8") as f:
        for d in docs:
            title = d.title.replace(" - Wikipedia", "").strip()
            links = sorted({u for u in d.links if u in ids and u != d.doc_id})
            f.write(json.dumps({"id": d.doc_id, "title": title, "text": d.text, "links": links,
                                "source": d.doc_id, "type": "Web page", "site": d.doc_id.split("/")[2]}) + "\n")
    stats = dict(c.stats, pages=len(docs), error_examples=c.error_examples, blocked_examples=c.blocked_urls[:5], links=sum(len({u for u in d.links if u in ids}) for d in docs),
                 seconds=round(time.time() - t0, 1), seeds=list(seeds))
    (out.parent / "crawl_stats.json").write_text(json.dumps(stats, indent=1))
    log(f"Saved {len(docs)} pages with {stats['links']} internal links to {out} ({stats})")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", action="append", required=True)
    ap.add_argument("--max-pages", type=int, default=300)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--exclude", action="append", default=[])
    a = ap.parse_args()
    crawl(a.seed, a.max_pages, a.depth, max(a.delay, 0.5), a.prefix, a.exclude)
