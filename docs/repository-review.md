# Repository review and implementation scope

## What the repository is going for

The attached four-page proposal describes an exact distributed equijoin using
Bloom filters as a candidate-reduction step. Its research question is how much
communication and elapsed query time filtering saves relative to transferring
complete remote records. A Bloom filter supplements the relational join: SQLite
still performs the final exact comparison.

The proposal was treated as project context, distinct from the user's request
to read, annotate, compare, and implement the repository. Its explicit core scope
is Section 4.1 sizing and three evaluation methods, not the paper's complete
four-strategy optimizer. No unrelated document instructions were executed.

The initial inventory contained all eight package modules, six test files,
README, pyproject, and .gitignore. All were read before edits. There were no
repository-specific agent instructions or uncommitted source changes. Initially
19 tests passed. The Bloom test module was empty.

## Findings and completed changes

| Initial finding | Implemented response |
| --- | --- |
| Full-transfer runner already used real sockets and a separate process | Preserve that architecture and exact SQL oracle |
| Packed deterministic Bloom filter and continuous sizing formula existed | Document, bound dimensions, and test serialization/membership/intersection |
| Bloom runner partially worked but CLI could not select it | Expose full/fixed/cost-selected methods through CLI and Python |
| Fixed ten-bits-per-key policy was missing | Add byte-aligned policy and nearest optimal hash count |
| Proposal's remote filter/AND was absent | Build compatible remote filter and AND before remote probes |
| Filter construction always reported zero | Measure local build and remote build/AND; sum and retain each interval |
| Empty filtered inputs could still transfer whole remote tables | Short-circuit known-empty joins |
| Benchmark only ran full transfer | Compare methods on identical data, rotate order, retain warmups policy and variance |
| Proposal workload matrix not runnable | Add one-factor-at-a-time suite covering all specified levels |
| Frames had no size bound | Reject frames over 16 MiB before reading bodies |
| README and explanatory material were missing | Add function notes, sizing derivation, methodology and public references |

## The AND observation

Let L be the local filter, R the remote filter, and x a key inserted into R.
Every hash position of x is one in R. Thus, at every position queried for x,
`(L & R)[position] == L[position]`. Probing L & R for remote records gives
exactly the same candidate decisions as probing L alone. This is true even
when L has false positives. A regression test checks that equivalence.

The `fixed` and `bloom` flows follow the proposal to make its work measurable.
The additional `bloom-local` method skips the second build to quantify that
overhead while retaining the same cost-selected dimensions. AND may have a purpose in different multi-site flows, but
it cannot improve this two-site remote-probe candidate set.

## Improvements to investigate next

1. Implemented: `bloom-local` skips the remote build/AND. Regression tests check
   identical candidate rows (including false positives), dimensions, and SQL
   results, plus zero remote build time. Comparisons retain both variants.
2. Extend cost selection to actual framing and base64 size (about 4/3 of packed
   size), integer hash counts, and CPU costs. The present model remains a faithful
   continuous Section 4.1 adaptation; its optimum is not a measured wire optimum.
3. Supply sampled/cached statistics and selectivity estimates. Currently widths
   require a full remote scan, which is charged to the cost-selected method.
4. Compare a faster noncryptographic hash/bit-array implementation while charging
   the same wire format and retaining deterministic cross-process compatibility.
5. Measure controlled bandwidth/latency separately from this loopback experiment.
   An exact-key semijoin would also be a useful additional baseline.
6. If expanding beyond the proposal, support skewed cardinalities, repeated keys,
   nullable keys, snapshot consistency, streaming reference verification and
   multiple sites. Those change assumptions and should be separate experiments.

The implementation deliberately does not claim that Bloom filtering always wins
or reproduce the complete optimizer from the paper.

## Initial three-method verification

All 33 unit/integration tests passed, the single-query CLI smoke check passed,
and `git diff --check` found no whitespace errors. Every source/test function
and class has a docstring. The complete nine-case workload sweep ran three
measured repeats plus one warmup for each method: all 108 results were verified
against the exact SQL oracle. See [evaluation](evaluation.md) for the 81 measured
runs, timing variation, byte reductions and raw data.
