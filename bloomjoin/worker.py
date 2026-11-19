"""The remote process owns the remote SQLite connection."""
import base64
from contextlib import closing
import socket
import sqlite3
from time import perf_counter
from .protocol import Channel, encode_json
from .strategies import BloomFilter


def sizing_statistics(db):
    """Scan rows with bounded memory; width includes one separator per row.

    Batch envelopes and framing are excluded from this estimate, but are counted
    in application_bytes when actually transmitted. Empty width is zero.
    """
    count = 0
    row_bytes = 0
    for row in db.execute("SELECT join_key, payload FROM records"):
        count += 1
        # Include serialized key/payload plus one separator, but no batch envelope.
        row_bytes += len(encode_json(row)) + 1
    return {"row_count": count, "mean_row_bytes": row_bytes / count if count else 0.0}


def serve(database, address):
    """Handle optional statistics, then filter and stream rows for one query.

    Both sites use the same dimensions and deterministic hashes. The second
    filter and AND follow the proposal; the exact SQL join remains authoritative.
    """
    with socket.create_connection(address, timeout=30) as connection:
        channel = Channel(connection)
        with closing(sqlite3.connect(database)) as db:
            request = channel.receive()
            # Only the cost policy (or explicit collection) requests statistics first.
            if request == {"request": "sizing"}:
                channel.send({"sizing": sizing_statistics(db)})
                request = channel.receive()
            strategy = request.get("strategy")
            filter_seconds = 0.0
            remote_count = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            if strategy == "full":
                # None disables membership testing so every remote row is sent.
                candidate = None
            elif strategy == "empty":
                # Keep the completion handshake even when no candidate scan is needed.
                channel.send({"done": True, "remote_records": remote_count,
                              "filter_build_seconds": format(0.0, "024.12f")})
                return
            elif strategy == "bloom":
                # Reuse the coordinator's dimensions; mismatched hashes/sizes lose safety.
                candidate = BloomFilter.from_bytes(request["bit_count"], request["hash_count"],
                                                   base64.b64decode(request["filter"], validate=True))
                built = perf_counter()
                remote_filter = BloomFilter(candidate.bit_count, candidate.hash_count)
                for (key,) in db.execute("SELECT join_key FROM records"):
                    remote_filter.add(key)
                # For keys inserted into remote_filter, this AND gives the same
                # decisions as the local filter alone; see docs/repository-review.md.
                candidate = candidate.intersection(remote_filter)
                filter_seconds = perf_counter() - built
            else:
                raise ValueError(f"Unknown strategy: {strategy!r}")
            cursor = db.execute("SELECT join_key, payload FROM records ORDER BY join_key")
            while True:
                batch = cursor.fetchmany(1000)  # Bound candidate memory per batch.
                if not batch:
                    break
                if candidate is not None:
                    # Keep only rows that might match a local key (false positives possible).
                    batch = [row for row in batch if candidate.might_contain(row[0])]
                    if not batch:
                        # Skip empty row messages, but continue scanning later batches.
                        continue
                channel.send({"rows": batch})
        channel.send({"done": True, "remote_records": remote_count,
                      # Fixed-width timing text keeps message size independent of jitter.
                      "filter_build_seconds": format(filter_seconds, "024.12f")})
