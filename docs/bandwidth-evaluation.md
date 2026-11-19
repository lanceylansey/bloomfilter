# Simulated bandwidth evaluation

Workload: 100,000 rows per site, 10% overlap, 32-byte payloads, seed 42.
Each rate uses three measured repeats and one excluded warmup per method,
with the same databases for all methods and rotating execution order.
The 10 Mbps and 100 Mbps comparisons were run sequentially.

**These are simulated application-bandwidth conditions on loopback TCP.**
They are not measurements from a real remote network.

| Simulated Mbps | Method | Mean query s | Sample stdev s | Application bytes | Speedup over full |
| ---: | --- | ---: | ---: | ---: | ---: |
| 10 | full | 3.7286 | 0.0050 | 4,390,490 | 1.00x |
| 10 | fixed | 1.9252 | 0.0195 | 628,622 | 1.94x |
| 10 | bloom | 2.2690 | 0.0309 | 632,613 | 1.64x |
| 10 | bloom-local | 1.8042 | 0.0071 | 632,619 | 2.07x |
| 100 | full | 0.5548 | 0.0050 | 4,390,490 | 1.00x |
| 100 | fixed | 1.4828 | 0.0064 | 628,622 | 0.37x |
| 100 | bloom | 1.8370 | 0.0228 | 632,613 | 0.30x |
| 100 | bloom-local | 1.3607 | 0.0038 | 632,619 | 0.41x |

## Interpretation

At 10 Mbps, the reduction in application bytes offsets filtering costs:
bloom-local averages about 2.1x faster than full transfer. At 100 Mbps,
full transfer is faster. This illustrates the tradeoff instead of assuming
a larger row count guarantees an elapsed-time advantage.

Each sender delays writing chunks against framed-byte/rate deadlines.
The receiver does not add another delay. Metadata, filters, rows, framing
and completion telemetry are all charged once. Rate is per direction;
10 Mbps means 1.25 million application bytes/s per direction. Delays are
inside query time and outside filter-build intervals. Default operation
has no artificial delay. Byte counts and exact SQL results are unchanged.

This models application serialization time on the link, not RTT, packet
loss, TCP headers, congestion or half-duplex sharing. Processing and OS
scheduling can lower achieved throughput. Per-frame pacing permits some
natural overlap between receiving/processing and the next outgoing frame.
The setting makes no changes to the operating system or actual internet
connection. Report results as simulated and retain unthrottled results.

## Verification

All 40 tests passed, including deterministic fake-clock pacing checks,
unchanged frame accounting, invalid-rate rejection, real spawned-worker
rate propagation, default unlimited behavior and exact SQL verification.
All 24 measured benchmark runs passed reference validation; eight warmups
were also verified. The single-query CLI passed a simulated-rate smoke test.

## Commands

```powershell
python -m bloomjoin.benchmark --compare --rows 100000 --overlap 0.1 --bandwidth-mbps 10 --output results/network-comparison.json
python -m bloomjoin.benchmark --compare --rows 100000 --overlap 0.1 --bandwidth-mbps 100 --output results/faster-network-comparison.json
```

Use `--rows 1000000` to repeat with one million rows per site. The same
option is supported by the single-query CLI and the complete suite.

Raw reports: [10 Mbps](measurements/bandwidth-10mbps.json) and
[100 Mbps](measurements/bandwidth-100mbps.json).
