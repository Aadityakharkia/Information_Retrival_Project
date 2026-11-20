# SearchBridge AI: An Intelligent Information Retrieval System for Smart Document Search

**CSD358 Information Retrieval — Course Project Report (draft)**
Shiv Nadar University, Monsoon 2026 · Instructor: Dr. Sonia Khetarpaul
Team: _⟨names, roll numbers⟩_

---

## Abstract
Students and researchers spend a lot of time looking for the right paper, report or passage across scattered
document collections. SearchBridge AI is a complete search system for collections of research papers and
PDFs. It implements the full IR pipeline from scratch: a positional inverted index with SPIMI construction and
compression, Boolean, vector-space, probabilistic (BM25), language-model and Markov-random-field retrieval,
semantic retrieval, query operations, classification and clustering, link analysis, a knowledge-graph layer and
responsible-IR safeguards.

We propose **Bridge-PRF**, a cross-retriever pseudo-relevance-feedback scheme. Documents found by the hybrid
of lexical and semantic retrieval become one shared feedback set, and that set refines *both* representations.
On the Cranfield-1400 test collection (225 queries), Bridge-PRF reaches MAP 0.3856 and nDCG@10 0.4640. That
is +21.8 % MAP over BM25 and +7.4 % over a cross-validation-tuned hybrid, both significant at p < 0.001.
We also report two honest negative results. A query-performance-predicted adaptive fusion weight (QAHR)
does not beat a fixed weight on Cranfield. And on a second, untuned collection of 2,243 computer-science
papers, hybrid retrieval again beats BM25 by about 16 % MAP, but Bridge-PRF does not improve on plain
hybrid fusion there.

## 1. Introduction and motivation
As students, we often spend a lot of time searching websites, research papers and documents for useful
information, and finding the exact passage we need can be hard. Keyword engines miss documents that use
different vocabulary ("aerofoil" vs "wing section"). Purely semantic engines miss rare exact terms such as
codes and names. SearchBridge AI *bridges* the two. It also helps users discover related documents and
explains why each result was returned.

**Goals.** (G1) Implement every module of the CSD358 syllabus as a working component. (G2) Build a usable
prototype: CLI, web UI and REST API, with PDF/HTML ingestion. (G3) Contribute something new and evaluate it
rigorously on a benchmark collection with significance testing. (G4) Address responsible-IR concerns: bias,
misinformation and privacy.

## 2. Related work
*Classical models.* Vector space with tf-idf [4,5]; BM25 from the probabilistic relevance framework [6];
query-likelihood language models with Dirichlet/JM smoothing [7,8]; the sequential dependence model as a
Markov random field over query terms [9].
*Feedback.* Rocchio [19] and relevance models, RM1/RM3 [20,21]. For dense retrievers, vector-based PRF
helps but is fragile [22,23].
*Semantic and hybrid retrieval.* LSA [24], Sentence-BERT [25] and DPR [26]. BEIR [27] shows that BM25 stays a
strong zero-shot baseline and that hybrids are robust. Fusion is done with CombSUM/CombMNZ [29] or RRF [28].
*Query performance prediction* uses pre-retrieval [30–32] and post-retrieval [33,34] signals. Arabzadeh et
al. [36] predict whether to choose sparse or dense retrieval per query.
**Gap.** PRF is normally applied *within* one retriever, so it inherits that retriever's errors, and hybrid
systems usually fuse only once, at the end. We study feeding the *fused* evidence back into both retrievers.

## 3. System design
See `docs/ARCHITECTURE.md` for the diagrams. Table 1 maps each syllabus module to its implementation.

**Table 1. Syllabus coverage**

