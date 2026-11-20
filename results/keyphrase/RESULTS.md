# Keyphrase benchmark — CS Research Library

150 author keyphrases used as queries over the 2,243-paper CS Research Library; papers tagged with the keyphrase are relevant (tags are not indexed). Parameters are the Cranfield defaults, so this tests whether the methods transfer to a new collection without tuning.

| System | MAP | P@10 | nDCG@10 | MRR | R@100 | p vs BM25 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.2511 | 0.2433 | 0.3136 | 0.4740 | 0.6662 | 1.0000 |
| QL-LM Dirichlet | 0.2393 | 0.2360 | 0.3024 | 0.4645 | 0.6576 | 0.0000 |
| Dense (LSA) | 0.2678 | 0.2473 | 0.3318 | 0.5478 | 0.6939 | 0.1729 |
| Hybrid RRF | 0.2890 | 0.2627 | 0.3514 | 0.5623 | 0.7187 | 0.0000 |
| Hybrid linear (alpha=0.3) | 0.2909 | 0.2693 | 0.3560 | 0.5616 | 0.7179 | 0.0000 |
| Bridge-PRF (ours, Cranfield defaults) | 0.2869 | 0.2680 | 0.3491 | 0.5350 | 0.7130 | 0.0000 |
