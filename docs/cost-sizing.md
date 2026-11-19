# Cost-selected filter size

The existing formula is an adaptation of Section 4.1, equation (4), in Ramesh,
Papapetrou and Siberski, *Optimizing Distributed Joins with Bloom Filters* (2008).
[Author-hosted paper](https://opapapetrou.win.tue.nl/papers/icdcit08-djoins.pdf).

Let n be inserted local keys, R remote rows, a the estimated fraction of remote
rows with a match, w the mean serialized remote-row width in **bytes**, and m the
filter length in **bits**. With the optimal continuous hash count
`k = (m/n) ln(2)`, approximate false-positive probability is
`p = exp(-m (ln(2))^2 / n)`.

Ignoring terms independent of m, expected transfer in bits is:

```
C(m) = m + 8 R w [a + (1-a) exp(-m (ln(2))^2 / n)]
m*   = n / (ln(2))^2 * ln(8 R w (1-a) (ln(2))^2 / n)
```

The paper uses equal cardinalities. Keeping n and R separate generalizes its
expression. Results stay at the first site, so no user-site result shipment is
measured. The logarithm is evaluated as sums/differences to avoid intermediate
overflow on large counts.

If either input is empty, a is one, or the logarithm is nonpositive, choose
`FilterSize(0, 0)`. The runner distinguishes an empty join from full-transfer
fallback. Otherwise round m upward to whole bytes, impose an 8 MiB packed cap,
and round k to the nearest integer with bounds 1..32. With n=R=100,
w=32 and a=0, the continuous 1001.617... bits become 1008 bits and seven hashes.

`fixed_filter_size` uses ten bits per local key, rounded upward to whole bytes,
the same cap, and the same hash-count rounding. Small/capped cases can depart
from precisely ten bits per key.

The width estimate scans remote rows through the same JSON serializer used for
transport, including key digits, escapes, and one separator per row. It excludes
batch envelopes and frame prefixes. Actual byte counters include them, plus
base64 expansion, metadata, configuration, and completion telemetry. Construction
time is measured but is not optimized by this transfer-only formula. Therefore
cost-selected means **model-selected**, not guaranteed minimum actual bytes or
minimum elapsed time. Full overlap with the default a=0 can spend extra bytes on
a filter that cannot reject any rows.

Generated overlap never secretly becomes the optimizer's selectivity estimate.
Use `--selectivity-estimate` for a stated estimate and retain it in the report.