| Module | What we built |
|---|---|
| 2 Basic IR models | Boolean recursive-descent parser (AND/OR/NOT, parentheses, phrases, `"…"~k` proximity, wildcards); TF-IDF lnc.ltc cosine; BM25 with per-term explanations; QL-LM (Dirichlet, JM); SDM/MRF over the positional index |
| 3 Indexing & compression | Analyzer (Unicode folding, tokenisation, stop list, Porter); positional inverted index built with SPIMI blocks and a k-way heap merge; dynamic auxiliary index and invalidation bit-vector; k-gram index; d-gaps with VByte, Elias-γ and Elias-δ; blocked front coding; Zipf and Heaps fits |
| 4 Evaluation | P/R/F1, P@k, R@k, MAP, MRR, R-Prec, nDCG (exponential gain), BPref, 11-point P-R; paired t-test and randomisation test; 5-fold CV protocol |
| 5 Query operations | Spelling correction (k-gram Jaccard candidates + Damerau-Levenshtein); Rocchio; RM3; association thesaurus; field filters |
| 6 Classification & clustering | Multinomial NB (verified against IIR Example 13.1), spam filter, Rocchio, kNN; spherical k-means++, HAC; labelling; purity, NMI, RI |
| 7 Web search | Crawler with URL frontier, robots.txt, per-host politeness, MinHash near-dup detection; PageRank (dangling nodes, personalisation), HITS |
| 8 Semantic search | LSA / SBERT dense retrieval; pattern NER + PMI collocations; ontology (SKOS-like) with Lesk disambiguation; NPMI knowledge graph for expansion and related concepts |
| 9 Responsible IR | MMR; exposure audit and fair re-ranking [47,48]; explainable credibility score [49,50]; PII redaction, salted user hashing, k-anonymous log release, Laplace-DP counts [51] |

**Collections.** (0) *Research Papers 2016–2025*: the most-cited computer-science papers of 2016–2025
from OpenAlex (about 1,200 per subfield across 12 subfields), with abstracts, authors, venues, keywords
and in-collection citation links, downloaded by `scripts/fetch_openalex.py`. (1) *Classic CS Papers*:
243 full ACM papers (SemEval-2010 Task 5 [52]) and 2,000
Inspec abstracts [53], with author keyphrases as tags, ACM categories as labels, and 40 citation links
matched from reference lists. (2) *Cranfield*, for evaluation. (3) *My library*: the user's own uploads.

**Web application.** A FastAPI backend serves a dependency-free single-page frontend. The Search page offers
autocomplete (keyphrases, mined phrases, vocabulary), "Did you mean", ten ranking models, faceted filters
(automatic topics from k-means over title+abstract vectors labelled by distinctive keyphrases, category,
type, keyphrase), and per-result evidence: a lexical-vs-semantic "bridge meter", BM25 term contributions,
credibility reasons and similar papers. Users can mark results relevant (Rocchio feedback), cluster results
into labelled groups, diversify (MMR), boost authority (PageRank) or enforce fair exposure. Other pages: a
full-text reader with citations, side-by-side model comparison, PDF upload, an interactive concept map,
index statistics with Zipf/Heaps charts and a postings inspector, the evaluation dashboard, and a
trust & privacy playground. Indexes are built in the background and cached, so restarts are instant.

## 4. Proposed methods

### 4.1 Bridge-PRF (main contribution)
Given query *q*, BM25 scores *L₀* and dense cosine scores *D₀*:
1. Hybrid first pass: *H₀ = α·mm(L₀) + (1−α)·mm(D₀)*, where *mm* is min-max normalisation.
2. Shared feedback set: *F = top-k(H₀)*.
3. Lexical refinement: *L₁ = BM25(RM3(q, F))*, with 10 expansion terms and original-query weight 0.6.
4. Semantic refinement: *v′ = normalize(v_q + β·mean_{d∈F} e_d)*, *D₁ = cos(E, v′)*, with β = 0.8.
5. Output: *α·mm(L₁) + (1−α)·mm(D₁)*.

*Intuition.* BM25 alone feeds back documents that share surface words. The hybrid list also contains
documents found semantically, so RM3 can pick up vocabulary the user never typed. Likewise, the dense
query vector is pulled towards documents with strong exact-term evidence, which reduces semantic drift.

