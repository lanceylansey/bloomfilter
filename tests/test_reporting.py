"""Check exported evidence, scenario separation and repeat statistics."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bloomjoin.reporting import export_csv, format_summary, report_rows
from bloomjoin.scenarios import run_scenarios, scenario_plan


def example_report():
    """Create a small report with independently calculable means and ratios."""
    def runs(seconds, size):
        """Return measured samples only, with a valid zero false-positive rate."""
        return [{"repeat": i + 1, "query_seconds": value, "application_bytes": size,
                 "filter_build_seconds": 0.0, "observed_false_positive_rate": 0.0,
                 "result_rows": 1, "verified": True} for i, value in enumerate(seconds)]
    return {"configuration": {"rows_per_site": 10, "overlap": .1, "payload_bytes": 32,
                              "seed": 42, "bandwidth_mbps": None, "repeats": 2, "warmups": 1},
            "measurement": {"network": "loopback TCP"},
            "methods": {"full": {"runs": runs([2, 4], 100)},
                        "bloom-local": {"runs": runs([1, 2], 25)}}}


class ReportingTests(unittest.TestCase):
    """Exports preserve raw values and calculate per-case statistics correctly."""

    def test_csv_round_trip_and_hand_calculated_summary(self):
        """Null stays blank, zero stays zero, and means/ratios use measured runs."""
        report = example_report()
        report['scenario_name'] = 'commas, quotes " and newline\ncase'
        with tempfile.TemporaryDirectory() as tmp:
            raw_path, summary_path = export_csv(report, Path(tmp) / 'runs.csv')
            with raw_path.open(newline='', encoding='utf-8') as source:
                raw = list(csv.DictReader(source))
            with summary_path.open(newline='', encoding='utf-8') as source:
                summary = list(csv.DictReader(source))
        self.assertEqual(len(raw), 4)
        self.assertEqual(raw[0]['scenario_name'], report['scenario_name'])
        self.assertEqual(raw[0]['bandwidth_mbps'], '')
        self.assertEqual(raw[0]['observed_false_positive_rate'], '0.0')
        self.assertEqual(float(summary[0]['query_mean_seconds']), 3)
        self.assertAlmostEqual(float(summary[0]['query_stdev_seconds']), 2**.5)
        self.assertEqual(float(summary[1]['byte_reduction_fraction']), .75)
        self.assertEqual(float(summary[1]['speedup']), 2)

    def test_scenarios_do_not_pool_seeds_or_bandwidth(self):
        """Separate configurations retain separate statistics and scenario numbers."""
        first, second = example_report(), example_report()
        second['configuration'].update(seed=7, bandwidth_mbps=10)
        raw, summaries = report_rows({'experiments': [first, second]})
        self.assertEqual(len(raw), 8)
        self.assertEqual(len(summaries), 4)
        self.assertEqual([r['scenario'] for r in summaries], [1, 1, 2, 2])
        self.assertEqual(summaries[2]['seed'], 7)
        self.assertEqual(summaries[2]['bandwidth_mbps'], 10)
        self.assertIn('simulated 10 Mbps', format_summary({'experiments': [first, second]}))

    def test_single_method_has_no_invented_baseline(self):
        """A filtered-only benchmark exports blank relative metrics, not fake zeros."""
        report = example_report()
        report['configuration']['strategy'] = 'bloom-local'
        report['runs'] = report.pop('methods')['bloom-local']['runs'][:1]
        _, summary = report_rows(report)
        self.assertIsNone(summary[0]['speedup'])
        self.assertIsNone(summary[0]['byte_reduction_fraction'])
        self.assertEqual(summary[0]['query_stdev_seconds'], 0)

    def test_unverified_reports_are_rejected_before_writing(self):
        """Incorrect results cannot become successful-looking CSV evidence."""
        report = example_report()
        report['methods']['full']['runs'][0]['verified'] = False
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'runs.csv'
            with self.assertRaises(ValueError):
                export_csv(report, path)
            self.assertFalse(path.exists())

    def test_scenario_plan_and_checkpoints(self):
        """The preset covers the promised factors and writes a complete checkpoint."""
        plan = scenario_plan()
        self.assertEqual(len(plan), 16)
        self.assertEqual(len({c['name'] for c in plan}), 16)
        self.assertEqual({c['seed'] for c in plan}, {7, 42, 99})
        self.assertEqual({c['bandwidth_mbps'] for c in plan}, {None, 10, 25, 100})
        self.assertEqual(plan[-1]['rows'], 1000000)
        with tempfile.TemporaryDirectory() as tmp, \
                patch('bloomjoin.scenarios.scenario_plan', return_value=plan[:1]), \
                patch('bloomjoin.scenarios.compare', return_value=example_report()), \
                patch('builtins.print'):
            output = Path(tmp) / 'fresh'
            report = run_scenarios(output, repeats=2, warmups=1)
            self.assertEqual(report['status'], 'complete')
            self.assertEqual(report['completed_scenarios'], 1)
            self.assertTrue((output / 'study.json').is_file())
            self.assertTrue((output / 'runs.csv').is_file())
            self.assertTrue((output / 'runs.summary.csv').is_file())

    def test_failed_later_scenario_preserves_verified_prefix(self):
        """An interrupted study retains completed data without claiming completion."""
        import json
        with tempfile.TemporaryDirectory() as tmp, \
                patch('bloomjoin.scenarios.scenario_plan', return_value=scenario_plan()[:2]), \
                patch('bloomjoin.scenarios.compare',
                      side_effect=[example_report(), RuntimeError('worker failed')]), \
                patch('builtins.print'):
            output = Path(tmp) / 'fresh'
            with self.assertRaisesRegex(RuntimeError, 'worker failed'):
                run_scenarios(output, repeats=2, warmups=1)
            report = json.loads((output / 'study.json').read_text())
            self.assertEqual(report['status'], 'running')
            self.assertEqual(report['completed_scenarios'], 1)
            self.assertEqual(report['planned_scenarios'], 2)
            with (output / 'runs.csv').open(newline='', encoding='utf-8') as source:
                self.assertEqual(len(list(csv.DictReader(source))), 4)
