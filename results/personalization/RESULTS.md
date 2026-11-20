# Retrieval models and search memory on Cranfield (225 judged queries)

Rankings cut at depth 100. MAP = mean average precision over that depth.

| Method | P@10 | R@10 | F1@10 | MAP | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| Boolean (AND) | 0.0089 | 0.0158 | 0.0105 | 0.0144 | 0.0213 |
| TF-IDF | 0.2200 | 0.3783 | 0.2516 | 0.2795 | 0.3582 |
| BM25 | 0.2218 | 0.3744 | 0.2522 | 0.2886 | 0.3635 |
| Semantic (LSA) | 0.2516 | 0.4256 | 0.2864 | 0.3287 | 0.4053 |
| Hybrid (BM25 + semantic) | 0.2467 | 0.4117 | 0.2794 | 0.3267 | 0.4003 |
| Bridge-PRF | 0.2738 | 0.4542 | 0.3094 | 0.3506 | 0.4288 |
| Smart (app default) | 0.2738 | 0.4542 | 0.3094 | 0.3506 | 0.4288 |

Smart vs BM25, paired randomisation test on per-query AP: p = 0.0.

## Search memory (simulated users, real judgements)

Personal weight beta = 0.5 (chosen by 2-fold CV: [0.5, 0.5]).

| Scenario | pairs | MAP without | MAP with | nDCG@10 without | nDCG@10 with | P@10 without | P@10 with | p (MAP) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| related (2-fold CV) | 208 | 0.3375 | 0.3503 | 0.4157 | 0.4309 | 0.2755 | 0.2865 | 0.0 |
| refind (same query again) | 208 | 0.3375 | 0.3845 | 0.4157 | 0.4600 | 0.2755 | 0.2788 | 0.0 |
| residual (opened docs removed) | 207 | 0.3034 | 0.3066 | 0.3795 | 0.3823 | 0.2372 | 0.2406 | 0.0001 |
| unrelated (harm check) | 225 | 0.3506 | 0.3509 | 0.4288 | 0.4296 | 0.2738 | 0.2733 | 0.6992 |
| related, 120 days later | 208 | 0.3375 | 0.3379 | 0.4157 | 0.4169 | 0.2755 | 0.2760 | 0.4436 |

MAP on related pairs by beta: 0.05: 0.3388, 0.1: 0.3398, 0.2: 0.342, 0.3: 0.3447, 0.5: 0.3474

Part 2 uses simulated users; relevance judgements are real (Cranfield).
