"""Bloom invariants and distributed correctness across all evaluation methods."""
from contextlib import closing
import sqlite3
import tempfile
import unittest

from bloomjoin.data import generate
from bloomjoin.experiment import run
from bloomjoin.strategies import BloomFilter, fixed_filter_size, MAX_FILTER_BITS


class BloomFilterTests(unittest.TestCase):
    """Exercise serialization, compatibility, and no-false-negative guarantees."""

    def test_round_trip_has_no_false_negatives(self):
        """Packed transport preserves membership for negative and large integers."""
        keys = list(range(-100, 100)) + [2**62]
        bloom = BloomFilter(4096, 7)
        for key in keys:
            bloom.add(key)
            bloom.add(key)
        restored = BloomFilter.from_bytes(4096, 7, bloom.to_bytes())
        self.assertTrue(all(restored.might_contain(key) for key in keys))
        self.assertFalse(BloomFilter(4096, 7).might_contain(1))
        self.assertTrue(any(not restored.might_contain(k) for k in range(1000, 1100)))

    def test_intersection_preserves_shared_keys_and_remote_probe_answers(self):
        """AND is safe but cannot reject more of the remote filter's own keys."""
        left, right = BloomFilter(1024, 7), BloomFilter(1024, 7)
        for key in range(100):
            left.add(key)
        for key in range(50, 150):
            right.add(key)
        combined = left.intersection(right)
        self.assertTrue(all(combined.might_contain(k) for k in range(50, 100)))
        self.assertEqual([left.might_contain(k) for k in range(50, 150)],
                         [combined.might_contain(k) for k in range(50, 150)])
        for other in (BloomFilter(1025, 7), BloomFilter(1024, 6)):
            with self.assertRaises(ValueError):
                left.intersection(other)

    def test_invalid_dimensions_and_payload(self):
        """Reject malformed and excessive allocations before allocating storage."""
        for bits, hashes in ((0, 1), (1, 0), (True, 1), (1, True), (1.5, 2),
                             (MAX_FILTER_BITS + 1, 1), (8, 33)):
            with self.subTest(bits=bits, hashes=hashes), self.assertRaises(ValueError):
                BloomFilter(bits, hashes)
        with self.assertRaises(ValueError):
            BloomFilter.from_bytes(9, 2, b'\x00')

    def test_fixed_policy(self):
        """Ten bits per key are byte-aligned with optimal rounded hash count."""
        self.assertEqual(fixed_filter_size(100), (1000, 7))
        self.assertEqual(fixed_filter_size(1), (16, 11))
        self.assertEqual(fixed_filter_size(0), (0, 0))
        for bad in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                fixed_filter_size(bad)


class DistributedBloomTests(unittest.TestCase):
    """Require exact SQL results despite probabilistic candidate selection."""

    def test_empty_disjoint_partial_and_complete_overlap(self):
        """Each method preserves true rows; filtering never increases row count."""
        for rows, overlap in ((0, 0), (100, 0), (100, .1), (100, 1)):
            with self.subTest(rows=rows, overlap=overlap), tempfile.TemporaryDirectory() as tmp:
                paths = generate(tmp, rows, overlap, 32)
                for strategy in ('fixed', 'bloom'):
                    metrics = run(*paths, strategy=strategy)
                    self.assertTrue(metrics['verified'])
                    self.assertEqual(metrics['result_rows'], int(rows * overlap))
                    self.assertLessEqual(metrics['transferred_records'], rows)
                    if rows:
                        self.assertTrue(metrics['filter_applied'])
                        self.assertGreater(metrics['local_filter_build_seconds'], 0)
                        self.assertGreater(metrics['remote_filter_build_seconds'], 0)
                        self.assertAlmostEqual(metrics['filter_build_seconds'],
                                               metrics['local_filter_build_seconds']
                                               + metrics['remote_filter_build_seconds'])

    def test_low_overlap_saves_bytes_and_byte_counts_are_repeatable(self):
        """Count filter/setup overhead and confirm actual end-to-end savings."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate(tmp, 1000, .01, 128)
            baseline = run(*paths)
            for strategy in ('fixed', 'bloom'):
                first = run(*paths, strategy=strategy)
                second = run(*paths, strategy=strategy)
                self.assertLess(first['application_bytes'], baseline['application_bytes'])
                self.assertEqual(first['application_bytes'], second['application_bytes'])
                self.assertLess(first['nonmatching_records'], baseline['nonmatching_records'])
                self.assertTrue(0 <= first['observed_false_positive_rate'] <= 1)

    def test_empty_one_site_and_cost_bypass(self):
        """An empty site short-circuits; an estimate of 100% bypasses filtering."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate(tmp, 20, .5, 8)
            bypass = run(*paths, strategy='bloom', selectivity=1)
            self.assertEqual(bypass['execution_strategy'], 'full')
            self.assertFalse(bypass['filter_applied'])
            with closing(sqlite3.connect(paths[0])) as db:
                db.execute('DELETE FROM records')
                db.commit()
            for strategy in ('fixed', 'bloom'):
                empty = run(*paths, strategy=strategy)
                self.assertEqual(empty['transferred_records'], 0)
                self.assertEqual(empty['execution_strategy'], 'empty')
                self.assertTrue(empty['verified'])

    def test_invalid_strategy_and_estimate(self):
        """Reject configuration before launching workers or opening databases."""
        with self.assertRaises(ValueError):
            run('missing', 'missing', strategy='unknown')
        with self.assertRaises(ValueError):
            run('missing', 'missing', selectivity=float('nan'))
        with self.assertRaises(FileNotFoundError):
            run('missing', 'missing')

    def test_saturated_filter_still_produces_exact_join(self):
        """Force many false positives and require exact SQL to remove them."""
        from unittest.mock import patch
        from bloomjoin.strategies import FilterSize
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate(tmp, 100, .1, 8)
            with patch('bloomjoin.experiment.choose_filter_size', return_value=FilterSize(8, 1)):
                metrics = run(*paths, strategy='bloom')
            self.assertTrue(metrics['verified'])
            self.assertEqual(metrics['result_rows'], 10)
            self.assertGreater(metrics['nonmatching_records'], 0)

    def test_nonempty_local_with_empty_remote(self):
        """The cost method detects remote emptiness and every method stays exact."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate(tmp, 10, .5, 8)
            with closing(sqlite3.connect(paths[1])) as db:
                db.execute('DELETE FROM records')
                db.commit()
            for strategy in ('full', 'fixed', 'bloom'):
                metrics = run(*paths, strategy=strategy)
                self.assertTrue(metrics['verified'])
                self.assertEqual(metrics['remote_records'], 0)
                self.assertEqual(metrics['result_rows'], 0)
                if strategy == 'bloom':
                    self.assertEqual(metrics['execution_strategy'], 'empty')
