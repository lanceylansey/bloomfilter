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
    def test_simulated_bandwidth_delays_both_directions_without_changing_results(self):
        """A real spawned worker honors the rate and preserves bytes/correctness."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate(tmp, 20, .1, 8)
            for strategy in ('full', 'bloom-local'):
                unlimited = run(*paths, strategy=strategy)
                limited = run(*paths, strategy=strategy, bandwidth_mbps=.05)
                self.assertTrue(limited['verified'])
                self.assertEqual(limited['result_rows'], unlimited['result_rows'])
                self.assertEqual(limited['application_bytes'], unlimited['application_bytes'])
                # Both request and response frames must be delayed, once each.
                minimum = limited['application_bytes'] / (.05 * 125000)
                self.assertGreaterEqual(limited['query_seconds'], minimum * .99)
                self.assertEqual(limited['bandwidth_mbps'], .05)
                self.assertIn('simulated', limited['network'])


    def test_empty_disjoint_partial_and_complete_overlap(self):
        """Each method preserves true rows; filtering never increases row count."""
        for rows, overlap in ((0, 0), (100, 0), (100, .1), (100, 1)):
            with self.subTest(rows=rows, overlap=overlap), tempfile.TemporaryDirectory() as tmp:
                paths = generate(tmp, rows, overlap, 32)
                for strategy in ('fixed', 'bloom', 'bloom-local'):
                    metrics = run(*paths, strategy=strategy)
                    self.assertTrue(metrics['verified'])
                    self.assertEqual(metrics['result_rows'], int(rows * overlap))
                    self.assertLessEqual(metrics['transferred_records'], rows)
                    if rows:
                        self.assertTrue(metrics['filter_applied'])
                        self.assertGreater(metrics['local_filter_build_seconds'], 0)
                        if strategy == 'bloom-local':
                            self.assertEqual(metrics['remote_filter_build_seconds'], 0)
                        else:
                            self.assertGreater(metrics['remote_filter_build_seconds'], 0)
                        self.assertAlmostEqual(metrics['filter_build_seconds'],
                                               metrics['local_filter_build_seconds']
                                               + metrics['remote_filter_build_seconds'])

    def test_low_overlap_saves_bytes_and_byte_counts_are_repeatable(self):
        """Count filter/setup overhead and confirm actual end-to-end savings."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate(tmp, 1000, .01, 128)
            baseline = run(*paths)
            for strategy in ('fixed', 'bloom', 'bloom-local'):
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
            for strategy in ('bloom', 'bloom-local'):
                bypass = run(*paths, strategy=strategy, selectivity=1)
                self.assertEqual(bypass['execution_strategy'], 'full')
                self.assertFalse(bypass['filter_applied'])
            with closing(sqlite3.connect(paths[0])) as db:
                db.execute('DELETE FROM records')
                db.commit()
            for strategy in ('fixed', 'bloom', 'bloom-local'):
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
            for strategy in ('full', 'fixed', 'bloom', 'bloom-local'):
                metrics = run(*paths, strategy=strategy)
                self.assertTrue(metrics['verified'])
                self.assertEqual(metrics['remote_records'], 0)
                self.assertEqual(metrics['result_rows'], 0)
                if strategy in ('bloom', 'bloom-local'):
                    self.assertEqual(metrics['execution_strategy'], 'empty')

    def test_local_only_matches_two_filter_transfer_and_sizing(self):
        """Removing the remote build preserves sizing, candidate counts and SQL rows."""
        for overlap in (0, .1, .8, 1):
            with self.subTest(overlap=overlap), tempfile.TemporaryDirectory() as tmp:
                paths = generate(tmp, 200, overlap, 32)
                original = run(*paths, strategy='bloom')
                local_only = run(*paths, strategy='bloom-local')
                self.assertEqual(local_only['sizing'], original['sizing'])
                for name in ('filter_bytes', 'transferred_records', 'nonmatching_records',
                             'result_rows', 'observed_false_positive_rate'):
                    self.assertEqual(local_only[name], original[name], name)
                self.assertTrue(local_only['verified'])
                self.assertEqual(local_only['execution_strategy'], 'bloom-local')
                self.assertEqual(local_only['remote_filter_build_seconds'], 0)
                self.assertEqual(local_only['filter_build_seconds'],
                                 local_only['local_filter_build_seconds'])
                # The longer strategy name is the only wire-format difference.
                self.assertEqual(local_only['application_bytes'] - original['application_bytes'],
                                 len('bloom-local') - len('bloom'))

    def test_worker_sends_identical_candidate_rows_without_remote_build(self):
        """Check actual candidate keys/payloads, including forced false positives."""
        import base64
        from unittest.mock import patch
        from bloomjoin.worker import serve

        with tempfile.TemporaryDirectory() as tmp:
            paths = generate(tmp, 100, .1, 8)
            # A tiny filter saturates: candidates include nonmatching keys too.
            bloom = BloomFilter(8, 1)
            for key in range(100):
                bloom.add(key)
            candidates = []
            for strategy in ('bloom', 'bloom-local'):
                request = {'strategy': strategy, 'bit_count': 8, 'hash_count': 1,
                           'filter': base64.b64encode(bloom.to_bytes()).decode('ascii')}
                with patch('bloomjoin.worker.socket.create_connection'), \
                        patch('bloomjoin.worker.Channel') as channel_class:
                    channel = channel_class.return_value
                    channel.receive.return_value = request
                    serve(str(paths[1]), ('127.0.0.1', 1))
                messages = [call.args[0] for call in channel.send.call_args_list]
                candidates.append([row for message in messages for row in message.get('rows', [])])
                if strategy == 'bloom-local':
                    self.assertEqual(float(messages[-1]['filter_build_seconds']), 0)
            self.assertGreater(len(candidates[0]), 10)
            self.assertEqual(candidates[0], candidates[1])
