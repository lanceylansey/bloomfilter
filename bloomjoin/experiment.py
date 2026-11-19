"""Verified full, fixed-size Bloom, and cost-selected Bloom distributed joins."""
from contextlib import closing
import multiprocessing
import socket
import sqlite3
import base64
from pathlib import Path
from time import perf_counter
from .protocol import Channel, validate_bandwidth, network_description
from .worker import serve
from .strategies import FilterSize, choose_filter_size, fixed_filter_size, BloomFilter

STRATEGIES = ("full", "fixed", "bloom", "bloom-local")


# Every strategy returns the same columns/order so complete results are comparable.
PROJECTION = "SELECT l.join_key, l.payload, r.payload FROM records l JOIN incoming r ON l.join_key = r.join_key ORDER BY l.join_key"


def reference_join(local_path, remote_path):
    """Compute the exact oracle locally, outside measured time and network bytes."""
    # Validation only: this local reference is outside measured query time/bytes.
    with closing(sqlite3.connect(local_path)) as db:
        db.execute("ATTACH DATABASE ? AS remote", (str(remote_path),))
        return db.execute("SELECT l.join_key, l.payload, r.payload FROM records l JOIN remote.records r ON l.join_key = r.join_key ORDER BY l.join_key").fetchall()


def run(local_path, remote_path, strategy="full", *, collect_sizing=False, selectivity=0.0,
        bandwidth_mbps=None):
    """Run one query against an independent remote process and verify its result.

    bloom selects size from the cost model; fixed uses ten bits per local key.
    bloom-local uses the same cost-selected size but skips the remote build/AND.
    selectivity is an estimate supplied by the caller, never measured overlap.
    collect_sizing adds a measured metadata exchange even to full/fixed runs.
    bandwidth_mbps adds simulated transmission delay at both senders, in query time.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy!r}")
    # Validate even when empty inputs would otherwise bypass the sizing policy.
    choose_filter_size(0, 0, 1, selectivity=selectivity)
    validate_bandwidth(bandwidth_mbps)
    for path in (local_path, remote_path):
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    # Spawn starts a fresh interpreter; the child opens its own database connection.
    context = multiprocessing.get_context("spawn")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))  # Port zero asks the OS for a free local port.
        listener.listen(1)
        listener.settimeout(30)
        process = context.Process(target=serve, args=(str(remote_path), listener.getsockname(),
                                                       bandwidth_mbps))
        process.start()  # The worker connects back to the address above.
        try:
            connection, _ = listener.accept()
            with connection, closing(sqlite3.connect(local_path)) as db:
                connection.settimeout(30)
                channel = Channel(connection, bandwidth_mbps=bandwidth_mbps)
                # TEMP keeps received candidates separate from persistent local data.
                db.execute("CREATE TEMP TABLE incoming (join_key INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                # Startup/connection setup is excluded; scans and query work follow.
                start = perf_counter()
                sizing = None  # Absent for a plain full-transfer baseline.
                size = FilterSize(0, 0)
                local_count = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                remote_count = None
                metadata_bytes = 0
                if collect_sizing or strategy in ("bloom", "bloom-local"):
                    # Metadata is part of the measured exchange, not free optimizer input.
                    before_metadata = channel.bytes_sent + channel.bytes_received
                    channel.send({"request": "sizing"})
                    remote_stats = channel.receive()["sizing"]
                    # The counter delta includes both framed metadata messages.
                    metadata_bytes = channel.bytes_sent + channel.bytes_received - before_metadata
                    remote_count = remote_stats["row_count"]
                    if not local_count or not remote_stats["row_count"]:
                        size = FilterSize(0, 0)
                    else:
                        size = choose_filter_size(local_count, remote_stats["row_count"],
                                                  remote_stats["mean_row_bytes"], selectivity=selectivity)
                    sizing = {"local_count": local_count, **remote_stats,
                              "selectivity_estimate": selectivity,
                              "bit_count": size.bit_count, "hash_count": size.hash_count,
                              "metadata_application_bytes": metadata_bytes,
                              "filter_applied": False}
                if strategy == "fixed":
                    # This method needs no remote width/cardinality scan by default.
                    size = fixed_filter_size(local_count)
                    sizing = {**(sizing or {}), "local_count": local_count,
                              "bit_count": size.bit_count, "hash_count": size.hash_count,
                              "metadata_application_bytes": metadata_bytes,
                              "filter_applied": False}
                request = {"strategy": "full"}
                filter_seconds = 0.0
                filter_bytes = 0
                # None means remote cardinality was not requested, not an empty table.
                short_circuit = strategy != "full" and (local_count == 0 or remote_count == 0)
                if short_circuit:
                    request = {"strategy": "empty"}
                elif strategy != "full" and size.bit_count:
                    built = perf_counter()
                    bloom = BloomFilter(size.bit_count, size.hash_count)
                    for (key,) in db.execute("SELECT join_key FROM records"):
                        bloom.add(key)
                    data = bloom.to_bytes()  # Packed bytes, before base64/JSON expansion.
                    filter_seconds = perf_counter() - built
                    filter_bytes = len(data)
                    # Base64 represents binary storage as JSON-safe ASCII text.
                    request = {"strategy": "bloom-local" if strategy == "bloom-local" else "bloom",
                               "bit_count": size.bit_count,
                               "hash_count": size.hash_count,
                               "filter": base64.b64encode(data).decode("ascii")}
                    sizing["filter_applied"] = True
                channel.send(request)
                # Stream into SQLite rather than accumulating all candidates in Python.
                transferred = 0
                remote_filter_seconds = 0.0
                filter_applied = request["strategy"] in ("bloom", "bloom-local")
                while True:
                    message = channel.receive()
                    if message.get("done"):
                        remote_filter_seconds = float(message.get("filter_build_seconds", 0.0))
                        remote_count = message["remote_records"]
                        break
                    rows = message["rows"]
                    db.executemany("INSERT INTO incoming VALUES (?, ?)", rows)
                    transferred += len(rows)
                # SQL equality removes false positives; ordering supports exact checking.
                result = db.execute(PROJECTION).fetchall()
                elapsed = perf_counter() - start
                metrics = {
                    "strategy": strategy,
                    "network": network_description(bandwidth_mbps),
                    "bandwidth_mbps": bandwidth_mbps,
                    "application_bytes": channel.bytes_sent + channel.bytes_received,
                    "query_seconds": elapsed,
                    # Sum wall-clock build intervals already included in query_seconds.
                    "filter_build_seconds": filter_seconds + remote_filter_seconds,
                    "local_filter_build_seconds": filter_seconds,
                    "remote_filter_build_seconds": remote_filter_seconds,
                    "filter_bytes": filter_bytes,
                    "filter_applied": filter_applied,
                    "execution_strategy": request["strategy"],
                    "remote_records": remote_count,
                    "rejected_records": remote_count - transferred,
                    "transferred_records": transferred,
                    # Unique keys give one result per true matching remote candidate.
                    "nonmatching_records": transferred - len(result),
                    "result_rows": len(result),
                    "observed_false_positive_rate": (
                        (transferred - len(result)) / (remote_count - len(result))
                        if filter_applied and remote_count > len(result) else None),
                }
                if sizing is not None:
                    metrics["sizing"] = sizing
            # A correct-looking result is insufficient if the worker failed to exit.
            process.join(timeout=30)
            if process.is_alive() or process.exitcode != 0:
                raise RuntimeError("Remote worker did not exit successfully")
        finally:
            # Reap the child on errors as well, avoiding orphaned worker processes.
            if process.is_alive():
                process.terminate()
            process.join()
    # Reference validation is intentionally outside measured time and socket bytes.
    expected = reference_join(local_path, remote_path)
    if result != expected:
        raise AssertionError("Distributed result differs from reference SQL join")
    metrics["verified"] = True
    return metrics
