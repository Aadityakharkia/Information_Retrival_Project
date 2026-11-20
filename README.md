# SearchBridge AI
**An Intelligent Information Retrieval System for Smart Document Search**

CSD358 Information Retrieval · Shiv Nadar University · Monsoon 2026 · Instructor: Dr. Sonia Khetarpaul

SearchBridge AI finds relevant information in large collections of documents, research papers and PDFs.
It combines classical IR (Boolean, TF-IDF, BM25, language models, Markov random fields) with semantic
search, and adds **Bridge-PRF**, a cross-retriever pseudo-relevance-feedback method that we propose. It
also does related-document discovery, knowledge-graph concepts, explainable rankings, and responsible-IR
safeguards (diversity, fair exposure, credibility flags, privacy-preserving logs).

| Cranfield-1400 (225 queries) | MAP | P@10 | nDCG@10 |
|---|---:|---:|---:|
| BM25 | 0.3165 | 0.2378 | 0.3909 |
| Hybrid BM25 + semantic (CV-tuned) | 0.3592 | 0.2720 | 0.4371 |
| **Bridge-PRF (ours, CV-tuned)** | **0.3856** | **0.2942** | **0.4640** |

That is **+21.8 % MAP over BM25** and **+7.4 % over a tuned hybrid**. Both gains are significant (paired
randomisation test, p < 0.001), and Bridge-PRF beats BM25 on 171 of 225 queries. The full results,
ablations and figures are in [`results/RESULTS.md`](results/RESULTS.md).

A second, untuned test on the CS Research Library (150 author keyphrases as queries) confirms that hybrid
retrieval transfers (MAP 0.29 vs 0.25 for BM25), but Bridge-PRF does not beat plain hybrid fusion there
([`results/keyphrase/RESULTS.md`](results/keyphrase/RESULTS.md)).

### What's new in version 2
* **Search memory.** The engine learns, per browser, which documents you actually find useful: what you read
  for a while, return to, explore from and rate. It ranks them, and similar documents, a little higher in
  later related searches. Quick clicks you abandon count against a document; old activity fades (21-day
  half-life); boosts are bounded so relevance always comes first. You can inspect, pause or clear it.
  With simulated users on Cranfield's real judgements, related searches gain 3.8 % MAP and repeat searches
  13.9 %, with no change on unrelated searches ([results](results/personalization/RESULTS.md)).
* **Intelligent search box.** Completions, matching document titles, your recent searches, popular searches
  (k-anonymous), related concepts and spelling fixes, all generated from the index as you type.
* **Smart ranking** (new default): Bridge-PRF relevance + PageRank V3 and HITS authority (real citations and
  hyperlinks only) + session context + search memory, with near-duplicates folded and every component shown
  under "Why this result".
* **Crawler collection**: crawl a website from the Library page into a searchable collection with its links.
* **Categories and topics**: Naive Bayes / Rocchio / kNN categorisation with a reject option and query-intent
  detection; k-means topics with a hierarchical topic map.
* **New interface** with a simple search page and an Insights section for the algorithms.

## Run it
```bash
./start.sh                       # macOS / Linux: creates a venv, installs, starts, opens the browser
```
or manually:
```bash
python3 -m venv ~/.venvs/searchbridge && source ~/.venvs/searchbridge/bin/activate
pip install -r requirements.txt
python -m uvicorn app.server:app --port 8000      # open http://127.0.0.1:8000
```
On the first run `start.sh` also installs Sentence-BERT for semantic search (skip with
`SEARCHBRIDGE_LITE=1`; LSA is used instead). The Research Papers collection (OpenAlex, with real
citation links) is downloaded only when `OPENALEX_API_KEY` is set. Indexing takes 1–3 minutes; indexes
are cached in `~/.cache/searchbridge`, so later starts are instant. Search memory is stored in
`~/.searchbridge/interactions.db` (outside the project folder; set `SEARCHBRIDGE_DATA` to move it).

The app uses Bridge-PRF with feedback depth 3 and equal word/meaning weight (α = 0.5). That setting was
the most robust across both benchmarks (best on the CS keyphrase benchmark, 0.006 MAP below the Cranfield-tuned setting
on Cranfield).

