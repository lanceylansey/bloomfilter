# Distributed Bloomjoin

CPSC 4660 research prototype: reduce communication for an exact join between two
SQLite databases owned by separate Python processes. Workers exchange framed JSON
over loopback TCP; the joined result remains at the first site.

Python 3.10+ is sufficient. The experiment and tests use only the standard library.
Run commands from this directory; installation is optional.

```powershell
# One generated, verified query (full, fixed, bloom, or bloom-local).
python -m bloomjoin --strategy bloom --rows 10000 --overlap 0.1 --payload-bytes 32

# Skip the redundant remote filter build, with the same cost-selected dimensions.
python -m bloomjoin --strategy bloom-local --rows 10000 --overlap 0.8

# Fair comparison: same data, three measured repeats, one excluded warmup.
python -m bloomjoin.benchmark --compare --rows 10000 --overlap 0.1 --payload-bytes 128 --output results/comparison.json

# Simulate a 10 megabit/s application link, with all four methods.
python -m bloomjoin.benchmark --compare --rows 100000 --overlap 0.1 --bandwidth-mbps 10 --output results/network-comparison.json

# Proposal workloads: nine distinct cases, varying one factor at a time.
python -m bloomjoin.benchmark --suite --output results/proposal-suite.json

# All correctness and measurement checks.
python -m unittest discover -s tests -v
```

## CSV export and repeated scenarios

Every benchmark now saves three files: the complete JSON report, a CSV with one
row per measured query, and a `.summary.csv` with one row per scenario/method.
The terminal shows a compact table by default. To print the full JSON instead,
pass `--print-json`; the saved JSON remains available either way.

```powershell
# Five repeats of every method on one selected workload.
python -m bloomjoin.benchmark --compare --rows 100000 --overlap 0.1 --repeats 5 --warmups 1 --output results/comparison.json --csv results/comparison.csv

# Repeat 16 scenarios, checkpointing CSV and JSON after each completed scenario.
python -m bloomjoin.scenarios --repeats 5 --warmups 1
```

The repeated-study command covers the proposal's nine cases, simulated bandwidth
at 10/25/100 Mbps, high overlap and wide payloads on a simulated 10 Mbps link,
and two additional seeds (7 and 99). All four methods use five measured repeats
and one excluded, verified warmup by default: **320 measured queries and 64
warmups**. The million-row case runs last. Scenarios run sequentially to avoid
competing benchmark workloads; each query still uses a fresh remote process.

`python -m bloomjoin.scenarios` creates a fresh timestamped folder under
`results/scenarios/`. Pass `--output-dir results/my-study` to select a different
new folder. An existing folder is rejected to prevent mixing studies. Files are:

- `plan.json`: every scenario's settings and the repeat/warmup counts.
- `01-...json` through `16-...json`: individual scenario reports.
- `study.json`: combined report with completion status and scenario counts.
- `runs.csv`: every measured run, including configuration, seed, network setting,
  timings, byte/row counters, filter dimensions and SQL-verification status.
- `runs.summary.csv`: per-scenario/method means, medians, extrema, sample standard
  deviations, mean bytes, byte reduction and speedup relative to that case's full
  transfer. Different seeds/network settings are kept separate.

CSV columns use seconds, bytes and fractions, not formatted percentages. For
example, `0.85` in `byte_reduction_fraction` means 85% fewer bytes. Empty cells
mean missing/not applicable: unlimited bandwidth is blank, and an observed zero
false-positive rate remains numeric zero. A filtered-only benchmark has blank
relative savings/speedup because no full-transfer baseline was measured.

Warmups never enter either CSV. If a later scenario fails, completed scenarios
remain saved and `study.json` remains labeled `running`; it does not claim the
whole study completed. Simulated networks are labeled explicitly. A study can
take several minutes, especially with the million-row workload.

The [completed repeated study](docs/repeated-study.md) includes all 320 measured
runs, 64 summary rows, the scenario plan and an interpretation of faster and
slower cases. The CSV and raw JSON files are archived with that report.

## Commands and options

There are two experiment commands:

- `python -m bloomjoin` generates data and runs one selected method once.
- `python -m bloomjoin.benchmark` repeats a method, compares all methods with
  `--compare`, or runs the predefined workloads with `--suite`.

Options beginning with `--` are settings you type into the terminal. Fields such
as `query_seconds`, `application_bytes`, and `speedup` are results printed in the
JSON report; they are not additional commands or options.

