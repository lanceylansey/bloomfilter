# Measured evaluation

Run on 2026-11-18 using seed 42, three measured repeats and one verified
excluded warmup per method/case. All 81 measured queries passed exact SQL
validation; 27 warmups were also verified. Strategy order rotates each round.

[Raw JSON with all runs, variance and environment](measurements/proposal-suite.json).

Environment: Python 3.13.1, SQLite 3.45.3.
Transport: local loopback TCP. The selectivity estimate was zero throughout,
independently of actual generated overlap. Sizes below include every application
frame and both directions, counted once; network packet headers are excluded.

| Rows/site | Overlap | Payload B | Method | Application B | Reduction | Mean query s | Sample stdev s |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 10,000 | 10% | 32 | full | 429,148 | 0.00% | 0.0183 | 0.0009 |
| 10,000 | 10% | 32 | fixed | 62,389 | 85.46% | 0.1445 | 0.0214 |
| 10,000 | 10% | 32 | bloom | 62,269 | 85.49% | 0.1788 | 0.0166 |
| 100,000 | 10% | 32 | full | 4,390,490 | 0.00% | 0.1998 | 0.0121 |
| 100,000 | 10% | 32 | fixed | 628,622 | 85.68% | 1.5584 | 0.1264 |
| 100,000 | 10% | 32 | bloom | 632,613 | 85.59% | 1.8451 | 0.0777 |
| 1,000,000 | 10% | 32 | full | 44,902,984 | 0.00% | 2.0082 | 0.0348 |
| 1,000,000 | 10% | 32 | fixed | 6,401,129 | 85.74% | 14.1368 | 0.8968 |
| 1,000,000 | 10% | 32 | bloom | 6,426,813 | 85.69% | 18.6205 | 0.6161 |
| 10,000 | 0% | 32 | full | 430,253 | 0.00% | 0.0191 | 0.0022 |
| 10,000 | 0% | 32 | fixed | 20,924 | 95.14% | 0.1384 | 0.0097 |
| 10,000 | 0% | 32 | bloom | 20,723 | 95.18% | 0.1790 | 0.0135 |
| 10,000 | 1% | 32 | full | 430,144 | 0.00% | 0.0183 | 0.0002 |
| 10,000 | 1% | 32 | fixed | 25,029 | 94.18% | 0.1307 | 0.0070 |
| 10,000 | 1% | 32 | bloom | 24,530 | 94.30% | 0.1657 | 0.0051 |
| 10,000 | 50% | 32 | full | 424,725 | 0.00% | 0.0223 | 0.0013 |
| 10,000 | 50% | 32 | fixed | 228,461 | 46.21% | 0.1442 | 0.0011 |
| 10,000 | 50% | 32 | bloom | 229,165 | 46.04% | 0.1811 | 0.0134 |
| 10,000 | 100% | 32 | full | 419,143 | 0.00% | 0.0295 | 0.0041 |
| 10,000 | 100% | 32 | fixed | 435,858 | -3.99% | 0.1687 | 0.0056 |
| 10,000 | 100% | 32 | bloom | 436,900 | -4.24% | 0.2131 | 0.0097 |
| 10,000 | 10% | 128 | full | 1,389,148 | 0.00% | 0.0275 | 0.0017 |
| 10,000 | 10% | 128 | fixed | 166,261 | 88.03% | 0.1423 | 0.0079 |
| 10,000 | 10% | 128 | bloom | 161,846 | 88.35% | 0.1926 | 0.0058 |
| 10,000 | 10% | 512 | full | 5,229,148 | 0.00% | 0.0836 | 0.0015 |
| 10,000 | 10% | 512 | fixed | 581,749 | 88.87% | 0.2100 | 0.0198 |
| 10,000 | 10% | 512 | bloom | 550,690 | 89.47% | 0.3066 | 0.0124 |

## Findings

- At one million rows and 10% overlap, the cost-selected method reduced bytes
  by 85.69% (44,902,984 to 6,426,813), while mean query time rose from
  2.0082 s to 18.6205 s. Communication improved; loopback execution slowed.
- At 10k rows and no overlap, cost-selected filtering reduced bytes by 95.18%.
- At full overlap, cost-selected filtering increased bytes by 4.24%; with the
  intentionally uninformed zero selectivity estimate it still built a filter.
- Larger payloads improved savings: at 10k rows/10% overlap/512 bytes,
  cost-selected filtering saved 89.47% versus 85.49% with 32-byte payloads.
- The continuous cost model did not always beat fixed sizing: at 100k and 1M
  rows the fixed policy used slightly fewer application bytes. Base64, batch
  envelopes, hash rounding and realized false positives are outside that model.
- Every Bloom case was slower than full transfer on this loopback setup.
  Both-site construction, Python hashing and the cost-policy width scan are
  included in timing. The second filter/AND gives no extra remote pruning.

## Interpretation and limits

These results support reduced communication for selective joins, not a blanket
runtime speedup. The final operation remains a relational SQL join. A slower or
higher-latency network could change the runtime tradeoff, but this run does not
measure one. Repeat under controlled network conditions before making that claim.
One seed and three repeats describe this machine and workload, not a statistical
guarantee across data distributions. Process startup and reference validation are
outside query timing; OS caches can persist despite each run using a new worker.

Reproduce:

```powershell
python -m bloomjoin.benchmark --suite --seed 42 --repeats 3 --warmups 1 --output results/proposal-suite.json
```
