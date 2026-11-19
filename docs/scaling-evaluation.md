# Million-row comparison

Measured on 2026-11-18 with 1,000,000 rows per site, 10% overlap,
32-byte payloads, seed 42, three measured repeats and one excluded
verified warmup per method. All four methods use the same databases,
with rotating execution order. All 12 measured results passed exact SQL validation.

| Method | Application bytes | Mean query seconds | Sample stdev seconds | Candidate rows |
| --- | ---: | ---: | ---: | ---: |
| full | 44,902,984 | 1.8173 | 0.0127 | 1,000,000 |
| fixed | 6,401,129 | 13.4613 | 0.5094 | 107,366 |
| bloom | 6,426,813 | 16.7217 | 0.4087 | 105,267 |
| bloom-local | 6,426,819 | 11.7152 | 0.1667 | 105,267 |

The local-filter variant reduced elapsed time by 29.9% relative to
the two-filter Bloom method while transferring identical candidate rows.
Compared with full transfer, it saved 38,476,165 application bytes (85.7%).
The final result contained exactly 100,000 rows for every method.

Increasing from 100k to 1M rows increases absolute transfer savings;
it does not eliminate the extra hashing and width-scan costs. On fast
loopback networking, full transfer remains fastest. The next useful
experiment is controlled bandwidth/latency with the same workload and
methods, explicitly labeling simulation if used. This run does not
measure or establish a speedup on a remote network.

[Raw measurements and environment](measurements/local-filter-1m.json).

```powershell
python -m bloomjoin.benchmark --compare --rows 1000000 --overlap 0.1 --payload-bytes 32 --repeats 3 --warmups 1 --output results/million-row-comparison.json
```