| Option | What it controls | Default / availability |
| --- | --- | --- |
| `--rows 1000000` | Number of records in **each** table, not the combined total | `1000`; both commands |
| `--overlap 0.1` | Fraction of remote keys that match local keys; `0.1` = 10%, `0.8` = 80%, `1` = 100% | `0.1`; both commands |
| `--payload-bytes 32` | Payload bytes per record, excluding the key and message overhead | `32`; both commands |
| `--seed 42` | Random seed; equal generation settings and seed reproduce the same data | `42`; both commands |
| `--strategy bloom-local` | Select `full`, `fixed`, `bloom`, or `bloom-local` | `full`; both commands, for single-method runs |
| `--compare` | Compare all four methods against the same generated databases | Benchmark only |
| `--suite` | Run the predefined one-factor-at-a-time workload sweep | Benchmark only; cannot combine with `--compare` |
| `--repeats 3` | Number of measured runs **per method** | `3`; benchmark only |
| `--warmups 1` | Extra runs per method that are verified but excluded from measured results | `1`; benchmark only |
| `--bandwidth-mbps 10` | Simulated application bandwidth per direction, in megabits/s | Omitted = ordinary loopback; both commands |
| `--selectivity-estimate 0.1` | Matching fraction assumed by the cost-sizing formula | `0.0`; both commands; independent of actual overlap |
| `--collect-sizing` | Also exchange remote sizing statistics for `full` or `fixed` | Off; single-query command only |
| `--data-dir data` | Where the single-query command creates the two databases | `data`; single-query command only |
| `--output results/run.json` | File in which to save the JSON report | Single query: `results/baseline.json`; benchmark: `results/benchmark.json` |
| `--csv results/runs.csv` | Per-run CSV path; also writes `runs.summary.csv` | Benchmark only; defaults to the JSON basename with `.csv` |
| `--print-json` | Print full JSON instead of the compact terminal table | Benchmark only; off by default |
| `--help` | Print available command-line options | Both commands |

`--compare` and `--suite` select methods themselves, so `--strategy` does not
restrict those modes. The suite selects its own row counts, overlaps and payload
widths; use `--compare` when choosing those values yourself. An overlap that does
not give a whole number of shared keys is rounded down to whole records.

For example, this runs each method once as a warmup and three times for measurement
(16 queries total), using one million records per table and 100,000 shared keys:

```powershell
python -m bloomjoin.benchmark --compare --rows 1000000 --overlap 0.1 --payload-bytes 32 --repeats 3 --warmups 1 --output results/million-row-comparison.json
```

That command uses ordinary loopback. To use the simulated link, add
`--bandwidth-mbps 10`. To inspect available options directly:

```powershell
python -m bloomjoin --help
python -m bloomjoin.benchmark --help
```

`--suite` includes 10k/100k/1M rows, 0/1/10/50/100% overlap, and 32/128/512-byte
payloads around a 10k-row, 10%-overlap, 32-byte baseline. It takes longer than a
single comparison. Each method is independently verified against an exact SQL join.

| Method | Policy | Remote work |
| --- | --- | --- |
| `full` | Send every remote row | Scan and serialize |
| `fixed` | Ten bits per local key, rounded to bytes | Build compatible filter, AND, test rows |
| `bloom` | Section 4.1 transfer-cost-selected size | Measure widths/cardinality, build filter, AND, test rows |
| `bloom-local` | Same cost-selected size as `bloom` | Measure widths/cardinality, test received local filter directly |

The `fixed` and `bloom` methods send the local filter, build a compatible remote filter, AND
the bit arrays, send passing records, and perform the same exact SQL join. False
positives affect transfer volume, never the final answer. Empty local inputs
short-circuit filtered methods; cost sizing also detects empty remote inputs.
`bloom-local` skips the second build and AND while preserving the same candidate
records as `bloom`. Its remote construction time is zero; restoring and probing
the received filter still count toward query time. The longer strategy name adds
six application bytes to the request. When the cost model proposes zero bits,
both cost-selected methods fall back to full transfer. `--compare` and `--suite`
include all four methods.

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
The [local-filter comparison](docs/local-filter-evaluation.md) measures the
additional `bloom-local` variant against the original two-filter flow.
The [simulated-bandwidth evaluation](docs/bandwidth-evaluation.md) compares
10 Mbps and 100 Mbps with all four methods and documents the simulation model.

## Measurements and interpretation

The saved JSON report groups the settings under `configuration`, software versions
under `environment`, and measurement rules under `measurement`. In a comparison,
`methods` contains each method's individual `runs` and summaries. A single-method
benchmark places `runs` and its summaries directly in the report instead.

