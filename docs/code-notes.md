# Code reading notes

Every source function and test function has a purpose docstring. Inline comments
explain the consequential lines: deterministic hashing, bit operations, metadata
accounting, width conversion, streaming, timing boundaries and process cleanup.
This guide follows execution order and explains the surrounding statements.

## Package and entry points

`bloomjoin/__init__.py` identifies the package; importing it starts no processes.
`pyproject.toml` declares Python >=3.10 and no runtime dependencies. `.gitignore`
keeps generated databases, measurements, bytecode and temporary tools out of Git.

`__main__.main` parses sizes, overlap, seed, strategy and an independent selectivity
estimate. It generates both databases, calls `run`, records the generation settings,
creates the output directory, and writes UTF-8 JSON. The `if __name__` guard is
required for safe multiprocessing spawn, particularly on Windows. The benchmark
module uses the same guard for its CLI.

## Data generation: `data.generate`

Validation rejects negative sizes, non-integer row/payload sizes, booleans and
out-of-range overlap. `Path.mkdir` prepares the destination. A private seeded RNG
avoids dependence on global random state. `shared = int(rows * overlap)` determines
the exact intersection cardinality. Local keys occupy `[0, rows)`; remote keys
combine a sample of that range with distinct values above it. Each list is shuffled
reproducibly. SQLite integer primary keys guarantee uniqueness and non-null keys.
`closing` releases the connection, and `with db` commits the inserts. Existing
records tables are deliberately replaced. Repeated ASCII payload characters make
the requested width equal to UTF-8 payload bytes. Returned paths identify the
two independent sites; database pages need not retain shuffled insertion order.

## Framing: `protocol.py`

- `encode_json`: compact separators produce deterministic application payloads;
  default JSON escaping is also used in the width estimator.
- `Channel.__init__`: retain the socket and initialize separate direction counters.
- `Channel.send`: serialize, enforce the body limit, prepend a big-endian unsigned
  four-byte length, `sendall`, then count the complete packet.
- `Channel._read`: TCP can split a frame arbitrarily, so loop until the requested
  length is available. Empty `recv` signals premature EOF. Count complete reads.
- `Channel.receive`: read the length, reject excessive bodies before allocation,
  read the complete body, decode UTF-8, and parse JSON. Malformed input raises.

Only one endpoint's sent-plus-received count is reported; adding both endpoints
would count every frame twice. The protocol is a trusted loopback experiment,
without authentication, schema negotiation or encryption.

## Filters and policies: `strategies.py`

- `FilterSize`: named tuple for bit/hash dimensions. Zero dimensions mean bypass,
  and are never passed to an allocated filter.
- `BloomFilter.__init__`: check integer dimensions and allocation/hash limits;
  round bits upward to bytes; allocate zeros or copy an exactly sized payload.
- `BloomFilter._positions`: encode the integer as stable UTF-8 text; SHA-256
  supplies two 64-bit components. Use a nonzero step and yield
  `(h1 + i*h2) % bit_count`. Lazy generation lets negative probes stop early.
  Python's randomized built-in hash would break worker compatibility.
- `BloomFilter.add`: byte index is `p // 8`, bit offset is `p % 8`; OR a one-bit
  mask into every selected position. Duplicate additions leave the same bits.
- `BloomFilter.might_contain`: return false as soon as any selected bit is zero;
  otherwise return true. True requires later exact verification.
- `BloomFilter.to_bytes`: return an immutable copy of packed storage.
- `BloomFilter.from_bytes`: delegate restoration and dimensional validation to
  the constructor. Hashing is fixed by the implementation rather than serialized.
- `BloomFilter.intersection`: require equal dimensions, AND corresponding bytes,
  return a separate compatible filter, and preserve both original arrays.
- `fixed_filter_size`: validate the local count, bypass empty inputs, allocate
  ten bits per local key rounded to bytes/capped, then choose rounded optimal k.
- `choose_filter_size`: validate counts, finite width and selectivity; bypass
  empty/no-benefit cases; evaluate the continuous cost optimum in log space;
  cap before multiplying large n; byte-align and choose bounded rounded k.
  [The derivation](cost-sizing.md) explains each logarithm and unit conversion.

## Coordinator: `experiment.py`

`reference_join` attaches the remote database locally, selects the same key and
two payload columns, and orders by key. This is validation after measurement.

`run` performs these steps:

1. Validate strategy, selectivity estimate and input file existence. Select spawn
   explicitly so each worker opens its own SQLite connection.
