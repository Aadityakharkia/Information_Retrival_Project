"""Does the search engine get better for a user who has been using it? (Cranfield, 225 judged queries)

Part 1 - retrieval models on the real judgements: Boolean, TF-IDF, BM25, Semantic, Hybrid, Bridge-PRF
and Smart (the app default), with P@10, R@10, F1@10, MAP, nDCG@10.

Part 2 - search memory. Real users are not available, so users are SIMULATED (clearly a simulation):
  * a simulated user searches query A and examines the top 10 with position bias; they open a relevant
    document with probability 0.85 and read it (dwell 45-120 s), sometimes come back to it later (30 %),
    and also open non-relevant documents by mistake (15 %) but leave within 3-8 s;
  * later they search query B. Relevance judgements decide what "useful" means; the engine only sees
    the clicks and dwell times, never the judgements.
Scenarios
  related   B shares judged-relevant documents with A (Cranfield queries about the same problem)
  refind    B = A, searched again later
  unrelated A and B share no relevant documents and are far apart in meaning: memory must NOT hurt
  residual  related, but documents already opened in session A are removed from the evaluation, so only
            generalisation (interest vector, linked/similar documents) can help
  decayed   related, with session A 120 days in the past (21-day half-life)
The personal weight beta is chosen by 2-fold cross-validation over query pairs.
Output: results/personalization/{results.json, RESULTS.md}
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from searchbridge.documents import load_cranfield  # noqa: E402
from searchbridge.engine import EngineConfig, SearchEngine  # noqa: E402
from searchbridge.evaluation import metrics as M  # noqa: E402
from searchbridge.personal import InteractionStore, PersonalContext, build_profile  # noqa: E402
from searchbridge.retrieval.bridge_prf import BridgePRFConfig  # noqa: E402
from searchbridge.text.preprocess import STOPWORDS, tokenize  # noqa: E402

DEPTH = 100
BETAS = [0.05, 0.1, 0.2, 0.3, 0.5]


def log(*a):
    print(*a, flush=True)


def metrics(run, qrels):
    p, r = M.precision_at(run, qrels, 10), M.recall_at(run, qrels, 10)
    return {"P@10": p, "R@10": r, "F1@10": 2 * p * r / (p + r) if p + r else 0.0,
            "MAP": M.average_precision(run, qrels), "nDCG@10": M.ndcg_at(run, qrels, 10)}


def mean(rows):
    return {k: round(float(np.mean([r[k] for r in rows])), 4) for k in rows[0]} if rows else {}


def main():
    t0 = time.time()
    docs, Q, QR = load_cranfield(ROOT / "data/cranfield")
    qids = [q for q in Q if any(g > 0 for g in QR.get(q, {}).values())]
    cfg = EngineConfig(encoder="lsa", lsa_dim=200, hybrid_alpha=0.5, bridge=BridgePRFConfig(fb_docs=3, alpha=0.5), build_kg=False)
    e = SearchEngine.from_documents(docs, cfg)
    log(f"engine built in {time.time() - t0:.0f}s")
    out: dict = {"collection": {"docs": len(docs), "queries": len(qids)}, "depth": DEPTH,
                 "note": "Part 2 uses simulated users; relevance judgements are real (Cranfield)."}

    def run(q, mode, personal=None):
        return [h.doc_id for h in e.search(Q[q], mode=mode, k=DEPTH, spell=False, explain=False, personal=personal, dedupe=False).hits]

    # ---------------------------------------------------------------- part 1: models
    modes = {"Boolean (AND)": "boolean", "TF-IDF": "tfidf", "BM25": "bm25", "Semantic (LSA)": "dense",
             "Hybrid (BM25 + semantic)": "hybrid", "Bridge-PRF": "bridge", "Smart (app default)": "smart"}
    table, per_query = {}, {}
    for name, m in modes.items():
        rows = []
        for q in qids:
            if m == "boolean":
                terms = [t for t in tokenize(Q[q]) if t not in STOPWORDS and t.isalpha()]
                text = " AND ".join(dict.fromkeys(terms)) if terms else ""
                hits = e.search(text, mode="boolean", k=DEPTH, spell=False, explain=False).hits if text else []
                r = [h.doc_id for h in hits]
            else:
                r = run(q, m)
            rows.append(metrics(r, QR[q]))
        per_query[name] = [x["MAP"] for x in rows]
        table[name] = mean(rows)
        log(name, table[name])
    out["models"] = table
    out["p_smart_vs_bm25"] = round(M.randomization_test(per_query["Smart (app default)"], per_query["BM25"]), 4)

    # ---------------------------------------------------------------- part 2: search memory
    rel = {q: {d for d, g in QR[q].items() if g > 0} for q in qids}
    qv = {q: e.dense.query_vector(Q[q]) for q in qids}
    rng = random.Random(7)
    related, unrelated = [], []
    for b in qids:
        cands = sorted((a for a in qids if a != b and rel[a] & rel[b]), key=lambda a: (-len(rel[a] & rel[b]), int(a)))
        if cands:
            related.append((cands[0], b))
        far = [a for a in qids if a != b and not rel[a] & rel[b] and float(qv[a] @ qv[b]) < 0.2]
        if far:
            unrelated.append((rng.choice(far), b))
    log(f"{len(related)} related pairs, {len(unrelated)} unrelated pairs")

    def simulate(store, user, a, ts, seed):
        r = random.Random(seed)
        store.log(user, "cran", "search", query=Q[a], ts=ts)
        top = run(a, "smart")[:10]
        opened = []
        for rank, d in enumerate(top, 1):
            store.log(user, "cran", "impression", query=Q[a], doc=d, rank=rank, ts=ts)
        for rank, d in enumerate(top, 1):
            if r.random() > 1 / (1 + 0.25 * (rank - 1)):       # position bias: lower results are examined less
                continue
            if d in rel[a] and r.random() < 0.85:
                store.log(user, "cran", "open", query=Q[a], doc=d, rank=rank, ts=ts + rank)
                store.log(user, "cran", "dwell", query=Q[a], doc=d, value=r.uniform(45, 120), ts=ts + rank + 1)
                opened.append(d)
                if r.random() < 0.3:
                    store.log(user, "cran", "open", query="", doc=d, source="direct", ts=ts + 3600)
                    store.log(user, "cran", "dwell", doc=d, value=r.uniform(30, 90), ts=ts + 3601)
            elif d not in rel[a] and r.random() < 0.15:
                store.log(user, "cran", "open", query=Q[a], doc=d, rank=rank, ts=ts + rank)
                store.log(user, "cran", "dwell", query=Q[a], doc=d, value=r.uniform(3, 8), ts=ts + rank + 1)
                opened.append(d)
        return opened

    def scenario(pairs, betas, age_days=0.0, refind=False, residual=False, tag=""):
        with tempfile.TemporaryDirectory() as tmp:
            store = InteractionStore(Path(tmp) / "x.db")
            now = time.time()
            res = {b_: [] for b_ in betas}
            base_rows = []
            for i, (a, b) in enumerate(pairs):
                if refind:
                    a = b
                user = f"sim{tag}{i}"
                opened = simulate(store, user, a, now - age_days * 86400 - 600, seed=i)
                prof = build_profile(user, "cran", store.events(user, "cran"), "v", now=now)
                qr = {d: g for d, g in QR[b].items() if not (residual and d in opened)}
                if not any(g > 0 for g in qr.values()):
                    continue
                base = run(b, "smart")
                if residual:
                    base = [d for d in base if d not in opened]
                base_rows.append(metrics(base, qr))
                for beta in betas:
                    ctx = None if prof.empty else PersonalContext(prof, e.index.doc_index, e.dense.emb, e.analyzer,
                                                                   e.out_links, e.in_links, beta=beta)
                    pr = run(b, "smart", ctx)
                    if residual:
                        pr = [d for d in pr if d not in opened]
                    res[beta].append(metrics(pr, qr))
            return base_rows, res

    # choose beta by 2-fold CV over related pairs
    folds = [related[0::2], related[1::2]]
    chosen, cv_rows, cv_base = [], [], []
    for f in (0, 1):
        _, tr = scenario(folds[1 - f], BETAS, tag=f"cv{f}")
        best = max(BETAS, key=lambda b_: np.mean([r["MAP"] for r in tr[b_]]))
        chosen.append(best)
        base, te = scenario(folds[f], [best], tag=f"te{f}")
        cv_rows += te[best]
        cv_base += base
    beta = float(np.median(chosen))
    out["beta_cv_chosen"], out["beta"] = chosen, beta
    log("beta chosen per fold", chosen)

    scen = {}
    scen["related (2-fold CV)"] = {"pairs": len(cv_base), "without_memory": mean(cv_base), "with_memory": mean(cv_rows),
                                   "p_MAP": round(M.randomization_test([r["MAP"] for r in cv_rows], [r["MAP"] for r in cv_base]), 4)}
    for name, kw in {"refind (same query again)": dict(pairs=related, refind=True),
                     "residual (opened docs removed)": dict(pairs=related, residual=True),
                     "unrelated (harm check)": dict(pairs=unrelated),
                     "related, 120 days later": dict(pairs=related, age_days=120)}.items():
        base, res = scenario(kw.pop("pairs"), [beta], tag=name[:3], **kw)
        scen[name] = {"pairs": len(base), "without_memory": mean(base), "with_memory": mean(res[beta]),
                      "p_MAP": round(M.randomization_test([r["MAP"] for r in res[beta]], [r["MAP"] for r in base]), 4)}
        log(name, scen[name])
    out["memory"] = scen
    _, sweep = scenario(related, BETAS, tag="sweep")
    out["beta_sweep_related_MAP"] = {str(b_): round(float(np.mean([r["MAP"] for r in sweep[b_]])), 4) for b_ in BETAS}
    out["seconds"] = round(time.time() - t0)

    dst = ROOT / "results/personalization"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "results.json").write_text(json.dumps(out, indent=1))
    (dst / "RESULTS.md").write_text(markdown(out))
    log(markdown(out))


def markdown(o):
    cols = ["P@10", "R@10", "F1@10", "MAP", "nDCG@10"]
    s = [f"# Retrieval models and search memory on Cranfield ({o['collection']['queries']} judged queries)\n",
         f"Rankings cut at depth {o['depth']}. MAP = mean average precision over that depth.\n",
         "| Method | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
    for n, v in o["models"].items():
        s.append(f"| {n} | " + " | ".join(f"{v[c]:.4f}" for c in cols) + " |")
    s.append(f"\nSmart vs BM25, paired randomisation test on per-query AP: p = {o['p_smart_vs_bm25']}.\n")
    s.append("## Search memory (simulated users, real judgements)\n")
    s.append(f"Personal weight beta = {o['beta']} (chosen by 2-fold CV: {o['beta_cv_chosen']}).\n")
    s.append("| Scenario | pairs | MAP without | MAP with | nDCG@10 without | nDCG@10 with | P@10 without | P@10 with | p (MAP) |")
    s.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for n, v in o["memory"].items():
        a, b = v["without_memory"], v["with_memory"]
        s.append(f"| {n} | {v['pairs']} | {a['MAP']:.4f} | {b['MAP']:.4f} | {a['nDCG@10']:.4f} | {b['nDCG@10']:.4f} | "
                 f"{a['P@10']:.4f} | {b['P@10']:.4f} | {v['p_MAP']} |")
    s.append("\nMAP on related pairs by beta: " + ", ".join(f"{k}: {v}" for k, v in o["beta_sweep_related_MAP"].items()))
    s.append("\n" + o["note"])
    return "\n".join(s) + "\n"


if __name__ == "__main__":
    main()