### 4.2 QAHR: QPP-gated adaptive hybrid (exploratory)
For each query we compute 12 features: avgIDF, maxIDF, SCQ, SCS, |q|, OOV, NQC(BM25), NQC(dense),
WIG(BM25), top-1 margins, and RBO between the two top-20 lists. A ridge regressor predicts the per-query
optimal α, trained on smoothed oracle α* values from an 11-point grid.

## 5. Experimental setup
*Collection:* Cranfield-1400 [15], with 1,400 aerodynamics abstracts and 225 queries (1,612 relevant
judgements). *Protocol:* ranked runs to depth 1000. Every tuned parameter (hybrid α, Bridge-PRF k and α,
QAHR regressor) is chosen by 5-fold cross-validation over queries, so a query is never scored by a setting
tuned on its own judgements. *Significance:* two-sided paired randomisation test on per-query AP with 10,000
permutations [18]. *Dense encoder:* LSA with 200 dimensions (fully offline). The benchmark can be re-run with
Sentence-BERT (`--encoder sbert`). *Reproduce:* `python experiments/run_benchmark.py` (about 1 minute).

## 6. Results

**Table 2. Retrieval effectiveness on Cranfield (MAP significance: † vs BM25, ‡ vs tuned hybrid, § vs dense+vector-PRF; p < 0.05)**

| System | MAP | P@10 | nDCG@10 | MRR | R@100 |
|---|---:|---:|---:|---:|---:|
| TF-IDF cosine (lnc.ltc) | 0.3080‡§ | 0.2351 | 0.3860 | 0.5382 | 0.7603 |
| BM25 (k1=1.2, b=0.75) | 0.3165‡§ | 0.2378 | 0.3909 | 0.5417 | 0.7505 |
| QL-LM Dirichlet (μ=300) | 0.3024†‡§ | 0.2302 | 0.3814 | 0.5465 | 0.7380 |
| QL-LM Jelinek-Mercer (λ=0.7) | 0.2931†‡§ | 0.2244 | 0.3729 | 0.5364 | 0.7358 |
| SDM / MRF | 0.3055†‡§ | 0.2342 | 0.3884 | 0.5604 | 0.7426 |
| Dense (LSA-200) | 0.3585†§ | 0.2684 | 0.4354 | 0.5819 | 0.8042 |
| BM25 + RM3 | 0.3535†§ | 0.2676 | 0.4286 | 0.5629 | 0.7783 |
| Dense + vector-PRF | 0.3773†‡ | 0.2827 | 0.4524 | 0.5915 | 0.8293 |
| Hybrid RRF | 0.3501†‡§ | 0.2631 | 0.4264 | 0.5706 | 0.7824 |
| Hybrid linear (α CV-tuned) | 0.3592†§ | 0.2720 | 0.4371 | 0.5714 | 0.7977 |
| QAHR (ours, CV) | 0.3570†§ | 0.2716 | 0.4347 | 0.5621 | 0.7946 |
| Bridge-PRF (ours, a-priori k=5, α=0.3) | 0.3785†‡ | 0.2924 | 0.4582 | 0.5619 | 0.8196 |
| **Bridge-PRF (ours, CV-tuned)** | **0.3856**†‡ | **0.2942** | **0.4640** | 0.5819 | 0.8267 |

**Observations.**
1. On this small, domain-specific collection, *semantic matching beats every lexical model*. LSA-200
   (0.3585) outperforms BM25 (0.3165), consistent with the original LSA findings on small collections [24].
   BM25 is the best lexical model. SDM's proximity features give a small gain over plain QL (0.3024 → 0.3055).
2. Fusing once (linear or RRF) gives little over the dense run alone (0.3592 vs 0.3585). This motivates
   using fused evidence *earlier*, as feedback.
3. **Bridge-PRF is the best system on MAP, P@10 and nDCG@10.** It beats BM25 on 171 of 225 queries
   (12 ties, 42 losses) and recovers 75 % of the gap between the tuned hybrid and the *oracle* per-query-α
   hybrid (0.3942). All five CV folds chose the same setting (k=3, α=0.2), so the configuration is stable.
