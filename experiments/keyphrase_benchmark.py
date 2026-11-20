"""Second evaluation: keyphrase-based retrieval on the CS Research Library.

There are no human relevance judgements for this collection, so we use the standard
"keyphrase as query" protocol: an author-assigned keyphrase is the query and every
paper annotated with that keyphrase is relevant. Keyphrases are NOT indexed (only
title + text are), so a system must find papers about the concept from their content.
Queries: keyphrases assigned to 5-40 papers (sampled, seed 7). No parameter is tuned
on this collection: every system uses the defaults chosen on Cranfield.

    python experiments/keyphrase_benchmark.py   -> results/keyphrase/results.json, RESULTS.md
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from searchbridge.documents import load_jsonl  # noqa: E402
from searchbridge.evaluation.metrics import evaluate_run, mean_scores, randomization_test  # noqa: E402
from searchbridge.index.inverted_index import InvertedIndex  # noqa: E402
from searchbridge.retrieval.bridge_prf import BridgePRF  # noqa: E402
from searchbridge.retrieval.fusion import interpolate, rrf  # noqa: E402
from searchbridge.retrieval.lexical import BM25Retriever, LMRetriever, top_k  # noqa: E402
from searchbridge.retrieval.semantic import DenseRetriever, LSAEncoder  # noqa: E402
from searchbridge.text.preprocess import Analyzer  # noqa: E402


def main(n_queries: int = 150):
    docs = load_jsonl(ROOT / "data/cs_papers/papers.jsonl.gz")
    tag_docs = defaultdict(set)
    for d in docs:
        for t in d.tags:
            tag_docs[t.lower()].add(d.doc_id)
    cands = sorted(t for t, ds in tag_docs.items() if 5 <= len(ds) <= 40 and len(t) > 3)
    random.Random(7).shuffle(cands)
    queries = {f"q{i}": t for i, t in enumerate(cands[:n_queries])}
    qrels = {q: {d: 1 for d in tag_docs[t]} for q, t in queries.items()}
    print(f"{len(docs)} docs, {len(queries)} keyphrase queries, avg {sum(map(len, qrels.values())) / len(qrels):.1f} relevant")

    an = Analyzer()
    ix = InvertedIndex(an).build((d.doc_id, d.full_text) for d in docs)
    ids = ix.doc_ids
    bm, lm = BM25Retriever(ix), LMRetriever(ix, mu=300)
    dense = DenseRetriever(LSAEncoder(an, 200), [d.full_text for d in docs])
    bridge = BridgePRF(bm, dense)
    qt = {q: an(t) for q, t in queries.items()}
    L = {q: bm.score(qt[q]) for q in queries}
    D = {q: dense.score_text(queries[q]) for q in queries}
    systems = {
        "BM25": lambda q: L[q],
        "QL-LM Dirichlet": lambda q: lm.score(qt[q]),
        "Dense (LSA)": lambda q: D[q],
        "Hybrid RRF": lambda q: rrf([L[q], D[q]]),
        "Hybrid linear (alpha=0.3)": lambda q: interpolate(L[q], D[q], 0.3),
        "Bridge-PRF (ours, Cranfield defaults)": lambda q: bridge.score(qt[q], queries[q]),
    }
    table, per = {}, {}
    for name, fn in systems.items():
        run = {q: [ids[d] for d, _ in top_k(fn(q), 1000)] for q in queries}
        pq = evaluate_run(run, qrels)
        per[name] = pq
        m = mean_scores(pq)
        table[name] = {k: round(m[k], 4) for k in ("MAP", "P@10", "nDCG@10", "MRR", "R@100")}
        print(f"{name:40s} " + "  ".join(f"{k} {v:.4f}" for k, v in table[name].items()))
    qs = list(qrels)
    for name in table:
        a = [per[name]["MAP"][q] for q in qs]
        table[name]["p_vs_bm25_rand"] = 1.0 if name == "BM25" else randomization_test(a, [per["BM25"]["MAP"][q] for q in qs])
    out = ROOT / "results/keyphrase"
    out.mkdir(parents=True, exist_ok=True)
    res = {"description": f"{len(queries)} author keyphrases used as queries over the {len(docs):,}-paper CS Research Library; "
                          "papers tagged with the keyphrase are relevant (tags are not indexed). Parameters are the Cranfield defaults, "
                          "so this tests whether the methods transfer to a new collection without tuning.",
           "queries": queries, "table": table}
    (out / "results.json").write_text(json.dumps(res, indent=2))
    md = ["# Keyphrase benchmark — CS Research Library", "", res["description"], "",
          "| System | MAP | P@10 | nDCG@10 | MRR | R@100 | p vs BM25 |", "|---|---:|---:|---:|---:|---:|---:|"]
    md += [f"| {n} | " + " | ".join(f"{r[k]:.4f}" for k in ("MAP", "P@10", "nDCG@10", "MRR", "R@100")) + f" | {r['p_vs_bm25_rand']:.4f} |"
           for n, r in table.items()]
    (out / "RESULTS.md").write_text("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
