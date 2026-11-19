"""Regression checks for benchmark."""
import unittest
from unittest.mock import patch
from bloomjoin.benchmark import benchmark, summarize, compare, suite


def sample(seconds):
    """Create a verified synthetic measurement for isolated benchmark tests."""
    return {"query_seconds": seconds, "filter_build_seconds": 0.0,
            "application_bytes": 123, "nonmatching_records": 9, "verified": True}


class BenchmarkTests(unittest.TestCase):
    """Check statistics, repeated-run bookkeeping, failures and real small queries."""
    def test_comparison_rotates_methods_and_excludes_warmups(self):
        """Compare the same paths with balanced order and discard verified warmups."""
        with patch('bloomjoin.benchmark.run', return_value=sample(2)) as runner:
            report = compare(rows=5, repeats=2, warmups=1)
        self.assertEqual(runner.call_count, 9)
        self.assertEqual([c.kwargs['strategy'] for c in runner.call_args_list],
                         ['full', 'fixed', 'bloom', 'fixed', 'bloom', 'full',
                          'bloom', 'full', 'fixed'])
        self.assertEqual(len({c.args for c in runner.call_args_list}), 1)
        for method in report['methods'].values():
            self.assertEqual(len(method['runs']), 2)
            self.assertEqual(method['byte_reduction_fraction'], 0)
            self.assertEqual(method['speedup'], 1)
        with patch('bloomjoin.benchmark.run', return_value={'verified': False}):
            with self.assertRaises(AssertionError):
                compare(rows=0)

    def test_suite_varies_only_one_factor_at_a_time(self):
        """Cover every proposal factor without repeating the baseline case."""
        with patch('bloomjoin.benchmark.compare', return_value={}) as comparison:
            suite(repeats=1, warmups=0)
        cases = [call.args[:3] for call in comparison.call_args_list]
        self.assertEqual(len(cases), 9)
        self.assertEqual(len(set(cases)), 9)
        self.assertIn((1000000, .1, 32), cases)
        for case in cases:
            self.assertLessEqual(sum(a != b for a, b in zip(case, (10000, .1, 32))), 1)

    def test_summary_matches_hand_calculated_values(self):
        """Verify descriptive statistics against a hand-computed three-value sample."""
        summary = summarize([sample(1), sample(2), sample(3)])["query_seconds"]
        self.assertEqual(summary, {"mean": 2, "median": 2, "min": 1, "max": 3, "stdev": 1})
        self.assertEqual(summarize([sample(2)])["query_seconds"]["stdev"], 0)
        with self.assertRaises(ValueError):
            summarize([])

    def test_warmups_excluded_and_same_dataset_reused(self):
        """Ensure warmups do not enter summaries and every repeat uses the same database paths."""
        with patch("bloomjoin.benchmark.run", side_effect=[sample(99), sample(1), sample(3)]) as runner:
            report = benchmark(rows=10, repeats=2, warmups=1)
        self.assertEqual(runner.call_count, 3)
        self.assertTrue(all(call == runner.call_args_list[0] for call in runner.call_args_list))
        self.assertEqual([entry["query_seconds"] for entry in report["runs"]], [1, 3])
        self.assertEqual([entry["repeat"] for entry in report["runs"]], [1, 2])
        self.assertEqual(report["timing_seconds"]["query_seconds"]["mean"], 2)
        self.assertEqual(report["runs"][0]["application_bytes"], 123)
        self.assertEqual(report["configuration"]["seed"], 42)
        self.assertIn("sqlite", report["environment"])

    def test_invalid_repeat_configuration(self):
        """Reject missing measured runs and negative warmup counts."""
        for repeats, warmups in ((0, 0), (-1, 1), (1, -1)):
            with self.subTest(repeats=repeats, warmups=warmups):
                with self.assertRaises(ValueError):
                    benchmark(repeats=repeats, warmups=warmups)

    def test_rejects_unverified_runs_including_warmups(self):
        """Prevent unverified answers from being accepted as benchmark evidence."""
        with patch("bloomjoin.benchmark.run", return_value={"verified": False}):
            with self.assertRaises(AssertionError):
                benchmark(rows=0)

    def test_reference_failure_is_not_swallowed(self):
        """Propagate incorrect-result failures rather than reporting misleading performance."""
        with patch("bloomjoin.benchmark.run", side_effect=AssertionError("Incorrect result")):
            with self.assertRaisesRegex(AssertionError, "Incorrect result"):
                benchmark(rows=0)

    def test_real_small_benchmark(self):
        """Exercise actual spawned workers and check repeatable full-transfer byte counts."""
        report = benchmark(rows=10, overlap=0.1, repeats=2, warmups=0)
        self.assertEqual(len(report["runs"]), 2)
        for entry in report["runs"]:
            self.assertTrue(entry["verified"])
            self.assertEqual(entry["result_rows"], 1)
            self.assertEqual(entry["nonmatching_records"], 9)
        self.assertEqual(report["runs"][0]["application_bytes"], report["runs"][1]["application_bytes"])
