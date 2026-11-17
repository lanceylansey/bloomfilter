"""Extension points for Bloom filtering and cost-selected sizing."""
import math
import hashlib
from typing import NamedTuple


MAX_FILTER_BITS = 8 * 1024 * 1024 * 8  # 8 MiB packed; no allocation here.
MAX_HASH_COUNT = 32


class FilterSize(NamedTuple):
    bit_count: int
    hash_count: int


class BloomFilter:
    def __init__(self, bit_count, hash_count, bits=None):
        if bit_count <= 0 or hash_count <= 0:
            raise ValueError("bit count and hash count must be positive")
        self.bit_count = bit_count
        self.hash_count = hash_count
        nbytes = math.ceil(bit_count / 8)
        if bits is None:
            self._bits = bytearray(nbytes)
        else:
            if len(bits) != nbytes:
                raise ValueError("bits length does not match bit_count")
            self._bits = bytearray(bits)

    def _positions(self, key):
        # Stable hashes so local and remote processes agree (never use hash()).
        raw = str(key).encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        h1 = int.from_bytes(digest[0:8], "big")
        h2 = int.from_bytes(digest[8:16], "big")
        return [((h1 + i * h2) % self.bit_count) for i in range(self.hash_count)]

    def add(self, key):
        for p in self._positions(key):
            self._bits[p // 8] |= 1 << (p % 8)

    def might_contain(self, key):
        for p in self._positions(key):
            if (self._bits[p // 8] & (1 << (p % 8))) == 0:
                return False
        return True

    def to_bytes(self):
        return bytes(self._bits)

    @classmethod
    def from_bytes(cls, bit_count, hash_count, data):
        return cls(bit_count, hash_count, bits=data)

    def intersection(self, other):
        if self.bit_count != other.bit_count or self.hash_count != other.hash_count:
            raise ValueError("filters must share bit_count and hash_count")
        combined = bytearray(a & b for a, b in zip(self._bits, other._bits))
        return BloomFilter(self.bit_count, self.hash_count, bits=combined)


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
    if not local_count or not remote_count or selectivity == 1:
        return FilterSize(0, 0)

    # Generalize r to n inserted keys and R probed rows. Logs avoid overflow
    # from multiplying huge counts and widths. Width is converted to bits.
    ln2 = math.log(2)
    log_factor = (math.log(remote_count) - math.log(local_count)
                  + math.log1p(-selectivity) + math.log(record_width)
                  + math.log(8) + 2 * math.log(ln2))
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
