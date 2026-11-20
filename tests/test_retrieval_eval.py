"""Unit tests: ranking models, fusion, QPP, feedback, evaluation metrics."""
import math

import numpy as np
import pytest

from searchbridge.evaluation.metrics import (average_precision, bpref, interpolated_pr_curve, ndcg_at, precision_at,
                                             precision_recall_f1, randomization_test, reciprocal_rank, recall_at)
from searchbridge.index.inverted_index import InvertedIndex
from searchbridge.query.feedback import rm3, rocchio
from searchbridge.retrieval.adaptive import ALPHA_GRID, AdaptiveHybrid
from searchbridge.retrieval.fusion import comb_sum, interpolate, normalize, rrf
from searchbridge.retrieval.lexical import BM25Retriever, LMRetriever, SDMRetriever, TFIDFRetriever
from searchbridge.retrieval.qpp import QPP

DOCS = [("a", "wing flutter wing flutter at supersonic speed"),
        ("b", "flutter of panels"),
        ("c", "boundary layer heat transfer"),
        ("d", "wing lift and drag of a swept wing in subsonic flow with many many extra words here")]


@pytest.fixture(scope="module")
def ix():
    return InvertedIndex().build(DOCS)


@pytest.mark.parametrize("cls", [TFIDFRetriever, BM25Retriever, LMRetriever, SDMRetriever])
def test_models_rank_obvious_doc_first(ix, cls):
    r = cls(ix)
    best = r.search(ix.analyzer("wing flutter"), 1)[0][0]
    assert ix.doc_ids[best] == "a"
    assert ix.doc_ids[r.search(ix.analyzer("heat transfer"), 1)[0][0]] == "c"


def test_bm25_explain_sums_to_score(ix):
    bm = BM25Retriever(ix)
    q = ix.analyzer("wing flutter")
    s = bm.score(q)
    for d, v in s.items():
        assert math.isclose(sum(c for *_, c in bm.explain(q, d)), v, rel_tol=1e-9)


def test_bm25_length_normalisation(ix):
    bm = BM25Retriever(ix, b=1.0)
    s = bm.score(["wing"])
    assert s[0] > s[3]   # same tf=2, but d is much longer


def test_fusion():
    a, b = {1: 10.0, 2: 5.0, 3: 0.0}, {3: 0.9, 2: 0.8}
    assert normalize(a) == {1: 1.0, 2: 0.5, 3: 0.0}
    r = rrf([a, b])
    assert r[3] > r[2] > r[1]               # 3rd+1st beats 2nd+2nd beats 1st+absent
    assert interpolate(a, b, 1.0)[1] == 1.0
    assert comb_sum([a, b], mnz=True)[2] > comb_sum([a, b])[2]


def test_qpp_and_rbo(ix):
    q = QPP(ix)
    f = q.pre(["flutter", "zzz"])
    assert f["oov"] == 0.5 and f["qlen"] == 2
    assert QPP.rbo([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert QPP.rbo([1, 2, 3], [4, 5, 6]) == 0.0


def test_adaptive_oracle_and_fit():
    ap = np.zeros(len(ALPHA_GRID)); ap[3] = 0.5
    assert AdaptiveHybrid.oracle_alpha(ap) == pytest.approx(ALPHA_GRID[3])
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 12)); y = np.clip(0.5 + 0.2 * X[:, 0], 0, 1)
    m = AdaptiveHybrid.fit(X, y, l2=0.01)
    assert np.corrcoef([m.predict(x) for x in X], y)[0, 1] > 0.9


def test_feedback(ix):
    q = rocchio(ix, ix.analyzer("flutter"), relevant=[1])
    assert "panel" in q
    e = rm3(ix, ix.analyzer("heat"), [(2, 1.0)])
    assert "boundari" in e and e["heat"] > e["boundari"]


# ---------------------------------------------------------------- metrics (hand-computed)
QR = {"d1": 1, "d3": 1, "d5": 1, "d9": 0}
RUN = ["d1", "d2", "d3", "d4", "d9", "d6"]


def test_set_and_rank_metrics():
    assert precision_at(RUN, QR, 2) == 0.5
    assert recall_at(RUN, QR, 3) == pytest.approx(2 / 3)
    assert average_precision(RUN, QR) == pytest.approx((1 + 2 / 3) / 3)
    assert reciprocal_rank(["x", "d3"], QR) == 0.5
    p, r, f = precision_recall_f1(["d1", "d2"], QR)
    assert (p, r) == (0.5, pytest.approx(1 / 3)) and f == pytest.approx(0.4)


def test_ndcg():
    assert ndcg_at(["d1", "d3", "d5"], QR, 3) == pytest.approx(1.0)
    dcg = 1 + 1 / math.log2(4)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at(RUN, QR, 3) == pytest.approx(dcg / idcg)


def test_bpref_counts_only_judged_nonrelevant():
    # d2,d4 unjudged -> ignored; d9 judged non-relevant ranked above nothing relevant afterwards
    assert bpref(RUN, QR) == pytest.approx((1 + 1) / 3)
    assert bpref(["d9", "d1"], QR) == pytest.approx(0.0)


def test_pr_curve_monotone():
    c = interpolated_pr_curve(RUN, QR)
    assert len(c) == 11 and all(c[i] >= c[i + 1] for i in range(10)) and c[0] == 1.0


def test_randomization_test():
    a = [0.5] * 30; b = [0.1] * 30
    assert randomization_test(a, b, n=2000) < 0.01
    assert randomization_test(a, a, n=2000) == 1.0


def test_sdm_rewards_adjacency():
    ix2 = InvertedIndex().build([("x", "heat transfer measured here"), ("y", "transfer of the measured heat")])
    s = SDMRetriever(ix2).score(ix2.analyzer("heat transfer"))
    assert s[0] > s[1]