### The web app
| Page | What it does |
|---|---|
| **Home / Search** | Search box with live suggestions; results with highlighted terms, topic groups, filters (topic, category, type, keyphrase), query-intent hint, "Why this result", 👍 / 👎 feedback and Rocchio refinement, near-duplicate folding, related searches |
| **Document** | Full text with highlights, citations / links in and out (following one is remembered), related documents, PageRank and credibility |
| **Your search memory** | What the engine has learned about you, with reasons; pause or clear it |
| **Insights** | Ranking methods side by side · PageRank V1 / V2 / V3 and HITS · topics, topic hierarchy and classifiers · dictionary, postings and compression · evaluation · crawler and duplicates |
| **Library** | Upload PDF / TXT / MD / HTML files, or crawl a website into the "Web pages" collection |
| `/classic` | The previous interface (concept map, trust & privacy tools, two-model compare) |

---

## Features → syllabus map

| # | Course module | Implemented in SearchBridge |
|---|---|---|
| 1 | Introduction / impact of the web | Web crawler, link-analysis prior, PDF/HTML ingestion (`documents.py`, `web/`) |
| 2 | Basic IR models | Boolean (AND/OR/NOT, phrase, proximity `~k`, wildcards) · TF-IDF cosine (lnc.ltc) · **BM25** · query-likelihood LM (Dirichlet, Jelinek-Mercer) · **Markov random field / SDM** (`retrieval/`) |
| 3 | Indexing, storage, compression | Tokenisation, stop words, Porter stemming · positional inverted index · **SPIMI block construction + k-way merge** · dynamic (auxiliary) index + lazy deletes · k-gram index · gap + **VByte / Elias-γ / Elias-δ** · front-coded lexicon · Zipf and Heaps fits (`index/`, `text/`) |
| 4 | Evaluation | P, R, F1, P@k, R@k, **MAP**, MRR, R-Prec, **nDCG**, **BPref**, 11-pt P-R curve, paired t-test + randomisation test (`evaluation/`) |
| 5 | Query operations | Search-as-you-type suggestions from the index · spelling correction (k-gram + Damerau-Levenshtein) · **Rocchio** relevance feedback · persistent implicit + explicit feedback (search memory) · **RM3** pseudo-relevance feedback · association-thesaurus expansion · query language with field filters (`author:`, `type:`) |
| 6 | Classification & clustering | Multinomial Naive Bayes, Rocchio centroid, kNN (category labelling with reject option, query intent), spam filter · k-means (k-means++), HAC (single/complete/average) · cluster labelling · purity / NMI / Rand index (`mining/`) |
| 7 | Web search | Polite crawler (robots.txt + Crawl-delay, politeness delay, frontier, path scope) → "Web pages" collection · MinHash + LSH near-duplicate folding · **PageRank V1 / V2 / V3** and **HITS** on real links, used in Smart ranking (`web/`, `scripts/crawl_web.py`) |
| 8 | Semantic search | Dense retrieval (LSA offline / Sentence-BERT) · entity recognition (patterns + PMI collocations) · ontology linking with Lesk disambiguation · **knowledge graph** for expansion and related concepts (`semantic/`) |
| 9 | Responsible IR | MMR diversification · fairness-of-exposure audit and fair re-ranking · explainable credibility / fake-news flags · PII redaction, k-anonymous query log, differentially-private counts (`responsible/`) |

## Novel contributions
1. **Bridge-PRF (cross-retriever PRF).** The top-k results of the *hybrid* ranking become one shared
   feedback set. That set expands the lexical query (RM3) and moves the semantic query vector
   (vector-Rocchio), and the two refined runs are fused. Each retriever learns from documents the other one
   found. See `retrieval/bridge_prf.py`.
2. **QAHR (QPP-gated adaptive hybrid).** A per-query lexical/semantic weight is regressed from 12
   query-performance-prediction features, including NQC, WIG, SCQ and RBO agreement between the two
   retrievers. We report it honestly as an exploratory, negative result on Cranfield (Section 3 of the results).
3. **Explainable "bridge documents".** Related-document discovery fuses semantic, lexical, knowledge-graph
   entity and link-graph evidence, and shows each component.
4. **Search memory with safeguards.** Dwell-time-aware implicit feedback, link-following and explicit
   feedback, time decay, a relevance gate and a bounded weight chosen by cross-validation; user-visible and
   resettable (`personal/`).