4. Being honest about attribution: the strongest single ingredient is vector-PRF on the dense side
   (0.3773). Bridge-PRF's MAP gain over it (+2.2 %) is **not** significant (p = 0.14). The benefit shows mostly
   in early precision (P@10 +4.1 %, nDCG@10 +2.6 %), which is what a user sees on the first page.

**Table 3. Bridge-PRF ablation (k=5, α=0.3)**

| Variant | MAP | P@10 | nDCG@10 |
|---|---:|---:|---:|
| Full Bridge-PRF | 0.3785 | 0.2924 | 0.4582 |
| − lexical RM3 branch | 0.3753 | 0.2853 | 0.4528 |
| − dense vector-PRF branch | 0.3659 | 0.2764 | 0.4433 |
| self-feedback (each retriever uses its own top-k) | 0.3784 | 0.2920 | 0.4569 |
| no feedback (= hybrid) | 0.3602 | 0.2724 | 0.4388 |

Both branches contribute, and the dense branch matters most. Sharing one feedback set gives small but
consistent gains over self-feedback at the best settings (k=3, α=0.2: 0.3856 vs 0.3815; k=5, α=0.2: 0.3828
vs 0.3813). It also needs only *one* feedback set, so it costs less.

**QAHR (negative result).** The best single QPP feature correlates only weakly with the oracle α (|r| ≤ 0.20,
for query length and NQC). The cross-validated predictor reaches r = 0.08 with the oracle, so QAHR ends
up close to a fixed α (MAP 0.3570 vs 0.3592, not significant). The oracle headroom is real (0.3942), but
standard QPP signals cannot capture it on 225 short, homogeneous queries. Supervised QPP on larger query
logs is left as future work.

**Table 4. Transfer to the CS Research Library (no tuning; 150 author keyphrases as queries, papers carrying
the keyphrase are relevant, keyphrases are not indexed)**

| System | MAP | P@10 | nDCG@10 | MRR |
|---|---:|---:|---:|---:|
| BM25 | 0.2511 | 0.2433 | 0.3136 | 0.4740 |
| QL-LM Dirichlet | 0.2393 | 0.2360 | 0.3024 | 0.4645 |
| Dense (LSA) | 0.2678 | 0.2473 | 0.3318 | 0.5478 |
| Hybrid RRF | 0.2890 | 0.2627 | 0.3514 | 0.5623 |
| Hybrid linear (α = 0.3) | **0.2909** | **0.2693** | **0.3560** | 0.5616 |
| Bridge-PRF (Cranfield defaults) | 0.2869 | 0.2680 | 0.3491 | 0.5350 |

