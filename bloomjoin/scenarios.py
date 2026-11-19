"""Run a bounded, repeatable study and checkpoint CSV/JSON after every scenario."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .benchmark import compare
from .reporting import export_csv, format_summary


def scenario_plan():
    """Cover proposal factors, bandwidth tradeoffs and additional dataset seeds.

    Each case varies one setting from its stated reference, rather than testing
    a large Cartesian product. The million-row case runs last.
    """
    cases = [
        ("baseline-10k", 10000, .1, 32, 42, None),
        ("size-100k", 100000, .1, 32, 42, None),
        *[(f"overlap-{int(a * 100)}pct", 10000, a, 32, 42, None)
          for a in (0, .01, .5, 1)],
        *[(f"payload-{width}", 10000, .1, width, 42, None) for width in (128, 512)],
        *[(f"network-{rate}mbps", 100000, .1, 32, 42, rate) for rate in (10, 25, 100)],
        ("network-high-overlap", 100000, .8, 32, 42, 10),
        ("network-wide-payload", 10000, .1, 512, 42, 10),
        *[(f"seed-{seed}", 100000, .1, 32, seed, None) for seed in (7, 99)],
        ("size-1m", 1000000, .1, 32, 42, None),
    ]
    return [{"name": name, "rows": rows, "overlap": overlap, "payload_bytes": width,
             "seed": seed, "bandwidth_mbps": bandwidth}
            for name, rows, overlap, width, seed, bandwidth in cases]


def run_scenarios(output_dir, repeats=5, warmups=1):
    """Run all cases sequentially; preserve a verified prefix if a later case fails."""
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be nonnegative")
    output_dir = Path(output_dir)
    # A fresh folder prevents accidentally mixing outputs from different studies.
    output_dir.mkdir(parents=True, exist_ok=False)
    plan = scenario_plan()
    (output_dir / "plan.json").write_text(json.dumps({"cases": plan, "repeats": repeats,
                                                   "warmups": warmups}, indent=2) + "\n", encoding="utf-8")
    report = {"planned_scenarios": len(plan), "completed_scenarios": 0,
              "status": "running", "experiments": []}

    def progress(strategy, round_number, warmup, metrics):
        """Print completed queries promptly, without adding time to their measurements."""
        phase = "warmup" if warmup else "measured"
        print(f"  {phase} round {round_number}: {strategy:<11} "
              f"{metrics['query_seconds']:.3f}s, {metrics['application_bytes']:,} bytes, SQL verified",
              flush=True)

    for index, case in enumerate(plan, 1):
        settings = {key: value for key, value in case.items() if key != "name"}
        print(f"\n[{index}/{len(plan)}] {case['name']}: {settings}", flush=True)
        experiment = compare(**settings, repeats=repeats, warmups=warmups, progress=progress)
        experiment["scenario_name"] = case["name"]
        path = output_dir / f"{index:02d}-{case['name']}.json"
        path.write_text(json.dumps(experiment, indent=2) + "\n", encoding="utf-8")
        report["experiments"].append(experiment)
        report["completed_scenarios"] = index
        report["status"] = "complete" if index == len(plan) else "running"
        # Every checkpoint contains only completed, verified scenarios. Raw runs
        # remain separate from summaries; warmups never enter either CSV.
        (output_dir / "study.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        export_csv(report, output_dir / "runs.csv")
        print(format_summary(experiment), flush=True)
    print(f"\nStudy complete. Reports saved in {output_dir}", flush=True)
    return report


def main():
    """Choose repetitions and a fresh output directory for the 16-scenario study."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--output-dir", type=Path, default=Path("results/scenarios") / timestamp)
    args = parser.parse_args()
    run_scenarios(args.output_dir, args.repeats, args.warmups)


if __name__ == "__main__":
    main()
