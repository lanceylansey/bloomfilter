"""Command-line entry point for generating data and running a verified join."""
import argparse
import json
from pathlib import Path
from .data import generate
from .experiment import run, STRATEGIES


def main():
    """Parse experiment settings and save measured, SQL-verified JSON results."""
    parser = argparse.ArgumentParser(description="Generate SQLite data and run a verified distributed join")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--overlap", type=float, default=0.1)
    parser.add_argument("--payload-bytes", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--strategy", choices=STRATEGIES, default="full")
    parser.add_argument("--selectivity-estimate", type=float, default=0.0,
                        help="Cost model input, independent of generated overlap")
    parser.add_argument("--collect-sizing", action="store_true",
                        help="Also collect sizing metadata for full/fixed runs")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("results/baseline.json"))
    args = parser.parse_args()
    # Generate persistent experiment inputs; this replaces their records tables.
    paths = generate(args.data_dir, args.rows, args.overlap, args.payload_bytes, args.seed)
    # The runner verifies its answer before returning any successful measurement.
    metrics = run(*paths, strategy=args.strategy, collect_sizing=args.collect_sizing,
                  selectivity=args.selectivity_estimate)
    # Save generation settings beside measurements to make the run reproducible.
    metrics["configuration"] = {"rows_per_site": args.rows, "overlap": args.overlap,
                                "payload_bytes": args.payload_bytes, "seed": args.seed,
                                "collect_sizing": args.collect_sizing, "strategy": args.strategy,
                                "selectivity_estimate": args.selectivity_estimate}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    # Spawned worker imports must not execute this CLI a second time.
    main()