Hybrid lexical+semantic retrieval transfers well (+16 % MAP over BM25), but Bridge-PRF's feedback step adds
nothing here. A plausible reason: this collection mixes 4,000-word full papers with 100-word abstracts, so
the top-5 feedback set is dominated by long papers whose centroid drifts away from the short abstracts that
make up most relevant sets. Keyphrase queries are also short noun phrases with little room for expansion.
So the Cranfield gains should be read as collection-dependent. A small grid over both collections shows
that a shallower feedback set and equal weighting (k = 3, α = 0.5) is the most robust compromise:
MAP 0.2993 on the CS library (the best of all settings tried, above hybrid's 0.2988) and 0.3794 on
Cranfield (vs 0.3856 for the CV-tuned setting). The web application uses this setting.

**Other experiments** (full tables in `results/RESULTS.md`):
* *Boolean retrieval:* treating queries as conjunctions gives P = 0.037 and R = 0.014, with an average of
  0.1 results per query. Disjunctions give R = 0.96 but P = 0.009. This is the classic motivation for ranked retrieval.
* *Text processing:* stemming plus stop-word removal is best (MAP 0.3165 vs 0.2789 with neither) and shrinks
  the vocabulary by 37 % (7,436 → 4,676 terms).
* *BM25 parameters:* b between 0.75 and 1.0 is best for every k1, and MAP rises slowly with k1 (0.3165 at the default k1 = 1.2 → 0.3216 at k1 = 2.5). We keep the standard defaults to avoid tuning on test queries.
* *Compression:* gap + VByte stores postings in 27 % of the uncompressed size, Elias-γ/δ in 24 %, and front
  coding stores the lexicon in 39 %. Heaps' law fits with b = 0.45 (R² = 0.998). The Zipf slope is 1.63; it is
  steeper than 1 because stop words were removed.
* *Link analysis:* Cranfield has no citation links. As an experiment, PageRank on a semantic kNN graph
  (LexRank-style centrality) was added as a prior: it slightly *hurts* MAP (0.3785 → 0.3726 at weight 0.2).
  Centrality is not relevance for topical queries, and in version 2 the engine only computes PageRank on real
  links (§7.3).
* *Diversity:* MMR λ = 0.7 raises intra-list diversity by 2.2 % at a cost of 2.8 % nDCG@10. λ = 0.5 trades
  10 % nDCG for 9 % diversity.
* *Exposure audit:* Bridge-PRF's top-10 exposure by publication venue closely tracks each venue's corpus
  share (largest gap: journal papers get 41.5 % of exposure vs 44.3 % of the corpus), so there is no strong venue bias.
* *Classification* (venue from text, 4 classes, 5-fold CV): NB 67.0 %, kNN 67.2 %, Rocchio 63.6 %, against a
  57.3 % majority baseline.
* *Topical clustering* (179 docs from 8 queries with disjoint relevant sets): k-means on LSA vectors reaches
  purity 0.79 and NMI 0.72, against purity 0.28 for random assignment. LSA beats tf-idf (NMI 0.56), and
  average-link HAC does poorly (purity 0.41).

## 7. Version 2: a search engine that learns from its users

Version 2 keeps everything above and connects the syllabus algorithms to the live search path. The default
ranking mode in the app is now **Smart**:

    final(d) = relevance(d)                         Bridge-PRF score, min-max scaled to [0, 1] over the top 200
             + 0.05 · PageRank_V3(d) + 0.05 · HITS_authority(d)    only where real links exist
             + 0.10 · similarity to a related previous query       session context, only if cosine ≥ 0.4
             + β · gate(relevance) · p_user(d)                    search memory, β = 0.5, p_user ∈ [−1, 1]

Relevance is the largest term by construction: every other addition is bounded and smaller than its range.

### 7.1 Search memory (personalised ranking)
Each browser gets an anonymous id (cookie); interactions are stored in SQLite outside the project folder and
never mixed between users. Recorded: searches, the top-10 results shown, documents opened (from a result list,
a link inside another document, related documents or directly), time spent on each document, links followed
from one document to another, and thumbs up/down. Design choices, following implicit-feedback research
[57–61]:
* opening a document is weak evidence (+0.25); what follows decides: reading ≥ 30 s (+0.75), 10–30 s (+0.3),
  leaving within 10 s (−0.2, "pogo-sticking"); revisits add 0.45·log(1 + extra visits);
* following a link from A to B credits A (explored further) and B (reached deliberately); a document merely
  linking to another is graph authority, not user evidence, and is kept separate;
* explicit feedback ±1.5, latest judgement wins; results shown repeatedly but never opened lose a little;
* all evidence decays with a 21-day half-life and is squashed with tanh, so affinity stays in (−1, 1);
* p_user = 0.5·affinity + 0.2·closeness to the user's interest vector (embedding centroid of useful documents,
  applied only to *other* documents) + 0.2·"useful for a similar earlier query" + 0.1·"linked to a document
  the user explored";
* the gate removes positive boosts from documents with normalised relevance below 0.3.
Users can see everything that was learned (Your search memory page), pause learning, or clear it.
Popular-query suggestions only include queries run by at least three different users (k-anonymity [62]).

### 7.2 Results
Retrieval models on Cranfield (225 judged queries, rankings cut at 100):

