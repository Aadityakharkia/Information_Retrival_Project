"""Download the "Research Papers 2016–2025" collection from OpenAlex (free, no API key).

For each computer-science subfield it takes the most-cited papers published 2016–2025 that
have an abstract: title, abstract, authors, venue, year, keywords (used as tags), subfield
(category), citation count, DOI link, and citation links between papers in the collection.

    python scripts/fetch_openalex.py                 # ~1,200 papers per subfield (~14k total, 2–4 min)
    python scripts/fetch_openalex.py --per-subfield 400 --email you@uni.edu
    OPENALEX_API_KEY=... python scripts/fetch_openalex.py      # optional free key (openalex.org/settings/api)

Without a key OpenAlex allows a small shared daily budget per IP address (about 1,000 requests);
this download needs about 80. Writes data/research_papers/papers.jsonl.gz.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data/research_papers/papers.jsonl.gz"
API = "https://api.openalex.org/works"
SUBFIELDS = {   # OpenAlex subfields of field 17 "Computer Science"
    1702: "Artificial Intelligence", 1707: "Computer Vision & Pattern Recognition", 1710: "Information Systems",
    1705: "Computer Networks & Communications", 1712: "Software", 1709: "Human-Computer Interaction",
    1703: "Computational Theory & Mathematics", 1708: "Hardware & Architecture", 1711: "Signal Processing",
    1704: "Computer Graphics & CAD", 1706: "Computer Science Applications", 1701: "Computer Science (general)",
}
SELECT = ("id,title,publication_year,authorships,primary_location,abstract_inverted_index,cited_by_count,"
          "primary_topic,keywords,referenced_works,doi,type")


def abstract_from_index(inv: dict) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the text."""
    if not inv:
        return ""
    pos = {}
    for word, ps in inv.items():
        for p in ps:
            pos[p] = word
    return re.sub(r"\s+", " ", " ".join(pos[i] for i in sorted(pos))).strip()


def to_record(w: dict, category: str):
    title = re.sub(r"<[^>]+>", "", w.get("title") or "").strip()
    text = abstract_from_index(w.get("abstract_inverted_index"))
    if not title or len(text.split()) < 40:
        return None
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    auth = w.get("authorships") or []
    topic = (w.get("primary_topic") or {}).get("display_name", "")
    return {"id": w["id"].rsplit("/", 1)[-1], "title": title, "text": text[:3000],
            "abstract": text[:1500], "year": str(w.get("publication_year") or ""),
            "authors": ", ".join(a["author"]["display_name"] for a in auth[:6] if a.get("author")) + (" et al." if len(auth) > 6 else ""),
            "venue": src.get("display_name") or "", "category": category, "topic_label": topic,
            "tags": [k["display_name"] for k in (w.get("keywords") or [])][:8],
            "citations": str(w.get("cited_by_count") or 0),
            "url": w.get("doi") or loc.get("landing_page_url") or w["id"],
            "type": "Preprint" if w.get("type") == "preprint" else "Article",
            "source": "OpenAlex",
            "refs": [r.rsplit("/", 1)[-1] for r in (w.get("referenced_works") or [])]}


# Header sets tried in order; some edge networks reject unfamiliar user agents with 401/403.
HEADER_SETS = [
    {"Accept": "application/json"},
    {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                                                 "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"},
    {"Accept": "application/json", "User-Agent": "python-requests/2.32 SearchBridge (mailto:searchbridge@example.com)"},
]
_working_headers: dict = {}


class FetchError(RuntimeError):
    pass


def fetch_json(url: str, tries: int = 4) -> dict:
    global _working_headers
    candidates = [_working_headers] if _working_headers else HEADER_SETS
    last = ""
    for headers in candidates:
        for a in range(tries):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                _working_headers = headers
                return data
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")[:400]
                last = f"HTTP {e.code}: {body}"
                if e.code in (401, 403):      # not transient: try the next header set
                    break
                if e.code == 429:
                    print("   rate limited; waiting 10 s", flush=True)
                    time.sleep(10)
                    continue
                time.sleep(2 * (a + 1))
            except Exception as e:  # network hiccup
                last = str(e)
                print(f"   retry ({e})", flush=True)
                time.sleep(2 * (a + 1))
    raise FetchError(last)


def fetch_subfield(sub: int, name: str, n: int, email: str, seen: set) -> list:
    out, cursor = [], "*"
    while len(out) < n and cursor:
        params = {"filter": f"primary_topic.subfield.id:{sub},publication_year:2016-2025,has_abstract:true,type:article|preprint",
                  "sort": "cited_by_count:desc", "per-page": "200", "cursor": cursor, "select": SELECT, "mailto": email}
        if os.environ.get("OPENALEX_API_KEY"):
            params["api_key"] = os.environ["OPENALEX_API_KEY"]
        data = fetch_json(f"{API}?{urllib.parse.urlencode(params)}")
        results = data.get("results") or []
        for w in results:
            rec = to_record(w, name)
            if rec and rec["id"] not in seen:
                seen.add(rec["id"])
                out.append(rec)
                if len(out) >= n:
                    break
        cursor = (data.get("meta") or {}).get("next_cursor")
        if not results:
            break
        time.sleep(0.15)   # stay well under OpenAlex's rate limit
    return out


def finalise(records: list) -> list:
    ids = {r["id"] for r in records}
    for r in records:
        r["links"] = [x for x in r.pop("refs", []) if x in ids]
    return records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-subfield", type=int, default=1200)
    ap.add_argument("--email", default="searchbridge@example.com", help="sent to OpenAlex's polite pool")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--api-key", default=None, help="optional OpenAlex API key (or set OPENALEX_API_KEY)")
    args = ap.parse_args(argv)
    if args.api_key:
        os.environ["OPENALEX_API_KEY"] = args.api_key
    seen: set = set()
    records: list = []
    t0 = time.time()
    for sub, name in SUBFIELDS.items():
        try:
            got = fetch_subfield(sub, name, args.per_subfield, args.email, seen)
        except FetchError as e:
            print(f"!! {name}: OpenAlex refused the request ({e})", flush=True)
            if not records:
                print("Stopping. If the message mentions an API key or budget, get a free key at "
                      "https://openalex.org/settings/api and run:\n  OPENALEX_API_KEY=YOUR_KEY python scripts/fetch_openalex.py",
                      file=sys.stderr)
                return 1
            continue
        records.extend(got)
        print(f"   {name:40s} {len(got):5d} papers   (total {len(records)}, {time.time() - t0:.0f}s)", flush=True)
    if len(records) < 100:
        print("Too few papers downloaded; is api.openalex.org reachable?", file=sys.stderr)
        return 1
    records = finalise(records)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(out)
    print(f"Saved {len(records)} papers with {sum(len(r['links']) for r in records)} citation links -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
