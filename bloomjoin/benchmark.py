"""Repeat verified queries and compare strategies on identical generated data."""
import argparse
import json
import platform
import sqlite3
import statistics
import tempfile
from pathlib import Path
from .data import generate
from .experiment import run, STRATEGIES


TIMING_METRICS = ("query_seconds", "filter_build_seconds")


def summarize(runs):
    """Summarize timings with sample deviation (zero for a single repeat)."""
    if not runs:
        raise ValueError("At least one measured run is required")
    # Gather each metric across runs, then compute its descriptive statistics.
    return {
        name: {
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        }
        for name in TIMING_METRICS
        for values in [[entry[name] for entry in runs]]
    }


def benchmark(rows=1000, overlap=0.1, payload_bytes=32, seed=42, repeats=3, warmups=1,
              strategy="full", selectivity=0.0):
    """Repeat one strategy on reused databases; verify and exclude warmups."""
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be nonnegative")
    measured = []
    # Generate once and reuse the same databases across all runs. Clean up on failure.
    with tempfile.TemporaryDirectory(prefix="bloomjoin-benchmark-") as directory:
        paths = generate(directory, rows, overlap, payload_bytes, seed)
        for index in range(warmups + repeats):
            metrics = run(*paths, strategy=strategy, selectivity=selectivity)
            if metrics.get("verified") is not True:
                raise AssertionError("Cannot benchmark an unverified result")
            # Warmups still run correctness checks, but do not enter the report.
            if index >= warmups:
                measured.append({"repeat": index - warmups + 1, **metrics})
    return {
        "configuration": {"rows_per_site": rows, "overlap": overlap,
                          "payload_bytes": payload_bytes, "seed": seed,
                          "repeats": repeats, "warmups": warmups, "strategy": strategy,
                          "selectivity_estimate": selectivity},
        "environment": {"python": platform.python_version(),
                        "platform": platform.platform(), "sqlite": sqlite3.sqlite_version},
        "measurement": {
            "network": "loopback TCP",
            "bytes": "application messages plus framing, both directions counted once",
            "timing": "local count through exact join; excludes generation, process startup/connection, reference validation",
            "filter_build": "sum of local build and remote build/AND; included in query time",
            "warmups": "executed and verified; excluded from runs and summaries",
        },
        "runs": measured,
        "timing_seconds": summarize(measured),
    }


def compare(rows=1000, overlap=0.1, payload_bytes=32, seed=42, repeats=3, warmups=1,
            selectivity=0.0):
    """Compare all methods on one dataset, rotating execution order each round."""
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be nonnegative")
    measured = {strategy: [] for strategy in STRATEGIES}
    with tempfile.TemporaryDirectory(prefix="bloomjoin-compare-") as directory:
        paths = generate(directory, rows, overlap, payload_bytes, seed)
        for index in range(warmups + repeats):
            # Rotate the first method so one method is not always run first.
            offset = index % len(STRATEGIES)
            for strategy in STRATEGIES[offset:] + STRATEGIES[:offset]:
                metrics = run(*paths, strategy=strategy, selectivity=selectivity)
                if metrics.get("verified") is not True:
                    raise AssertionError("Cannot benchmark an unverified result")
                if index >= warmups:
                    measured[strategy].append({"repeat": index - warmups + 1, **metrics})
    # Use full-transfer means as the common denominator for every method.
    baseline_bytes = statistics.mean(r["application_bytes"] for r in measured["full"])
    baseline_time = statistics.mean(r["query_seconds"] for r in measured["full"])
    methods = {}
    for strategy, runs in measured.items():
        mean_bytes = statistics.mean(r["application_bytes"] for r in runs)
        mean_seconds = statistics.mean(r["query_seconds"] for r in runs)
        methods[strategy] = {
            "runs": runs, "timing_seconds": summarize(runs),
            "mean_application_bytes": mean_bytes,
            # Negative reduction means overhead exceeded the bytes saved.
            "byte_reduction_fraction": 1 - mean_bytes / baseline_bytes,
            # Above one is faster; below one is slower than the baseline.
            "speedup": baseline_time / mean_seconds if mean_seconds else None,
        }
    return {
        "configuration": {"rows_per_site": rows, "overlap": overlap,
                          "payload_bytes": payload_bytes, "seed": seed,
                          "repeats": repeats, "warmups": warmups,
                          "selectivity_estimate": selectivity},
        "environment": {"python": platform.python_version(),
                        "platform": platform.platform(), "sqlite": sqlite3.sqlite_version},
        "measurement": {"network": "loopback TCP", "order": "rotating strategy order",
                        "bytes": "all application frames, both directions counted once; excludes TCP/IP",
                        "timing": "local count through exact join; excludes startup, generation and validation",
                        "filter_build": "sum of local build and remote build/AND; included in query time",
                        "warmups": "verified and excluded; fresh process per run"},
        "methods": methods,
    }


def suite(seed=42, repeats=3, warmups=1, selectivity=0.0):
    """Vary proposal factors individually around 10k rows, 10% overlap, 32 bytes."""
    # dict.fromkeys removes repeated baseline cases while preserving their order.
    cases = dict.fromkeys(
        [(n, 0.1, 32) for n in (10000, 100000, 1000000)]
        + [(10000, overlap, 32) for overlap in (0, 0.01, 0.1, 0.5, 1)]
        + [(10000, 0.1, width) for width in (32, 128, 512)])
    return {"baseline": {"rows": 10000, "overlap": 0.1, "payload_bytes": 32},
            "experiments": [compare(n, overlap, width, seed, repeats, warmups, selectivity)
                            for n, overlap, width in cases]}


def main():
    """Write a single-method benchmark, a comparison, or the proposal sweep."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--overlap", type=float, default=0.1)
    parser.add_argument("--payload-bytes", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--strategy", choices=STRATEGIES, default="full")
    # Comparison and the complete sweep are alternative benchmark modes.
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--compare", action="store_true", help="Compare all methods on identical data")
    modes.add_argument("--suite", action="store_true", help="Run the proposal's one-factor-at-a-time sweep")
    parser.add_argument("--selectivity-estimate", type=float, default=0.0)
    parser.add_argument("--output", type=Path, default=Path("results/benchmark.json"))
    args = parser.parse_args()
    if args.suite:
        report = suite(args.seed, args.repeats, args.warmups, args.selectivity_estimate)
    elif args.compare:
        report = compare(args.rows, args.overlap, args.payload_bytes, args.seed,
                         args.repeats, args.warmups, args.selectivity_estimate)
    else:
        report = benchmark(args.rows, args.overlap, args.payload_bytes, args.seed,
                           args.repeats, args.warmups, args.strategy, args.selectivity_estimate)
    # Save individual runs as well as summaries so calculations can be inspected.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