| Method | P@10 | R@10 | F1@10 | MAP | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| Boolean (AND) | 0.0089 | 0.0158 | 0.0105 | 0.0144 | 0.0213 |
| TF-IDF | 0.2200 | 0.3783 | 0.2516 | 0.2795 | 0.3582 |
| BM25 | 0.2218 | 0.3744 | 0.2522 | 0.2886 | 0.3635 |
| Semantic (LSA) | 0.2516 | 0.4256 | 0.2864 | 0.3287 | 0.4053 |
| Hybrid (BM25 + semantic) | 0.2467 | 0.4117 | 0.2794 | 0.3267 | 0.4003 |
| Bridge-PRF | 0.2738 | 0.4542 | 0.3094 | 0.3506 | 0.4288 |
| Smart (app default) | 0.2738 | 0.4542 | 0.3094 | 0.3506 | 0.4288 |

Smart equals Bridge-PRF here: Cranfield has no links and these runs have no history, so the extra signals
are zero. Smart vs BM25: p < 0.001 (paired randomisation test).

Search memory is evaluated with **simulated users** (real users were not available) on the **real** judgements:
the user searches query A, examines the top 10 with position bias, opens relevant documents with probability
0.85 and reads them, opens non-relevant ones 15 % of the time and leaves within seconds, and sometimes
returns to a document later; then they search query B. The engine sees only clicks and dwell times. β was
chosen by 2-fold cross-validation over query pairs from {0.05, 0.1, 0.2, 0.3, 0.5} (the grid stops at 0.5
so relevance stays dominant; CV picked [0.5, 0.5]).

| Scenario | Pairs | MAP without | MAP with | nDCG@10 without | nDCG@10 with | p (MAP) |
|---|---:|---:|---:|---:|---:|---:|
| related (2-fold CV) | 208 | 0.3375 | 0.3503 | 0.4157 | 0.4309 | < 0.001 |
| refind (same query again) | 208 | 0.3375 | 0.3845 | 0.4157 | 0.4600 | < 0.001 |
| residual (opened docs removed) | 207 | 0.3034 | 0.3066 | 0.3795 | 0.3823 | < 0.001 |
| unrelated (harm check) | 225 | 0.3506 | 0.3509 | 0.4288 | 0.4296 | 0.6992 |
| related, 120 days later | 208 | 0.3375 | 0.3379 | 0.4157 | 0.4169 | 0.4436 |

* **Related searches** (B shares relevant documents with A): MAP +3.8 %, significant.
* **Re-finding** (searching the same thing again): MAP +13.9 %.
* **Residual** (documents already opened removed from scoring): +1.1 %, small but significant, so the interest
  vector generalises a little beyond the exact documents read.
* **Unrelated searches**: no change (p = 0.6992), so the memory does not drag old interests into new topics.
* **After 120 days** the effect has decayed away, as designed.
These numbers depend on the click simulation; real behaviour is noisier, so treat them as evidence that the
mechanism is sound and safe, not as the size of the gain users would see.

### 7.3 Other upgrades
* **Search-as-you-type suggestions** built from the index: keyphrase and dictionary completions (sorted arrays
  + binary search; the next word is ranked by how often it actually follows the typed words, using the
  positional index), matching document titles, the user's own history, k-anonymous popular queries,
  related concepts from the concept graph, and k-gram spelling correction. Debounced in the browser
  (110 ms), keyboard navigable.
* **Link analysis on real links only.** Version 1 ran PageRank on a semantic kNN graph when a collection had
  no links; version 2 never invents links. PageRank V1 (no teleport), V2 (teleport) and V3 (dead ends
  redistributed + teleport) are computed on citations or crawled hyperlinks and compared on the Insights page;
  V3 and query-time HITS authority feed Smart ranking. On the Classic CS collection only 40 citation links
  exist, so their effect is small; the crawler (§3) produces densely linked collections.
* **Crawler collection.** `scripts/crawl_web.py` (or the Library page) crawls a site breadth-first, obeys
  robots.txt and Crawl-delay, waits ≥ 1 s per host, stays inside a path prefix, skips near-duplicates and keeps
  only links between crawled pages, producing the “Web pages” collection.
