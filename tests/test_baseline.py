"""Regression checks for baseline."""
import tempfile
import unittest
from pathlib import Path
from bloomjoin.data import generate
from bloomjoin.experiment import run


class BaselineTests(unittest.TestCase):
    """Verify the full-transfer control and reproducible synthetic inputs."""
    def test_reference_results_and_transfer_counts(self):
        """Check exact results and full row transfer at empty, disjoint, partial and full overlap."""
        for rows, overlap in ((0, 0), (20, 0), (20, 0.1), (20, 1)):
            with self.subTest(rows=rows, overlap=overlap), tempfile.TemporaryDirectory() as tmp:
                local, remote = generate(tmp, rows, overlap, 32, 42)
                metrics = run(local, remote)
                self.assertTrue(metrics["verified"])
                self.assertEqual(metrics["result_rows"], int(rows * overlap))
                self.assertEqual(metrics["transferred_records"], rows)
                self.assertEqual(metrics["nonmatching_records"], rows - int(rows * overlap))
                self.assertGreater(metrics["application_bytes"], 0)

    def test_generation_is_reproducible(self):
        """Compare complete database bytes from independently generated equal-seed datasets."""
        with tempfile.TemporaryDirectory() as tmp:
            first = generate(Path(tmp) / "a", 20, 0.5, 32, 7)
            second = generate(Path(tmp) / "b", 20, 0.5, 32, 7)
            for a, b in zip(first, second):
                self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_invalid_data_configuration(self):
        """Reject negative counts, impossible overlap and negative payload width."""
        for rows, overlap, width in ((-1, 0, 32), (1, 1.1, 32), (1, 0, -1)):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    generate(tmp, rows, overlap, width)


if __name__ == "__main__":
    unittest.main()
