# Public implementation cross-comparison

Inspected 2026-11-18. These are design comparisons, not head-to-head performance
claims. No third-party implementation was copied or added as a dependency.
Links to branch heads can change; pin a commit before a formal reproduction.

| Reference | Relevant observed design | Implication for this project |
| --- | --- | --- |
| [python-bloomfilter / pybloom_live](https://github.com/joseph-fox/python-bloomfilter), [implementation](https://github.com/joseph-fox/python-bloomfilter/blob/master/pybloom_live/pybloom.py) | Fixed-capacity/error-rate and scalable filters, external bitarray/xxhash dependencies, compatible-dimension intersection and persistence | Useful optional CPU baseline; unlike this project, size is selected from an error target rather than remote transfer cost |
| [Apache Spark BloomFilterImpl](https://github.com/apache/spark/blob/master/common/sketch/src/main/java/org/apache/spark/util/sketch/BloomFilterImpl.java) | Combines two hash components for bit positions, stops negative probes early, checks merge dimensions, versions serialized data | Supports retaining deterministic double hashing, lazy early-exit probes, dimension checks; a wire version would help if this prototype becomes a service |
| [Original python-bloomfilter](https://github.com/jaybaird/python-bloomfilter) | Archived scalable-filter implementation | Historical reference; prefer assessing the fork when choosing an optional maintained dependency |
| [Ramesh et al., author-hosted paper](https://opapapetrou.win.tue.nl/papers/icdcit08-djoins.pdf), [DOI](https://doi.org/10.1007/978-3-540-89737-8_15) | Section 4.1 models filter transmission plus candidate transfer and derives filter length | Source of existing sizing policy; generalize separate local/remote counts and convert bytes to bits explicitly |

The Spark file is a filter primitive, not this SQLite distributed-join experiment.
Likewise, pybloom_live measures membership behavior rather than the socket and SQL
pipeline here. Comparing their published speed claims directly to these timings
would conflate languages, workloads, data structures and network assumptions.

For a fair optional library comparison, reuse the generated databases, match
effective bit/hash parameters where possible, use the same base64/JSON transport,
and include construction and probing in query time. Validate every result with
the SQL oracle and count every application frame. Keep dependency versions and
licenses with the resulting report. Faster hashing should be measured before
replacing the standard-library SHA-256 implementation.