* **Near-duplicate folding.** MinHash (64 permutations, 4-word shingles) + LSH banding finds pairs with
  Jaccard ≥ 0.8; duplicates are folded into one result.
* **Categories.** Naive Bayes, Rocchio and kNN are trained on topical category labels (held-out accuracy
  shown in Insights). A document without a category gets one only when NB and Rocchio agree with high
  confidence; on Classic CS this labels 117 of 2,000 unlabelled abstracts and leaves the rest alone. The same
  classifiers detect query intent and offer a one-click category filter.
* **Topic hierarchy.** Average-link hierarchical clustering of the k-means topic centroids.
* **Interface.** A new interface with progressive disclosure: a plain search page by default, with “Why this
  result” (score components, BM25 term contributions, personal reasons), topic groups, filters, and
  advanced views on a separate Insights page. The previous interface remains at `/classic`.

## 8. Responsible IR
* **Bias and filter bubbles:** MMR re-ranking and fair-exposure re-ranking are both available in the UI, and
  the benchmark audits exposure by publication venue.
* **Misinformation:** every result carries a transparent credibility score with its reasons (scholarly
  markers, hedging, clickbait, absolutist claims, source reputation, citation authority). Low scores are
  flagged rather than silently removed, which keeps the user in control.
* **Privacy:** snippets and logs are PII-redacted (email, phone, Aadhaar-like IDs, PAN, Luhn-checked
  cards, IPs). User IDs are salted hashes. Query statistics are released only when k-anonymous, with
  ε-differentially-private noise.
* **Explainability:** BM25 term contributions, query-expansion terms, and the components of related-document
  scores are all shown to the user.

## 9. Limitations and future work
* Bridge-PRF's gain did not transfer to the CS Research Library (Table 4); feedback on collections with
  very mixed document lengths needs more work.
* Cranfield is small and old. Evaluating on BEIR subsets (SciFact, NFCorpus, TREC-COVID) with SBERT or
  E5 encoders would test generality. The code supports this through `load_jsonl` and `--encoder sbert`.
* Dense retrieval uses brute-force cosine; it needs an ANN index (FAISS/HNSW) at scale.
* A cross-encoder re-ranker stage and learned sparse models (SPLADE) are natural extensions.
* The credibility score is heuristic. A learned model on labelled fake-news data would be stronger, at the
  cost of transparency.
* QAHR could use supervised QPP (e.g., BERT-QPP) and larger query logs.
* Search memory was evaluated with simulated users; a small user study (or an interleaving experiment)
  would measure the real gain. Profiles are per browser; there is no login, so clearing cookies starts over.
* Link signals are only as good as the links: Classic CS has very few citations, and the Research Papers
  collection (with real citations) needs an OpenAlex download; OpenAlex returned 401 errors without an API key during development, so set `OPENALEX_API_KEY` if you have one.

## 10. Conclusion
SearchBridge AI implements the CSD358 syllabus end to end as a usable, tested search system (60 automated
tests, a web application, a CLI and a REST API). Its main contribution, Bridge-PRF, feeds hybrid lexical-semantic evidence back
into both retrievers. It improves MAP by 21.8 % over BM25 and by 7.4 % over a tuned hybrid on Cranfield,
with every parameter chosen by cross-validation and every claim backed by a significance test. On a
second collection the hybrid design transfers, while the feedback step does not, which marks out where
the method needs further work.

## Appendix A. Reproducibility
```
pip install -r requirements.txt
pytest -q
python experiments/run_benchmark.py      # writes results/RESULTS.md, results/results.json, results/figures/
python experiments/keyphrase_benchmark.py   # writes results/keyphrase/
./start.sh                               # web application at http://127.0.0.1:8000
```
Hardware: any laptop; the full benchmark takes about 1 minute on CPU. Random seeds are fixed (42 for CV folds,
0 for clustering).

## References
See `docs/REFERENCES.md` (53 entries). Bracketed numbers in this report refer to that list.
