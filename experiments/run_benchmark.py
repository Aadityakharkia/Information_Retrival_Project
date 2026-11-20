"""Full experimental evaluation of SearchBridge AI on the Cranfield collection.

    python experiments/run_benchmark.py                 # LSA dense encoder (offline)
    python experiments/run_benchmark.py --encoder sbert # Sentence-BERT (needs sentence-transformers)

Writes results/RESULTS.md, results/results.json, results/figures/*.png and
models/adaptive_cranfield.json. All tuned components use 5-fold cross-validation over
queries (tuning never sees the test fold's judgements).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from searchbridge.documents import load_cranfield, iter_text  # noqa: E402
from searchbridge.evaluation.metrics import (METRICS, average_precision, evaluate_run, interpolated_pr_curve,  # noqa: E402
                                             mean_scores, ndcg_at, paired_t_test, precision_recall_f1,
                                             randomization_test)
from searchbridge.index.compression import compression_report  # noqa: E402
from searchbridge.index.inverted_index import InvertedIndex  # noqa: E402
from searchbridge.index.laws import heaps_fit, zipf_fit  # noqa: E402
from searchbridge.mining.classify import KNNClassifier, MultinomialNB, RocchioClassifier, accuracy_report  # noqa: E402
from searchbridge.mining.cluster import KMeans, hac, nmi, purity  # noqa: E402
from searchbridge.query.feedback import rm3  # noqa: E402
from searchbridge.responsible.fairness import exposure_by_group, intra_list_diversity, mmr  # noqa: E402
from searchbridge.retrieval.adaptive import ALPHA_GRID, FEATURES, AdaptiveHybrid  # noqa: E402
from searchbridge.retrieval.boolean import BooleanRetriever  # noqa: E402
from searchbridge.retrieval.bridge_prf import BridgePRF, BridgePRFConfig  # noqa: E402
from searchbridge.retrieval.fusion import interpolate, rrf  # noqa: E402
from searchbridge.retrieval.lexical import BM25Retriever, LMRetriever, SDMRetriever, TFIDFRetriever, top_k  # noqa: E402
from searchbridge.retrieval.qpp import QPP  # noqa: E402
from searchbridge.retrieval.semantic import DenseRetriever, make_encoder  # noqa: E402
from searchbridge.text.preprocess import Analyzer, PreprocessConfig  # noqa: E402
from searchbridge.web.linkanalysis import pagerank, similarity_graph  # noqa: E402

DEPTH = 1000
FOLDS, SEED = 5, 42
SHOW = ["MAP", "P@10", "nDCG@10", "MRR", "R@100", "BPref"]


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data/cranfield"))
    ap.add_argument("--encoder", default="lsa", choices=["lsa", "sbert"])
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()
    out = Path(args.out); fig_dir = out / "figures"; fig_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "models").mkdir(exist_ok=True)

    docs, Q, QR = load_cranfield(args.data)
    qids = [q for q in Q if any(g > 0 for g in QR.get(q, {}).values())]
    QR = {q: QR[q] for q in qids}
    log(f"Cranfield: {len(docs)} docs, {len(qids)} judged queries")
    an = Analyzer()
    ix = InvertedIndex(an).build(iter_text(docs))
    ids = ix.doc_ids
    texts = [d.full_text for d in docs]
    R: dict = {"collection": {"docs": len(docs), "queries": len(qids)}}

    def to_run(score_fn):
        return {q: [ids[d] for d, _ in top_k(score_fn(q), DEPTH)] for q in qids}

    def evaluate(score_fn):
        run = to_run(score_fn)
        pq = evaluate_run(run, QR)
        return mean_scores(pq), pq, run

    systems: dict = {}

    # ------------------------------------------------------------------ E1 baselines
    log("E1: baselines")
    bm, tf, lmd, lmj = BM25Retriever(ix), TFIDFRetriever(ix), LMRetriever(ix, "dirichlet", mu=300), LMRetriever(ix, "jm", lam=0.7)
    qt = {q: an(Q[q]) for q in qids}
    for name, r in [("TF-IDF cosine (lnc.ltc)", tf), ("BM25 (k1=1.2, b=0.75)", bm),
                    ("QL-LM Dirichlet (mu=300)", lmd), ("QL-LM Jelinek-Mercer (lambda=0.7)", lmj),
                    ("SDM / Markov random field (0.85, 0.10, 0.05)", SDMRetriever(ix, mu=300))]:
        systems[name] = evaluate(lambda q, r=r: r.score(qt[q]))
    enc = make_encoder(args.encoder, an, dim=200)
    t0 = time.time()
    dense = DenseRetriever(enc, texts)
    log(f"   dense encoder {dense.name} fitted in {time.time()-t0:.1f}s")
    L0 = {q: bm.score(qt[q]) for q in qids}
    D0 = {q: dense.score_text(Q[q]) for q in qids}
    systems[dense.name] = evaluate(lambda q: D0[q])
    systems["BM25 + RM3 (self-PRF)"] = evaluate(lambda q: bm.score_weighted(rm3(ix, qt[q], top_k(L0[q], 10))))
    E = dense.emb

    def vprf(q, fb, beta=0.8):
        v = dense.query_vector(Q[q]) + beta * E[[d for d, _ in fb]].mean(0)
        v /= np.linalg.norm(v)
        return {i: float(s) for i, s in enumerate(E @ v)}

    systems[f"{dense.name} + vector-PRF (self)"] = evaluate(lambda q: vprf(q, top_k(D0[q], 5)))
    systems["Hybrid RRF (k=60)"] = evaluate(lambda q: rrf([L0[q], D0[q]]))

    # per-query AP for every alpha (used by CV-tuned hybrid and QAHR)
    AP = np.array([[average_precision([ids[d] for d, _ in top_k(interpolate(L0[q], D0[q], a), DEPTH)], QR[q])
                    for a in ALPHA_GRID] for q in qids])
    rng = np.random.default_rng(SEED)
    folds = np.array_split(rng.permutation(len(qids)), FOLDS)

    best_alpha_cv = np.zeros(len(qids))
    for f in folds:
        tr = np.setdiff1d(np.arange(len(qids)), f)
        best_alpha_cv[f] = ALPHA_GRID[AP[tr].mean(0).argmax()]
    systems["Hybrid linear (alpha CV-tuned)"] = evaluate(
        lambda q: interpolate(L0[q], D0[q], best_alpha_cv[qids.index(q)]))
    R["hybrid_alpha_curve"] = dict(zip(map(float, ALPHA_GRID), AP.mean(0).round(4).tolist()))
    R["oracle_per_query_alpha_MAP"] = float(AP.max(1).mean())

    # ------------------------------------------------------------------ E2 QAHR (novelty #2)
    log("E2: QPP-adaptive hybrid (QAHR)")
    ah = AdaptiveHybrid(QPP(ix))
    X = np.array([ah.features(qt[q], L0[q], D0[q]) for q in qids])
    y = np.array([AdaptiveHybrid.oracle_alpha(a) for a in AP])
    pred = np.zeros(len(qids))
    for f in folds:
        tr = np.setdiff1d(np.arange(len(qids)), f)
        m = AdaptiveHybrid.fit(X[tr], y[tr], l2=0.5)
        pred[f] = [m.predict(x) for x in X[f]]
    systems["QAHR: QPP-adaptive hybrid (ours, 5-fold CV)"] = evaluate(
        lambda q: interpolate(L0[q], D0[q], pred[qids.index(q)]))
    AdaptiveHybrid.fit(X, y, l2=0.5).save(ROOT / "models/adaptive_cranfield.json")
    R["qahr"] = {"feature_alpha_correlation": {f: round(float(np.corrcoef(X[:, i], y)[0, 1]), 3) for i, f in enumerate(FEATURES)},
                 "pred_alpha_mean": float(pred.mean()), "pred_alpha_std": float(pred.std()),
                 "alpha_pred_vs_oracle_r": float(np.corrcoef(pred, y)[0, 1])}

    # ------------------------------------------------------------------ E3 Bridge-PRF (novelty #1)
    log("E3: Bridge-PRF")
    H0cache: dict = {}

    def bridge_scores(q, k, a, use_lex=True, use_dense=True, cross=True):
        key = (q, a)
        if key not in H0cache:
            H0cache[key] = interpolate(L0[q], D0[q], a)
        fb = top_k(H0cache[key], k) if cross else None
        fb_l = fb if cross else top_k(L0[q], k)
        fb_d = fb if cross else top_k(D0[q], k)
        L1 = bm.score_weighted(rm3(ix, qt[q], [(d, L0[q].get(d, 0.0)) for d, _ in fb_l])) if use_lex else L0[q]
        D1 = vprf(q, fb_d) if use_dense else D0[q]
        return interpolate(L1, D1, a)

    default = BridgePRFConfig()
    systems["Bridge-PRF (ours, default k=5, alpha=0.3)"] = evaluate(lambda q: bridge_scores(q, default.fb_docs, default.alpha))
    # sanity check: the library class reproduces the experimental pipeline
    lib = BridgePRF(bm, dense, default)
    q0 = qids[0]
    assert top_k(lib.score(qt[q0], Q[q0]), 5) == top_k(bridge_scores(q0, 5, 0.3), 5)

    grid = [(k, a) for k in (3, 5, 10) for a in (0.2, 0.3, 0.4, 0.5)]
    gAP = {}
    for k, a in grid:
        gAP[(k, a)] = np.array([average_precision([ids[d] for d, _ in top_k(bridge_scores(q, k, a), DEPTH)], QR[q]) for q in qids])
    cv_runs = {}
    chosen = []
    for f in folds:
        tr = np.setdiff1d(np.arange(len(qids)), f)
        k, a = max(grid, key=lambda g: gAP[g][tr].mean())
        chosen.append((k, a))
        for i in f:
            cv_runs[qids[i]] = (k, a)
    systems["Bridge-PRF (ours, 5-fold CV-tuned)"] = evaluate(lambda q: bridge_scores(q, *cv_runs[q]))
    R["bridge_grid_MAP"] = {f"k={k},alpha={a}": round(float(v.mean()), 4) for (k, a), v in gAP.items()}
    R["bridge_cv_chosen"] = [f"k={k},alpha={a}" for k, a in chosen]

    ablation = {
        "Bridge-PRF (full)": lambda q: bridge_scores(q, 5, 0.3),
        "  - without lexical RM3 branch": lambda q: bridge_scores(q, 5, 0.3, use_lex=False),
        "  - without dense vector-PRF branch": lambda q: bridge_scores(q, 5, 0.3, use_dense=False),
        "  - self-feedback instead of shared hybrid feedback": lambda q: bridge_scores(q, 5, 0.3, cross=False),
        "  - no feedback at all (= hybrid alpha 0.3)": lambda q: interpolate(L0[q], D0[q], 0.3),
    }
    R["bridge_ablation"] = {n: {m: round(v, 4) for m, v in evaluate(fn)[0].items() if m in SHOW} for n, fn in ablation.items()}

    # ------------------------------------------------------------------ main table + significance
    base, hyb, ours = "BM25 (k1=1.2, b=0.75)", "Hybrid linear (alpha CV-tuned)", "Bridge-PRF (ours, 5-fold CV-tuned)"
    table = {}
    for name, (means, pq, _) in systems.items():
        row = {m: round(means[m], 4) for m in METRICS}
        vprf_name = [n for n in systems if n.endswith("vector-PRF (self)")][0]
        for ref, tag in ((base, "vs_bm25"), (hyb, "vs_hybrid"), (vprf_name, "vs_vprf")):
            a = [pq["MAP"][q] for q in qids]; b = [systems[ref][1]["MAP"][q] for q in qids]
            row[f"p_{tag}_ttest"] = paired_t_test(a, b) if name != ref else 1.0
            row[f"p_{tag}_rand"] = randomization_test(a, b) if name != ref else 1.0
        table[name] = row
    R["main_table"] = table
    ours_pq = systems[ours][1]["MAP"]; base_pq = systems[base][1]["MAP"]
    diff = np.array([ours_pq[q] - base_pq[q] for q in qids])
    R["win_tie_loss_vs_bm25"] = {"wins": int((diff > 1e-9).sum()), "ties": int((abs(diff) <= 1e-9).sum()), "losses": int((diff < -1e-9).sum())}

    # ------------------------------------------------------------------ E4 Boolean retrieval
    log("E4: Boolean set retrieval")
    br = BooleanRetriever(ix)
    for op in ("AND", "OR"):
        prf = []
        for q in qids:
            terms = list(dict.fromkeys(qt[q]))
            res = br.search_query(f" {op} ".join(terms)) if terms else set()
            prf.append(precision_recall_f1([ids[d] for d in res], QR[q]) + (len(res),))
        P, Rc, F, n = np.array(prf).mean(0)
        R[f"boolean_{op}"] = {"precision": round(P, 4), "recall": round(Rc, 4), "F1": round(F, 4), "avg_result_size": round(n, 1)}

    # ------------------------------------------------------------------ E5 preprocessing ablation & BM25 sweep
    log("E5: preprocessing ablation, BM25 sweep")
    pre = {}
    for stem in (True, False):
        for stop in (True, False):
            a2 = Analyzer(PreprocessConfig(stem=stem, remove_stopwords=stop))
            ix2 = InvertedIndex(a2).build(iter_text(docs))
            b2 = BM25Retriever(ix2)
            m = evaluate(lambda q, b2=b2, a2=a2: b2.score(a2(Q[q])))[0]
            pre[f"stemming={'on' if stem else 'off'}, stopwords={'removed' if stop else 'kept'}"] = {
                "MAP": round(m["MAP"], 4), "P@10": round(m["P@10"], 4), "vocab": len(ix2.postings)}
    R["preprocessing_ablation"] = pre
    k1s, bs = [0.6, 0.9, 1.2, 1.5, 2.0, 2.5], [0.0, 0.25, 0.5, 0.75, 1.0]
    sweep = np.zeros((len(k1s), len(bs)))
    for i, k1 in enumerate(k1s):
        for j, b in enumerate(bs):
            r = BM25Retriever(ix, k1, b)
            sweep[i, j] = np.mean([average_precision([ids[d] for d, _ in top_k(r.score(qt[q]), DEPTH)], QR[q]) for q in qids])
    R["bm25_sweep"] = {"k1": k1s, "b": bs, "MAP": sweep.round(4).tolist()}

    # ------------------------------------------------------------------ E6 index compression & laws
    log("E6: compression, Zipf, Heaps")
    rep = compression_report(ix.postings)
    R["compression"] = [{"structure": n, "bytes": b, "ratio": round(r, 3)} for n, b, r in rep.as_rows()]
    zf, ranks, freqs = zipf_fit(ix.collection_tf())
    hf, T, M = heaps_fit(t for x in texts for t in an(x))
    R["zipf"] = {"exponent": round(zf.exponent, 3), "r2": round(zf.r2, 3)}
    R["heaps"] = {"k": round(hf.k, 2), "b": round(hf.b, 3), "r2": round(hf.r2, 3)}

    # ------------------------------------------------------------------ E7 link analysis prior
    log("E7: PageRank prior on similarity graph")
    pr = pagerank(similarity_graph(E, 10)); pr = pr / pr.max()
    pr_res = {}
    for w in (0.0, 0.05, 0.1, 0.2):
        def fn(q, w=w):
            s = bridge_scores(q, 5, 0.3)
            return {d: v + w * pr[d] for d, v in s.items()}
        pr_res[str(w)] = round(evaluate(fn)[0]["MAP"], 4)
    R["pagerank_prior_MAP"] = pr_res

    # ------------------------------------------------------------------ E8 diversity & exposure
    log("E8: MMR diversity + venue exposure audit")
    venue = [d.meta["venue"] for d in docs]
    div = {}
    for lam in (1.0, 0.85, 0.7, 0.5):
        nd, ild = [], []
        for q in qids:
            cand = top_k(bridge_scores(q, 5, 0.3), 50)
            rk = mmr(cand, E, lam, 10) if lam < 1 else cand[:10]
            nd.append(ndcg_at([ids[d] for d, _ in rk], QR[q], 10))
            ild.append(intra_list_diversity([d for d, _ in rk], E))
        div[str(lam)] = {"nDCG@10": round(float(np.mean(nd)), 4), "ILD@10": round(float(np.mean(ild)), 4)}
    R["mmr_tradeoff"] = div
    corpus_share = {v: venue.count(v) / len(venue) for v in set(venue)}
    exp_tot = {v: 0.0 for v in corpus_share}
    for q in qids:
        for g, e in exposure_by_group([d for d, _ in top_k(bridge_scores(q, 5, 0.3), 10)], lambda d: venue[d]).items():
            exp_tot[g] += e / len(qids)
    R["venue_exposure_top10"] = {g: {"corpus_share": round(corpus_share[g], 3), "exposure_share": round(exp_tot[g], 3)} for g in corpus_share}

    # ------------------------------------------------------------------ E9 classification & clustering
    log("E9: venue classification + clustering")
    lab_idx = [i for i, v in enumerate(venue) if not v.startswith("Other")]
    Xt = [texts[i] for i in lab_idx]; yt = [venue[i] for i in lab_idx]
    perm = np.random.default_rng(SEED).permutation(len(Xt)); cfolds = np.array_split(perm, 5)
    cls = {}
    for name, mk in [("Multinomial Naive Bayes", lambda: MultinomialNB(an)), ("Rocchio (nearest centroid)", lambda: RocchioClassifier(an)),
                     ("kNN (k=5, cosine)", lambda: KNNClassifier(an, 5))]:
        accs, f1s = [], []
        for f in cfolds:
            tr = np.setdiff1d(perm, f)
            c = mk().fit([Xt[i] for i in tr], [yt[i] for i in tr])
            acc, per = accuracy_report(c, [Xt[i] for i in f], [yt[i] for i in f])
            accs.append(acc); f1s.append(np.mean([v[2] for v in per.values()]))
        cls[name] = {"accuracy": round(float(np.mean(accs)), 4), "macro_F1": round(float(np.mean(f1s)), 4)}
    maj = max(set(yt), key=yt.count)
    cls["Majority-class baseline"] = {"accuracy": round(yt.count(maj) / len(yt), 4), "macro_F1": None}
    R["venue_classification_5fold"] = cls
    El = E[lab_idx]
    clu = {}
    for name, labels in [("k-means (spherical, k=4)", KMeans(4, seed=0).fit(El).labels_),
                         ("HAC average-link (k=4)", hac(El, 4, "average")[0]),
                         ("HAC complete-link (k=4)", hac(El, 4, "complete")[0])]:
        clu[name] = {"purity": round(purity(list(labels), yt), 4), "NMI": round(nmi(list(labels), yt), 4)}
    R["clustering_vs_venue"] = clu
    # topical clustering: relevant sets of queries with disjoint judgements act as gold topics
    rel_sets = sorted(((q, {ix.doc_index[d] for d, g in QR[q].items() if g > 0}) for q in qids), key=lambda x: -len(x[1]))
    chosen_q, used = [], set()
    for q, rs in rel_sets:
        if len(rs) >= 8 and not (rs & used):
            chosen_q.append((q, rs)); used |= rs
        if len(chosen_q) == 8:
            break
    tdocs = [d for _, rs in chosen_q for d in sorted(rs)]
    tgold = [q for q, rs in chosen_q for _ in rs]
    from sklearn.feature_extraction.text import TfidfVectorizer
    Xtf = TfidfVectorizer(analyzer=an, sublinear_tf=True).fit_transform([texts[d] for d in tdocs]).toarray()
    kq = len(chosen_q)
    topical = {}
    for rep_name, Xr in (("LSA vectors", E[tdocs]), ("tf-idf vectors", Xtf)):
        for name, labels in [("k-means", KMeans(kq, seed=0).fit(Xr).labels_),
                             ("HAC average-link", hac(Xr, kq, "average")[0]),
                             ("HAC complete-link", hac(Xr, kq, "complete")[0])]:
            topical[f"{name} on {rep_name}"] = {"purity": round(purity(list(labels), tgold), 4), "NMI": round(nmi(list(labels), tgold), 4)}
    rl = np.random.default_rng(0).integers(0, kq, len(tgold))
    topical["random assignment (baseline)"] = {"purity": round(purity(list(rl), tgold), 4), "NMI": round(nmi(list(rl), tgold), 4)}
    R["clustering_topical"] = {"topics": kq, "docs": len(tdocs), "scores": topical}

    # ------------------------------------------------------------------ figures
    log("figures")
    _figures(fig_dir, systems, qids, QR, ids, to_run, base, ours, hyb, R, ranks, freqs, T, M, zf, hf, sweep, k1s, bs, diff)
    (out / "results.json").write_text(json.dumps(R, indent=2, default=float))
    (out / "RESULTS.md").write_text(_markdown(R, dense.name))
    log("done ->", out)


def _figures(fig_dir, systems, qids, QR, ids, to_run, base, ours, hyb, R, ranks, freqs, T, M, zf, hf, sweep, k1s, bs, diff):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"figure.dpi": 130, "font.size": 9, "axes.spines.top": False, "axes.spines.right": False})

    # 11-point interpolated precision-recall curves
    fig, ax = plt.subplots(figsize=(5, 3.6))
    dense_name = [n for n in systems if n.startswith("Dense")][0]
    for name in ["Boolean-free baselines:", "TF-IDF cosine (lnc.ltc)", base, dense_name, hyb, ours][1:]:
        run = systems[name][2]
        curve = np.mean([interpolated_pr_curve(run[q], QR[q]) for q in qids], axis=0)
        R.setdefault("pr_curves", {})[name] = curve.round(4).tolist()
        ax.plot(np.linspace(0, 1, 11), curve, marker="o", ms=3, label=name, lw=2.2 if name == ours else 1.2)
    ax.set_xlabel("recall"); ax.set_ylabel("interpolated precision"); ax.legend(fontsize=6.5)
    ax.set_title("11-point interpolated P-R (Cranfield)")
    fig.tight_layout(); fig.savefig(fig_dir / "pr_curves.png"); plt.close(fig)

    # Per-query AP difference (Bridge-PRF - BM25)
    fig, ax = plt.subplots(figsize=(5.5, 3))
    d = np.sort(diff)[::-1]
    ax.bar(range(len(d)), d, width=1.0, color=np.where(d >= 0, "#2a7ab9", "#d0573c"))
    ax.axhline(0, color="k", lw=0.6)
    ax.set_xlabel("queries (sorted)"); ax.set_ylabel("ΔAP  (Bridge-PRF − BM25)")
    w = R["win_tie_loss_vs_bm25"]
    ax.set_title(f"Per-query gain: {w['wins']} wins / {w['ties']} ties / {w['losses']} losses")
    fig.tight_layout(); fig.savefig(fig_dir / "per_query_delta.png"); plt.close(fig)

    # Zipf & Heaps
    fig, axs = plt.subplots(1, 2, figsize=(8, 3))
    axs[0].loglog(ranks, freqs, ".", ms=2); axs[0].set_title(f"Zipf: cf ∝ rank^-{zf.exponent:.2f} (R²={zf.r2:.2f})")
    axs[0].set_xlabel("rank"); axs[0].set_ylabel("collection frequency")
    axs[1].plot(T, M, "-"); axs[1].plot(T, hf.k * T ** hf.b, "--", label=f"M = {hf.k:.1f}·T^{hf.b:.2f}")
    axs[1].set_title("Heaps' law"); axs[1].set_xlabel("tokens T"); axs[1].set_ylabel("vocabulary M"); axs[1].legend()
    fig.tight_layout(); fig.savefig(fig_dir / "zipf_heaps.png"); plt.close(fig)

    # BM25 sweep heatmap
    fig, ax = plt.subplots(figsize=(4.2, 3.4))
    im = ax.imshow(sweep, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(bs)), bs); ax.set_yticks(range(len(k1s)), k1s)
    ax.set_xlabel("b"); ax.set_ylabel("k1"); ax.set_title("BM25 MAP over (k1, b)")
    for i in range(len(k1s)):
        for j in range(len(bs)):
            ax.text(j, i, f"{sweep[i, j]:.3f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im); fig.tight_layout(); fig.savefig(fig_dir / "bm25_sweep.png"); plt.close(fig)

    # alpha curve
    fig, ax = plt.subplots(figsize=(4.5, 3))
    a = list(map(float, R["hybrid_alpha_curve"])); v = list(R["hybrid_alpha_curve"].values())
    ax.plot(a, v, "o-", label="fixed-alpha hybrid")
    ax.axhline(R["oracle_per_query_alpha_MAP"], ls="--", color="gray", label="oracle per-query alpha")
    ax.axhline(R["main_table"][ours]["MAP"], ls=":", color="#d0573c", label="Bridge-PRF (CV)")
    ax.set_xlabel("alpha (weight of BM25)"); ax.set_ylabel("MAP"); ax.legend(fontsize=7)
    ax.set_title("Lexical/semantic interpolation")
    fig.tight_layout(); fig.savefig(fig_dir / "alpha_curve.png"); plt.close(fig)

    # MMR trade-off
    fig, ax = plt.subplots(figsize=(4.2, 3))
    pts = R["mmr_tradeoff"]
    ax.plot([p["ILD@10"] for p in pts.values()], [p["nDCG@10"] for p in pts.values()], "o-")
    for lam, p in pts.items():
        ax.annotate(f"λ={lam}", (p["ILD@10"], p["nDCG@10"]), fontsize=7, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("intra-list diversity@10"); ax.set_ylabel("nDCG@10"); ax.set_title("MMR relevance-diversity trade-off")
    fig.tight_layout(); fig.savefig(fig_dir / "mmr_tradeoff.png"); plt.close(fig)


def _markdown(R, dense_name) -> str:
    L = ["# SearchBridge AI — Experimental Results (Cranfield 1400)", "",
         f"Collection: {R['collection']['docs']} documents, {R['collection']['queries']} judged queries. "
         f"Dense encoder: **{dense_name}**. Ranked runs evaluated to depth 1000. "
         "Tuned systems use 5-fold cross-validation over queries. "
         "† / ‡ / § = significantly different from BM25 / CV-tuned linear hybrid / dense+vector-PRF "
         "(two-sided paired randomisation test on per-query AP, 10k permutations, p < 0.05).", "",
         "## 1. Retrieval effectiveness", "",
         "| System | " + " | ".join(SHOW) + " |", "|---|" + "---:|" * len(SHOW)]
    for name, row in R["main_table"].items():
        mark = ("†" if row["p_vs_bm25_rand"] < 0.05 else "") + ("‡" if row["p_vs_hybrid_rand"] < 0.05 else "") \
            + ("§" if row["p_vs_vprf_rand"] < 0.05 else "")
        bold = "**" if "ours" in name else ""
        L.append(f"| {bold}{name}{bold} | " + " | ".join(
            f"{row[m]:.4f}{mark if m == 'MAP' else ''}" for m in SHOW) + " |")
    w = R["win_tie_loss_vs_bm25"]
    L += ["", f"Bridge-PRF (CV) vs BM25 per query (AP): {w['wins']} wins, {w['ties']} ties, {w['losses']} losses.",
          f"Oracle per-query alpha upper bound for linear hybrid: MAP {R['oracle_per_query_alpha_MAP']:.4f}.", "",
          "![pr](figures/pr_curves.png) ![per-query](figures/per_query_delta.png) ![alpha](figures/alpha_curve.png)", "",
          "## 2. Bridge-PRF ablation (k=5, alpha=0.3)", "", "| Variant | " + " | ".join(SHOW) + " |", "|---|" + "---:|" * len(SHOW)]
    for n, row in R["bridge_ablation"].items():
        L.append(f"| {n} | " + " | ".join(f"{row[m]:.4f}" for m in SHOW) + " |")
    L += ["", "Grid (MAP): " + ", ".join(f"{k}: {v}" for k, v in R["bridge_grid_MAP"].items()), "",
          f"Folds chose: {', '.join(R['bridge_cv_chosen'])}", "",
          "## 3. QAHR — QPP-adaptive fusion weight", "",
          f"Correlation of predicted alpha with oracle alpha: r = {R['qahr']['alpha_pred_vs_oracle_r']:.3f} "
          f"(predicted alpha mean {R['qahr']['pred_alpha_mean']:.2f} ± {R['qahr']['pred_alpha_std']:.2f}).", "",
          "| QPP feature | Pearson r with oracle alpha |", "|---|---:|"]
    L += [f"| {f} | {v} |" for f, v in R["qahr"]["feature_alpha_correlation"].items()]
    L += ["", "## 4. Boolean retrieval (queries as conjunction / disjunction of terms)", "",
          "| Operator | Precision | Recall | F1 | Avg. result-set size |", "|---|---:|---:|---:|---:|"]
    for op in ("AND", "OR"):
        b = R[f"boolean_{op}"]
        L.append(f"| {op} | {b['precision']} | {b['recall']} | {b['F1']} | {b['avg_result_size']} |")
    L += ["", "## 5. Text-processing ablation (BM25)", "", "| Setting | MAP | P@10 | Vocabulary |", "|---|---:|---:|---:|"]
    L += [f"| {k} | {v['MAP']} | {v['P@10']} | {v['vocab']} |" for k, v in R["preprocessing_ablation"].items()]
    L += ["", "![bm25](figures/bm25_sweep.png)", "", "## 6. Index compression & term statistics", "",
          "| Structure | Bytes | Ratio |", "|---|---:|---:|"]
    L += [f"| {c['structure']} | {c['bytes']:,} | {c['ratio']} |" for c in R["compression"]]
    L += ["", f"Zipf exponent {R['zipf']['exponent']} (R² {R['zipf']['r2']}); Heaps k={R['heaps']['k']}, b={R['heaps']['b']} (R² {R['heaps']['r2']}).", "",
          "![zipf](figures/zipf_heaps.png)", "", "## 7. Link analysis: PageRank prior (semantic kNN graph) added to Bridge-PRF", "",
          "| PageRank weight | MAP |", "|---:|---:|"]
    L += [f"| {w} | {m} |" for w, m in R["pagerank_prior_MAP"].items()]
    L += ["", "## 8. Responsible IR: diversity & exposure", "", "| MMR λ | nDCG@10 | ILD@10 |", "|---:|---:|---:|"]
    L += [f"| {l} | {v['nDCG@10']} | {v['ILD@10']} |" for l, v in R["mmr_tradeoff"].items()]
    L += ["", "![mmr](figures/mmr_tradeoff.png)", "", "Venue exposure in Bridge-PRF top-10 vs share of corpus:", "",
          "| Venue group | Corpus share | Exposure share |", "|---|---:|---:|"]
    L += [f"| {g} | {v['corpus_share']} | {v['exposure_share']} |" for g, v in R["venue_exposure_top10"].items()]
    L += ["", "## 9. Text classification (venue, 5-fold CV) & clustering", "", "| Classifier | Accuracy | Macro-F1 |", "|---|---:|---:|"]
    L += [f"| {k} | {v['accuracy']} | {v['macro_F1'] if v['macro_F1'] is not None else '–'} |" for k, v in R["venue_classification_5fold"].items()]
    L += ["", "| Clustering (dense vectors) | Purity | NMI |", "|---|---:|---:|"]
    L += [f"| {k} | {v['purity']} | {v['NMI']} |" for k, v in R["clustering_vs_venue"].items()]
    ct = R["clustering_topical"]
    L += ["", f"Topical clustering: {ct['docs']} documents from the relevant sets of {ct['topics']} queries with disjoint judgements (gold topic = query).", "",
          "| Method | Purity | NMI |", "|---|---:|---:|"]
    L += [f"| {k} | {v['purity']} | {v['NMI']} |" for k, v in ct["scores"].items()]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
