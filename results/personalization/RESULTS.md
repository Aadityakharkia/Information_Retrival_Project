# Retrieval models and search memory on Cranfield (225 judged queries)

Rankings cut at depth 100. MAP = mean average precision over that depth.

| Method | P@10 | R@10 | F1@10 | MAP | nDCG@10 |
|---|---:|---:|---:|---:|---:|
| Boolean (AND) | 0.0089 | 0.0158 | 0.0105 | 0.0144 | 0.0213 |
| TF-IDF | 0.2324 | 0.4002 | 0.2654 | 0.2986 | 0.3813 |
| BM25 | 0.2351 | 0.3964 | 0.2665 | 0.3074 | 0.3872 |
| Semantic (LSA) | 0.2671 | 0.4523 | 0.3037 | 0.3503 | 0.4326 |
| Hybrid (BM25 + semantic) | 0.2613 | 0.4367 | 0.2956 | 0.3462 | 0.4247 |
| Bridge-PRF | 0.2907 | 0.4805 | 0.3274 | 0.3719 | 0.4559 |
| Smart (app default) | 0.2907 | 0.4805 | 0.3274 | 0.3719 | 0.4559 |

Smart vs BM25, paired randomisation test on per-query AP: p = 0.0.

## Search memory (simulated users, real judgements)

Personal weight beta = 0.5 (chosen by 2-fold CV: [0.5, 0.5]).

| Scenario | pairs | MAP without | MAP with | nDCG@10 without | nDCG@10 with | P@10 without | P@10 with | p (MAP) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| related (2-fold CV) | 208 | 0.3605 | 0.3759 | 0.4449 | 0.4635 | 0.2937 | 0.3063 | 0.0 |
| refind (same query again) | 208 | 0.3605 | 0.4092 | 0.4449 | 0.4911 | 0.2938 | 0.2976 | 0.0 |
| residual (opened docs removed) | 206 | 0.3253 | 0.3298 | 0.4079 | 0.4126 | 0.2529 | 0.2578 | 0.0 |
| unrelated (harm check) | 225 | 0.3719 | 0.3723 | 0.4559 | 0.4562 | 0.2907 | 0.2898 | 0.5699 |
| related, 120 days later | 208 | 0.3605 | 0.3610 | 0.4449 | 0.4461 | 0.2938 | 0.2942 | 0.4486 |

MAP on related pairs by beta: 0.05: 0.3622, 0.1: 0.3631, 0.2: 0.3652, 0.3: 0.3685, 0.5: 0.3721

Part 2 uses simulated users; relevance judgements are real (Cranfield).
