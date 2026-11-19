# Distributed Bloomjoin

CPSC 4660 research prototype: reduce communication for an exact join between two
SQLite databases owned by separate Python processes. Workers exchange framed JSON
over loopback TCP; the joined result remains at the first site.

Python 3.10+ is sufficient. The experiment and tests use only the standard library.
Run commands from this directory; installation is optional.

```powershell
# One generated, verified query (full, fixed, or bloom).
python -m bloomjoin --strategy bloom --rows 10000 --overlap 0.1 --payload-bytes 32

# Fair comparison: same data, three measured repeats, one excluded warmup.
python -m bloomjoin.benchmark --compare --rows 10000 --overlap 0.1 --payload-bytes 128 --output results/comparison.json

# Proposal workloads: nine distinct cases, varying one factor at a time.
python -m bloomjoin.benchmark --suite --output results/proposal-suite.json

# All correctness and measurement checks.
python -m unittest discover -s tests -v
```

`--suite` includes 10k/100k/1M rows, 0/1/10/50/100% overlap, and 32/128/512-byte
payloads around a 10k-row, 10%-overlap, 32-byte baseline. It takes longer than a
single comparison. Each method is independently verified against an exact SQL join.

| Method | Policy | Remote work |
| --- | --- | --- |
| `full` | Send every remote row | Scan and serialize |
| `fixed` | Ten bits per local key, rounded to bytes | Build compatible filter, AND, test rows |
| `bloom` | Section 4.1 transfer-cost-selected size | Measure widths/cardinality, build filter, AND, test rows |

Both Bloom methods send the local filter, build a compatible remote filter, AND
the bit arrays, send passing records, and perform the same exact SQL join. False
positives affect transfer volume, never the final answer. Empty local inputs
short-circuit filtered methods; cost sizing also detects empty remote inputs.
When the cost model proposes zero bits, `bloom` falls back to full transfer.

`--selectivity-estimate` is an explicit cost-model estimate, defaulting to zero.
It is independent of `--overlap`, which controls generated ground truth. For
example, use `--selectivity-estimate 1` to test the no-filter fallback. A default
estimate of zero deliberately does not give the optimizer advance knowledge of
the generated overlap. `--collect-sizing` optionally measures metadata for
`full` or `fixed` without changing the selected policy.

The single-query command replaces `records` in `data/local.sqlite` and
`data/remote.sqlite` (or `--data-dir`). Benchmark commands use temporary databases.
JSON reports go to `results/` unless `--output` is supplied.

Read [the repository review](docs/repository-review.md),
[the function-by-function code notes](docs/code-notes.md),
[the cost model](docs/cost-sizing.md), and
[public-project comparisons](docs/references.md).
The [measured evaluation](docs/evaluation.md) includes the full proposal sweep
and its raw report.

## Measurements and interpretation

- `application_bytes` includes configuration, metadata, base64 filters, records,
  completion telemetry, and four-byte frame prefixes, in both directions counted
  once. It excludes TCP/IP headers and the local reference join.
- `query_seconds` includes cardinality/width scans, filter construction and AND,
  hashing/probing, serialization, sockets, candidate loading, and exact joining.
  Data generation, worker startup, connection setup, and validation are excluded.
- `filter_build_seconds` sums local construction and remote construction/AND;
  it is already inside query time. Separate local/remote intervals are also saved.
- `nonmatching_records` counts transferred false positives when filtering is
  applied. `observed_false_positive_rate` divides them by remote nonmatches;
  it is null when no filter was applied or no negative probes exist.
- Comparison reports retain every measured run, timing mean/median/min/max/sample
  deviation, byte reduction relative to `full`, and elapsed-time speedup.
  Negative byte reduction or speedup below one indicates a worse result.

Less communication does not guarantee less elapsed time. Loopback is fast and
Python hashing adds CPU work; report observed timings without extrapolating to a
WAN. The proposal's second filter/AND adds no pruning for remote keys already
inserted into that filter; see the proof and improvement options in the review.

This is a two-site experiment with unique, non-null integer keys and text payloads,
not a general SQL engine. Inputs should remain unchanged during a query. Workers
stream candidates in batches of 1,000; final/reference results are materialized.
Filters are capped at 8 MiB and frames at 16 MiB. No external source code was
vendored; the original dependency-free implementation remains inspectable.