2. Bind a loopback listener to an OS-selected free port, launch `serve` with the
   remote path/address, accept its connection, and apply socket timeouts.
3. Open the local database and create a temporary candidate table with the same
   uniqueness assumptions as generated inputs. Start query timing.
4. Count local rows. For cost selection or explicit metadata collection, exchange
   sizing messages and calculate their byte contribution as a counter delta.
   Estimate dimensions using remote count/width and the supplied selectivity.
5. Override dimensions with the fixed policy for `fixed`. Initialize a full
   request and zero construction counters. Known-empty filtered inputs use the
   empty request; zero-cost-model dimensions otherwise leave full fallback.
6. If filtering applies, build from local keys, copy packed bits, end local build
   timing, base64 encode, and send dimensions/data as a Bloom request. Record
   packed bytes separately from the larger complete wire message.
7. Receive row batches into the temporary SQLite table and count candidates.
   Completion supplies remote cardinality and construction time. Fixed-width
   timing text prevents timer precision/jitter changing wire byte counts.
8. Execute `PROJECTION`, materialize ordered results, stop query timing, and
   assemble counters. False-positive rate uses only negative remote probes and
   is null when it has no meaningful denominator or no filter was applied.
9. Join the worker, check its exit status, and terminate/join on failure in
   `finally`. Close sockets/SQLite via context managers.
10. Compare complete ordered results to `reference_join`; mark verified only
    after exact equality. Incorrect results cannot enter a benchmark silently.

## Remote process: `worker.py`

`sizing_statistics` scans rows without keeping them all, serializes each row using
the actual JSON encoder, and adds a separator byte. It returns count and mean
width (zero for empty input). Actual message counters separately include envelopes.

`serve` connects back to the coordinator and opens the remote database itself.
It optionally responds to sizing before reading the strategy. Full transfer uses
no candidate filter; empty sends completion without candidate rows. Bloom restores
the local filter, builds a compatible remote filter, ANDs them, and times the
remote construction/AND interval. Unknown strategies fail explicitly. A cursor
fetches up to 1,000 ordered rows at a time; optional membership tests remove
definite misses; empty filtered batches are skipped. The final message reports
completion, original row count and build time. No joined result travels back.

## Benchmarking: `benchmark.py`

- `summarize`: reject no measured samples; summarize each timing with mean,
  median, extremes and sample standard deviation (zero for one sample).
- `benchmark`: generate once in a temporary directory, run warmups/repeats of
  one method, reject unverified runs, retain measured repetitions, and include
  configuration/environment/methodology in the report.
- `compare`: generate one dataset for every method, rotate starting strategy
  each round, independently verify warmups and measurements, and retain results
  by method. Divide mean bytes and time by full transfer for reduction/speedup.
- `suite`: deduplicate the baseline among nine one-factor-at-a-time cases and
  run a comparison for each. The one-million-row case is intentional.
- `main`: parse exclusive compare/suite switches or choose a single method;
  write the resulting JSON report and print it for command-line use.

## Tests and what each assertion protects

Every `test_*` function has a local docstring explaining its individual contract.
Test classes group these contracts:

| File / class | Coverage |
| --- | --- |
| `test_baseline.py` / `BaselineTests` | Reference joins at overlap extremes; full row counts; reproducible database bytes; generator rejection |
| `test_bloom_filter.py` / `BloomFilterTests` | Membership without false negatives; serialized round-trip; compatible AND and remote-probe equivalence; dimension/payload rejection; fixed sizing |
| `test_bloom_filter.py` / `DistributedBloomTests` | Real socket workers at overlap extremes; build timing; byte savings/repeatability; known-empty and cost fallback; bad configuration |
| `test_benchmark.py` / `BenchmarkTests` | Hand-computed statistics; warmup exclusion; reused datasets; rotation; suite factors; failure propagation; real repeats |
| `test_cost_sizing.py` / `CostSizingTests` | Paper examples; monotonic cost inputs; empty/no-benefit cases; caps/alignment and huge counts; complete validation |
| `test_protocol.py` / `ProtocolTests` | Exact frame counts; one-byte fragments; truncated frames; excessive advertised length |
| `test_sizing_metadata.py` / `SizingMetadataTests` | Escaped widths; metadata counted once; SQL correctness; empty local inputs |

Mocks isolate benchmark bookkeeping; distributed tests run real spawned processes.
Temporary directories and socket context managers release resources after failures.
