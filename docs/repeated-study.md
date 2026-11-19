# Repeated scenario study

Completed 16 scenarios using all four methods, with five measured repeats
and one verified excluded warmup per method/scenario: **320 measured queries
and 64 warmups**. All results matched the exact reference SQL join.

[Summary CSV: 64 rows](measurements/repeated-study/runs.summary.csv) |
[Individual measurements: 320 rows](measurements/repeated-study/runs.csv) |
[Complete JSON](measurements/repeated-study/study.json) |
[Scenario plan](measurements/repeated-study/plan.json)

CSV row counts, query times, sample standard deviations, speedups and byte
reductions were independently checked against the JSON measurements.
All 46 unit/integration tests passed. No runtime dependencies were added.

## Workloads and results

Times below are means in seconds. Detailed variation and every individual
measurement are retained in the CSV/JSON files. MB uses decimal bytes.
All cases use a selectivity estimate of zero, independent of actual overlap.

| Scenario | Rows/site | Overlap | Payload B | Network | Full s | Fixed s | Bloom s | Local s | Local bytes saved | Local speedup |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline-10k | 10,000 | 10% | 32 | loopback | 0.0178 | 0.1256 | 0.1570 | 0.1148 | 85.5% | 0.15x |
| size-100k | 100,000 | 10% | 32 | loopback | 0.1725 | 1.2629 | 1.5925 | 1.1333 | 85.6% | 0.15x |
| overlap-0pct | 10,000 | 0% | 32 | loopback | 0.0172 | 0.1201 | 0.1552 | 0.1125 | 95.2% | 0.15x |
| overlap-1pct | 10,000 | 1% | 32 | loopback | 0.0170 | 0.1199 | 0.1547 | 0.1091 | 94.3% | 0.16x |
| overlap-50pct | 10,000 | 50% | 32 | loopback | 0.0204 | 0.1349 | 0.1666 | 0.1224 | 46.0% | 0.17x |
| overlap-100pct | 10,000 | 100% | 32 | loopback | 0.0245 | 0.1464 | 0.1833 | 0.1369 | -4.2% | 0.18x |
| payload-128 | 10,000 | 10% | 128 | loopback | 0.0237 | 0.1295 | 0.1774 | 0.1264 | 88.3% | 0.19x |
| payload-512 | 10,000 | 10% | 512 | loopback | 0.0811 | 0.1863 | 0.2809 | 0.2144 | 89.5% | 0.38x |
| network-10mbps | 100,000 | 10% | 32 | simulated 10 Mbps | 3.7324 | 1.8293 | 2.1937 | 1.6974 | 85.6% | 2.20x |
| network-25mbps | 100,000 | 10% | 32 | simulated 25 Mbps | 1.6359 | 1.5016 | 1.8395 | 1.3990 | 85.6% | 1.17x |
| network-100mbps | 100,000 | 10% | 32 | simulated 100 Mbps | 0.5477 | 1.3615 | 1.7145 | 1.2656 | 85.6% | 0.43x |
| network-high-overlap | 100,000 | 80% | 32 | simulated 10 Mbps | 3.7144 | 4.3951 | 4.7196 | 4.2807 | 16.2% | 0.87x |
| network-wide-payload | 10,000 | 10% | 512 | simulated 10 Mbps | 4.2664 | 0.6671 | 0.7333 | 0.6582 | 89.5% | 6.48x |
| seed-7 | 100,000 | 10% | 32 | loopback | 0.1709 | 1.2511 | 1.6129 | 1.1254 | 85.6% | 0.15x |
| seed-99 | 100,000 | 10% | 32 | loopback | 0.1710 | 1.2382 | 1.5794 | 1.1351 | 85.6% | 0.15x |
| size-1m | 1,000,000 | 10% | 32 | loopback | 1.8065 | 12.6425 | 15.9589 | 11.5025 | 85.7% | 0.16x |

## Findings

- **network-10mbps:** full transfer 3.732 s; bloom-local 1.697 s; 2.20x speedup and 85.6% fewer bytes.
- **network-25mbps:** full transfer 1.636 s; bloom-local 1.399 s; 1.17x speedup and 85.6% fewer bytes.
- **network-100mbps:** full transfer 0.548 s; bloom-local 1.266 s; 0.43x speedup and 85.6% fewer bytes.
- **network-high-overlap:** full transfer 3.714 s; bloom-local 4.281 s; 0.87x speedup and 16.2% fewer bytes.
- **network-wide-payload:** full transfer 4.266 s; bloom-local 0.658 s; 6.48x speedup and 89.5% fewer bytes.
- **Million-row loopback:** bloom-local used 6.43 MB versus 44.90 MB for full transfer; CPU work still made filtering slower.
- Full-overlap filtering increased communication, because a filter cannot
  discard matching records. That unfavorable case is retained in the results.
- Seeds 7, 42 and 99 were compared at 100k rows, 10% overlap and 32-byte
  payloads on loopback. This is a limited seed check within this generator,
  not coverage of arbitrary data distributions or key skew.
- Both cost-selected variants transferred identical candidate counts and
  returned identical SQL results in every case. The local-filter request is
  six bytes longer; its improvement comes from skipping the remote build/AND.

## Methodology and limits

Scenarios ran sequentially. Each method used the same databases within a
scenario; execution order rotated between rounds. Each query used a fresh
remote process. Warmups were checked but excluded from both CSVs and summaries.
An initial 20-row CLI/export smoke check overlapped the 100k case warmup,
before that case's measured rounds. Remaining benchmark cases ran without
another benchmark workload launched by this session.
Process startup, generation and reference validation are excluded from query
time; filtering, serialization, sockets and the exact SQL join are included.
OS caches and scheduling can still affect timings.

Simulated links pace outgoing application frames in each direction. These
are loopback experiments with imposed transmission delay, not real WAN
measurements. They do not model RTT, packet loss, TCP headers or congestion.
Five repeats describe observed variation; no statistical-significance or
universal performance claim is made. Comparisons are kept within each case;
do not attribute differences between cases with different row counts and
payload widths to one factor alone.

## Reproduce

```powershell
python -m bloomjoin.scenarios --repeats 5 --warmups 1
```

A fresh timestamped folder is created under `results/scenarios`. For one
chosen scenario and explicit CSV filenames:

```powershell
python -m bloomjoin.benchmark --compare --rows 100000 --overlap 0.1 --bandwidth-mbps 10 --repeats 5 --warmups 1 --output results/comparison.json --csv results/comparison.csv
```