| Result field | How to read it |
| --- | --- |
| `repeat` | Which measured repetition this is; warmups are not in this list |
| `strategy` | Requested method: `full`, `fixed`, `bloom`, or `bloom-local` |
| `execution_strategy` | Worker operation actually used; `fixed` uses the `bloom` handler, while bypass and empty cases use `full` or `empty` |
| `application_bytes` | All exchanged application bytes, including message framing and filter encoding |
| `query_seconds` | Elapsed query time, including scans, filtering, transmission, candidate loading and exact joining |
| `filter_build_seconds` | Local build plus remote build/AND time; **already included in query time**, so do not add it again |
| `local_filter_build_seconds` | Construction time at the first site |
| `remote_filter_build_seconds` | Construction/AND time at the remote site; zero for `bloom-local` |
| `filter_bytes` | Packed filter size before base64 encoding and message overhead |
| `filter_applied` | Whether a Bloom filter was actually used |
| `remote_records` | Original remote table cardinality |
| `transferred_records` | Remote candidate rows sent to the first site |
| `rejected_records` | Remote rows prevented from being transferred |
| `nonmatching_records` | Transferred rows discarded by the exact join; these are false positives when a filter was applied |
| `result_rows` | Number of true matching records returned by the exact join |
| `observed_false_positive_rate` | Nonmatching transferred rows divided by all remote nonmatches; null if no filter was used or there were no negative probes |
| `verified` | True only after complete results match the reference SQL join |
| `mean_application_bytes` | Average application bytes across measured runs |
| `byte_reduction_fraction` | `1 - method_bytes / full_transfer_bytes`; `0.8569` means about 85.69% fewer bytes |
| `speedup` | `full_transfer_mean_time / method_mean_time`; above 1 is faster, below 1 is slower |

The `sizing` object explains filter dimensions and their inputs:

| Sizing field | Meaning |
| --- | --- |
| `local_count` | Number of local keys available to insert into the filter |
| `row_count` | Remote row count returned by the statistics exchange |
| `mean_row_bytes` | Estimated serialized remote-row width, including key, escaped payload and a separator; wider than payload alone |
| `selectivity_estimate` | Expected matching fraction supplied to the formula; this is not the measured overlap |
| `bit_count` | Number of bits allocated for the filter |
| `hash_count` | Number of bit positions generated per key |
| `metadata_application_bytes` | Framed bytes used to request and return sizing statistics |
| `filter_applied` | Whether the proposed dimensions were actually used for filtering |

Some sizing fields are absent when statistics are not collected. For example,
`fixed` needs only the local count. `selectivity_estimate: 0.0` with actual overlap
`0.1` means the sizing formula assumes no matches while the generated data has
10% overlap. This deliberately keeps the optimizer's assumption separate from
the ground truth.

`timing_seconds` summarizes query/build time across measured repetitions:
`mean` is the average, `median` is the middle observation, `min`/`max` are the
extremes, and `stdev` is the sample standard deviation (variation between runs).
For a single measured run, standard deviation is reported as zero.

For example, in the pasted million-row unthrottled run, `bloom-local` transferred
105,267 records: 100,000 true matches plus 5,267 false positives. Its observed
false-positive rate was `5267 / 900000`, about 0.585%. It exchanged 6.43 MB versus
44.90 MB for full transfer, saving about 85.7% of application bytes. Its mean time
was 11.49 s versus 1.79 s, so `speedup: 0.156` means roughly 6.4 times as long.
MB here uses decimal units (one million bytes); your timings may vary.

`--bandwidth-mbps` is optional for both `python -m bloomjoin` and
`python -m bloomjoin.benchmark` (including comparison/suite modes). Omit it for
normal loopback. It accepts rates of at least 0.001 **megabits per second**;
10 Mbps corresponds to 1.25 million application bytes/s per direction.

This is an application-level simulation on loopback. Each sender paces small
chunks against a clock, charging the framed JSON bytes once, including metadata,
filters and completion messages. Query time includes the delay and processing;
filter construction time does not include the delay. The model provides a
per-direction transmission budget and does not simulate RTT, packet loss, TCP
headers, congestion or a shared half-duplex link. Scheduling and processing can
make effective throughput lower than the configured rate. It changes no OS or
internet settings. Reports explicitly label simulation and record the rate.

For a larger run, use `--rows 1000000` with the same flags. Larger payloads and
lower overlap may favor filtering; complete overlap still adds filter overhead.
Keep all methods on identical settings and report slower cases too.

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