5. **Transparent trust layer.** Every result carries a feature-based credibility score with reasons, and
   snippets are PII-redacted.

## Development
```bash
pytest -q                                  # 60 tests
python experiments/run_benchmark.py        # Cranfield experiments (~1 min)
python experiments/keyphrase_benchmark.py  # CS-library keyphrase experiment
python experiments/personalization_benchmark.py  # retrieval models + search memory (~6 min)
python scripts/crawl_web.py --seed https://en.wikipedia.org/wiki/Information_retrieval --prefix /wiki/ --exclude : --max-pages 300
python scripts/prepare_cs_library.py       # rebuild the CS library from the public datasets
# REST API docs: http://127.0.0.1:8000/docs
# optional, better semantic model (downloads ~90 MB once): pip install sentence-transformers
```

### CLI
```bash
python -m searchbridge.cli index cranfield -o cran.pkl            # or: index ./my_pdfs -o mine.pkl
python -m searchbridge.cli search cran.pkl "heat transfer in hypersonic boundry layers" --explain
python -m searchbridge.cli search cran.pkl '"boundary layer" AND (suction OR injection) AND NOT turbulent'
python -m searchbridge.cli search cran.pkl "shock waves author:lees" -m bm25
python -m searchbridge.cli related cran.pkl 1
python -m searchbridge.cli crawl https://example.edu --max-pages 30 -o site.jsonl
```

### Python API
```python
from searchbridge import SearchEngine, EngineConfig, load_directory
engine = SearchEngine.from_documents(load_directory("papers/"), EngineConfig(encoder="auto"))
resp = engine.search("transformer models for document ranking", mode="bridge", k=10, diversify=True)
for h in resp.hits:
    print(h.rank, h.title, h.score, h.credibility, h.explanation[:3])
engine.related_documents(resp.hits[0].doc_id)
```

Search modes: `smart` (default in the app), `bridge`, `adaptive`, `hybrid`, `rrf`, `bm25`, `tfidf`, `lm`, `sdm`, `dense`, `boolean`.

## Project layout
```
searchbridge/
  text/preprocess.py        tokeniser, stop words, Porter stemmer, analyzer
  index/                    inverted_index (SPIMI, positional, dynamic) · kgram · compression · laws (Zipf/Heaps)
  retrieval/                boolean · lexical (TF-IDF, BM25, LM, SDM) · semantic · fusion · qpp · adaptive · bridge_prf
  query/feedback.py         Rocchio, RM3, association thesaurus
  mining/                   classify (NB, Rocchio, kNN) · cluster (k-means, HAC, metrics)
  web/                      crawler (robots, politeness, MinHash) · linkanalysis (PageRank V1/V2/V3, HITS)
  personal/                 store (interaction log) · profile (decayed evidence) · rerank (bounded boost)
  suggest.py                search-as-you-type suggestions · mining/categorize.py (classifiers with reject option)
  semantic/                 entities (NER, collocations, ontology linking) · knowledge_graph
  responsible/              fairness (MMR, exposure) · privacy (PII, k-anon, DP) · credibility
  evaluation/metrics.py     all IR metrics + significance tests
  engine.py                 SearchEngine facade · snippets.py · cli.py
app/                        server.py (FastAPI) · static/ (index.html, sb.css, sb.js — no build step; papers/ = /classic)
experiments/                run_benchmark.py (Cranfield) · keyphrase_benchmark.py (CS library) · personalization_benchmark.py
data/                       cs_papers/ · cranfield/ · sample/ · ontology.json · library/ (your uploads) · web/ (crawled)
docs/                       REPORT.md · ARCHITECTURE.md · REFERENCES.md
tests/                      60 unit / integration / API tests
```

## Data
`data/cs_papers/` is the CS Research Library: 243 full ACM conference papers from SemEval-2010 Task 5
(Kim et al., 2010) and 2,000 Inspec journal abstracts (Hulth, 2003), with author keyphrases, ACM categories
and citation links matched from reference lists (`scripts/prepare_cs_library.py` rebuilds it).

The `data/cranfield/` folder holds the Cranfield collection: 1,400 aerodynamics abstracts, 225 queries and
relevance judgements (Cleverdon, 1967), in TREC-XML format. It is bundled for offline reproducibility, and
`scripts/download_cranfield.py` fetches it again.
