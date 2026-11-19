"""Packed compatible Bloom filters and fixed/cost-selected sizing policies."""
import math
import hashlib
from typing import NamedTuple


MAX_FILTER_BITS = 8 * 1024 * 1024 * 8  # 8 MiB packed; no allocation here.
MAX_HASH_COUNT = 32


class FilterSize(NamedTuple):
    """Wire-compatible dimensions; (0, 0) requests a full-transfer fallback."""
    bit_count: int
    hash_count: int


class BloomFilter:
    """A deterministic integer-key filter; positive answers require an exact join."""

    def __init__(self, bit_count, hash_count, bits=None):
        """Allocate packed bits or restore a payload, enforcing resource limits."""
        if (isinstance(bit_count, bool) or not isinstance(bit_count, int)
                or not 0 < bit_count <= MAX_FILTER_BITS
                or isinstance(hash_count, bool) or not isinstance(hash_count, int)
                or not 0 < hash_count <= MAX_HASH_COUNT):
            raise ValueError("bit count and hash count must be positive bounded integers")
        self.bit_count = bit_count
        self.hash_count = hash_count
        nbytes = math.ceil(bit_count / 8)  # A partial final byte still needs storage.
        if bits is None:
            self._bits = bytearray(nbytes)
        else:
            if len(bits) != nbytes:
                raise ValueError("bits length does not match bit_count")
            self._bits = bytearray(bits)  # Copy so callers cannot mutate our storage.

    def _positions(self, key):
        """Yield double-hash positions identically in independently spawned workers."""
        # Stable hashes so local and remote processes agree (never use hash()).
        raw = str(key).encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        # Split one digest into a starting position and a step for double hashing.
        h1 = int.from_bytes(digest[0:8], "big")
        h2 = int.from_bytes(digest[8:16], "big") or 1
        # Yield lazily so a negative membership test can stop at its first zero.
        for i in range(self.hash_count):
            yield (h1 + i * h2) % self.bit_count

    def add(self, key):
        """Set every position for a key; repeated insertions are harmless."""
        for p in self._positions(key):
            # p // 8 chooses a byte; shifting 1 by p % 8 chooses its bit.
            self._bits[p // 8] |= 1 << (p % 8)

    def might_contain(self, key):
        """Return False for a definite miss and True for a possible match."""
        for p in self._positions(key):
            # Any missing bit proves absence; all set bits only suggest membership.
            if (self._bits[p // 8] & (1 << (p % 8))) == 0:
                return False
        return True

    def to_bytes(self):
        """Copy packed storage for transport without exposing mutable state."""
        return bytes(self._bits)

    @classmethod
    def from_bytes(cls, bit_count, hash_count, data):
        """Restore packed bits with the same dimensions and hash algorithm."""
        return cls(bit_count, hash_count, bits=data)

    def intersection(self, other):
        """AND compatible arrays; this approximates intersection, not an exact set."""
        if self.bit_count != other.bit_count or self.hash_count != other.hash_count:
            raise ValueError("filters must share bit_count and hash_count")
        # Matching keys retain every selected bit; collisions can also survive AND.
        combined = bytearray(a & b for a, b in zip(self._bits, other._bits))
        return BloomFilter(self.bit_count, self.hash_count, bits=combined)


def fixed_filter_size(local_count):
    """Use ten bits per local key, byte alignment, and the nearest optimal k."""
    if isinstance(local_count, bool) or not isinstance(local_count, int) or local_count < 0:
        raise ValueError("local_count must be a nonnegative integer")
    if not local_count:
        return FilterSize(0, 0)
    # Adding seven before integer division rounds ten bits/key up to whole bytes.
    bits = min(MAX_FILTER_BITS, 8 * ((10 * local_count + 7) // 8))
    # Optimal continuous k is (m/n) ln(2); round to a bounded integer.
    hashes = max(1, min(MAX_HASH_COUNT, math.floor(bits / local_count * math.log(2) + 0.5)))
    return FilterSize(bits, hashes)


def choose_filter_size(local_count, remote_count, record_width, *, selectivity=0.0):
    """Return (bits, hashes) using Section 4.1's continuous cost optimum.

    record_width is mean serialized remote-row BYTES. selectivity is the
    estimated fraction of remote rows matching local keys, not measured overlap.
    The default assumes disjoint keys. See docs/cost-sizing.md for adaptations.
    (0, 0) means bypass the filter, or short-circuit an empty join.
    """
    for name, value in (("local_count", local_count), ("remote_count", remote_count)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    for name, value in (("record_width", record_width), ("selectivity", selectivity)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"{name} must be a finite number")
    if record_width <= 0 or not 0 <= selectivity <= 1:
        raise ValueError("record_width must be positive; selectivity must be in [0, 1]")
    # Empty inputs need no filter; complete expected overlap offers no pruning.
    if not local_count or not remote_count or selectivity == 1:
        return FilterSize(0, 0)

    # Generalize r to n inserted keys and R probed rows. Logs avoid overflow
    # from multiplying huge counts and widths. Width is converted to bits.
    ln2 = math.log(2)
    # This is ln(8 * R * width * (1-selectivity) * ln(2)^2 / n).
    # log1p(-selectivity) remains accurate when selectivity is close to zero.
    log_factor = (math.log(remote_count) - math.log(local_count)
                  + math.log1p(-selectivity) + math.log(record_width)
                  + math.log(8) + 2 * math.log(ln2))
    # A nonpositive optimum cannot justify allocating a positive-size filter.
    if log_factor <= 0:
        return FilterSize(0, 0)
    # Compare against the cap before multiplying by an arbitrarily large n.
    if math.log(local_count) + math.log(log_factor / (ln2 * ln2)) >= math.log(MAX_FILTER_BITS):
        bits = MAX_FILTER_BITS
    else:
        optimum = local_count * (log_factor / (ln2 * ln2))
        bits = min(MAX_FILTER_BITS, max(8, 8 * math.ceil(optimum / 8)))
    hashes = max(1, min(MAX_HASH_COUNT, math.floor((bits / local_count) * ln2 + 0.5)))
    return FilterSize(bits, hashes)
