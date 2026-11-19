# Local-filter comparison

The new `bloom-local` strategy uses the same cost-selected filter as `bloom`,
but the remote process probes that received filter directly. The existing
`bloom` method remains the control with its second build and bitwise AND.

Each workload uses 100,000 rows per site, 32-byte payloads, seed 42, a zero
selectivity estimate, three measured repeats and one excluded verified warmup.
All four strategies run on the same databases, with rotating execution order.
Reports were run sequentially to avoid competing benchmark workloads.

| Overlap | Method | Mean query s | Sample stdev s | Mean filter build s | Candidate rows | Application bytes |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 10% | full | 0.1822 | 0.0142 | 0.0000 | 100,000 | 4,390,490 |
| 10% | fixed | 1.2625 | 0.0498 | 0.8981 | 10,714 | 628,622 |
| 10% | bloom | 1.6501 | 0.0978 | 0.9294 | 10,548 | 632,613 |
| 10% | bloom-local | 1.1642 | 0.0189 | 0.4458 | 10,548 | 632,619 |
| 80% | full | 0.2182 | 0.0043 | 0.0000 | 100,000 | 4,312,673 |
| 80% | fixed | 1.5541 | 0.0340 | 1.0067 | 80,162 | 3,606,517 |
| 80% | bloom | 1.9168 | 0.0537 | 1.0473 | 80,115 | 3,615,138 |
| 80% | bloom-local | 1.4295 | 0.0120 | 0.5573 | 80,115 | 3,615,144 |

## Findings

- At 10% overlap, mean query time fell from 1.6501 s to 1.1642 s (29.4% lower elapsed time, 1.42x speedup over the two-filter method).
- At 80% overlap, mean query time fell from 1.9168 s to 1.4295 s (25.4% lower elapsed time, 1.34x speedup over the two-filter method).
- Both variants transferred identical candidate counts and returned identical
  exact SQL results. Unit tests additionally compare complete candidate rows,
  including deliberately induced false positives.
- `bloom-local` reports zero remote construction time because it skips that
  build/AND. Restoring, probing and serializing remain inside query time.
- Application bytes increase by exactly six because `bloom-local` is six
  characters longer than `bloom` in the request. Filter payloads and row
  messages are otherwise identical; this optimization targets computation.
- The optimized variant is still slower than full transfer on loopback.
  These timings describe this machine and these workloads; they do not
  establish performance on a remote network or every possible distribution.

## Validation and reproduction

All 35 tests passed. All 24 measured runs and eight excluded warmups passed
the reference SQL check. Regression coverage includes empty inputs, no overlap,
partial/full overlap, cost-model bypass and identical candidate selection.

```powershell
python -m unittest discover -s tests -v
python -m bloomjoin.benchmark --compare --rows 100000 --overlap 0.1 --repeats 3 --warmups 1 --output results/local-filter-10pct.json
python -m bloomjoin.benchmark --compare --rows 100000 --overlap 0.8 --repeats 3 --warmups 1 --output results/local-filter-80pct.json
```

Raw reports: [10% overlap](measurements/local-filter-10pct.json),
[80% overlap](measurements/local-filter-80pct.json). Each includes environment,
all individual measurements, timing summaries and comparison ratios.
