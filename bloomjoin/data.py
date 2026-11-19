"""Reproducible data with unique, non-null integer keys."""
from contextlib import closing
import random
import sqlite3
from pathlib import Path


def generate(directory, rows=1000, overlap=0.1, payload_bytes=32, seed=42):
    """Create equal-sized sites with exactly floor(rows * overlap) shared keys.

    Existing records tables in local.sqlite and remote.sqlite are replaced.
    ASCII payload length equals its UTF-8 byte width; the wire row is wider.
    """
    # Reject booleans explicitly: Python otherwise treats True as the integer 1.
    if (isinstance(rows, bool) or not isinstance(rows, int)
            or isinstance(payload_bytes, bool) or not isinstance(payload_bytes, int)
            or isinstance(overlap, bool) or not isinstance(overlap, (int, float))
            or rows < 0 or not 0 <= overlap <= 1 or payload_bytes < 0):
        raise ValueError("rows and payload size must be nonnegative; overlap must be 0..1")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)  # A private generator makes equal seeds reproducible.
    # Distinct ranges ensure that only the sampled local keys overlap.
    shared = int(rows * overlap)  # Fractional matches are rounded down to whole rows.
    local_keys = list(range(rows))
    # Sample shared keys without replacement, then fill with remote-only keys.
    remote_keys = rng.sample(local_keys, shared) + list(range(rows, 2 * rows - shared))
    paths = []
    for name, keys in (("local", local_keys), ("remote", remote_keys)):
        rng.shuffle(keys)
        path = directory / (name + ".sqlite")
        # The connection context commits inserts; closing also releases the file.
        with closing(sqlite3.connect(path)) as db, db:
            # Regeneration replaces only this experiment's records table.
            db.execute("DROP TABLE IF EXISTS records")
            db.execute("CREATE TABLE records (join_key INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            # Generate rows lazily; l/r payload markers distinguish the two sites.
            db.executemany("INSERT INTO records VALUES (?, ?)",
                           ((key, name[0] * payload_bytes) for key in keys))
        paths.append(path)
    return tuple(paths)
