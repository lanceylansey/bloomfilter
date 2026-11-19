"""Export verified benchmark reports as flat CSVs and readable terminal tables."""
import csv
from pathlib import Path
import statistics


CONTEXT_FIELDS = (
    "scenario", "scenario_name", "rows_per_site", "overlap", "payload_bytes", "seed",
    "selectivity_estimate", "bandwidth_mbps", "repeats", "warmups", "network",
    "python", "sqlite", "platform", "strategy",
)
RUN_FIELDS = (
    "repeat", "execution_strategy", "filter_applied", "application_bytes",
    "query_seconds", "filter_build_seconds", "local_filter_build_seconds",
    "remote_filter_build_seconds", "filter_bytes", "remote_records",
    "transferred_records", "rejected_records", "nonmatching_records",
    "result_rows", "observed_false_positive_rate", "verified",
)
SIZING_FIELDS = (
    "local_count", "row_count", "mean_row_bytes", "bit_count", "hash_count",
    "metadata_application_bytes",
)
SUMMARY_FIELDS = (
    "measured_runs", "query_mean_seconds", "query_median_seconds",
    "query_min_seconds", "query_max_seconds", "query_stdev_seconds",
    "filter_build_mean_seconds", "filter_build_stdev_seconds",
    "mean_application_bytes", "byte_reduction_fraction", "speedup",
    "mean_transferred_records", "mean_nonmatching_records", "result_rows", "verified",
)


def report_rows(report):
    """Flatten single-method, comparison or multi-scenario reports without pooling cases.

    Warmups are already excluded by the benchmark. Missing/not-applicable values
    stay blank in CSV; they are never changed into measured zeros.
    """
    raw_rows, summaries = [], []
    for scenario, experiment in enumerate(report.get("experiments", [report]), 1):
        config = experiment["configuration"]
        if "methods" in experiment:
            methods = experiment["methods"]
        else:
            methods = {config["strategy"]: experiment}
        full_runs = methods.get("full", {}).get("runs", [])
        baseline_bytes = statistics.mean(r["application_bytes"] for r in full_runs) if full_runs else None
        baseline_time = statistics.mean(r["query_seconds"] for r in full_runs) if full_runs else None
        for strategy, method in methods.items():
            runs = method["runs"]
            if not runs or any(run.get("verified") is not True for run in runs):
                raise ValueError("CSV exports require nonempty, SQL-verified measured runs")
            context = {"scenario": scenario, "scenario_name": experiment.get("scenario_name"), **config,
                       "network": experiment.get("measurement", {}).get("network"),
                       **experiment.get("environment", {}), "strategy": strategy}
            # Select known columns rather than leaking nested objects into cells.
            context = {name: context.get(name) for name in CONTEXT_FIELDS}
            for run in runs:
                raw_rows.append({**context, **{name: run.get(name) for name in RUN_FIELDS},
                                 **{"sizing_" + name: run.get("sizing", {}).get(name)
                                    for name in SIZING_FIELDS}})
            times = [r["query_seconds"] for r in runs]
            builds = [r["filter_build_seconds"] for r in runs]
            mean_time = statistics.mean(times)
            mean_bytes = statistics.mean(r["application_bytes"] for r in runs)
            summaries.append({
                **context, "measured_runs": len(runs),
                "query_mean_seconds": mean_time, "query_median_seconds": statistics.median(times),
                "query_min_seconds": min(times), "query_max_seconds": max(times),
                "query_stdev_seconds": statistics.stdev(times) if len(times) > 1 else 0.0,
                "filter_build_mean_seconds": statistics.mean(builds),
                "filter_build_stdev_seconds": statistics.stdev(builds) if len(builds) > 1 else 0.0,
                "mean_application_bytes": mean_bytes,
                "byte_reduction_fraction": 1 - mean_bytes / baseline_bytes if baseline_bytes else None,
                "speedup": baseline_time / mean_time if baseline_time is not None and mean_time else None,
                "mean_transferred_records": _mean_if_present(runs, "transferred_records"),
                "mean_nonmatching_records": _mean_if_present(runs, "nonmatching_records"),
                "result_rows": runs[0].get("result_rows"), "verified": True,
            })
    return raw_rows, summaries


def _mean_if_present(runs, field):
    """Preserve missing fields when exporting an older/minimal report."""
    values = [run.get(field) for run in runs]
    return statistics.mean(values) if all(value is not None for value in values) else None


def export_csv(report, path):
    """Write per-run CSV and a sibling .summary.csv; return both actual paths."""
    raw_rows, summaries = report_rows(report)
    path = Path(path)
    summary_path = path.with_name(path.stem + ".summary.csv")
    for destination, fields, rows in (
        (path, CONTEXT_FIELDS + RUN_FIELDS + tuple("sizing_" + n for n in SIZING_FIELDS), raw_rows),
        (summary_path, CONTEXT_FIELDS + SUMMARY_FIELDS, summaries),
    ):
        destination.parent.mkdir(parents=True, exist_ok=True)
        # newline='' lets csv handle platform line endings and quoted values correctly.
        with destination.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return path, summary_path


def format_summary(report):
    """Show one compact comparison table per scenario, including slower methods."""
    _, summaries = report_rows(report)
    lines = []
    previous = None
    for row in summaries:
        if row["scenario"] != previous:
            rate = row["bandwidth_mbps"]
            network = f"simulated {rate:g} Mbps" if rate is not None else "unlimited loopback"
            lines.extend([
                "", f"Scenario {row['scenario']}: {row['rows_per_site']:,} rows/site, "
                f"{row['overlap'] * 100:g}% overlap, {row['payload_bytes']} payload bytes, "
                f"seed {row['seed']}, {network}",
                "Method        Mean s   Stdev s   Build s   Bytes (MB)   Saved     Speedup",
            ])
            previous = row["scenario"]
        saved = f"{row['byte_reduction_fraction']:.1%}" if row['byte_reduction_fraction'] is not None else "--"
        speedup = f"{row['speedup']:.2f}x" if row['speedup'] is not None else "--"
        lines.append(f"{row['strategy']:<12} {row['query_mean_seconds']:>7.4f} "
                     f"{row['query_stdev_seconds']:>9.4f} {row['filter_build_mean_seconds']:>9.4f} "
                     f"{row['mean_application_bytes'] / 1e6:>12.3f} {saved:>8} {speedup:>11}")
    lines.append("All measured results verified against SQL. Warmups excluded; MB = 1,000,000 bytes.")
    return "\n".join(lines)
