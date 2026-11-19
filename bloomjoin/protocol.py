"""Length-prefixed UTF-8 JSON; counters include the four-byte prefix.

Each endpoint counts its own sends/receives. Report one endpoint's sum to
avoid counting the same wire bytes twice. TCP/IP headers are excluded.
"""
import json
import struct
import math
from time import perf_counter, sleep

# Accommodates the maximum 8 MiB filter after base64/JSON expansion.
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


def validate_bandwidth(bandwidth_mbps):
    """Accept unlimited (None) or a finite rate of at least 0.001 megabits/s."""
    if bandwidth_mbps is None:
        return
    if (isinstance(bandwidth_mbps, bool)
            or not isinstance(bandwidth_mbps, (int, float))):
        raise ValueError("bandwidth_mbps must be finite and at least 0.001, or None")
    try:
        valid = math.isfinite(bandwidth_mbps * 125000) and bandwidth_mbps >= 0.001
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("bandwidth_mbps must be finite and at least 0.001, or None")


def network_description(bandwidth_mbps):
    """Label simulated application transmission separately from real networking."""
    return ("loopback TCP with simulated application-bandwidth delay"
            if bandwidth_mbps is not None else "loopback TCP")


def encode_json(message):
    """The shared wire serializer, also used for row-width estimation."""
    # Compact separators avoid whitespace; UTF-8 turns JSON text into socket bytes.
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


class Channel:
    """One synchronous framed connection and its application-byte counters."""

    def __init__(self, connection, bandwidth_mbps=None):
        """Wrap an owned-by-caller socket with initially empty counters."""
        validate_bandwidth(bandwidth_mbps)
        self.connection = connection
        # Decimal megabits/s -> bytes/s. Each endpoint delays its own sends only.
        self.bytes_per_second = bandwidth_mbps * 125000 if bandwidth_mbps is not None else None
        self.bytes_sent = 0
        self.bytes_received = 0

    def send(self, message):
        """Serialize and send one bounded frame, counting successful sends."""
        body = encode_json(message)
        if len(body) > MAX_MESSAGE_BYTES:
            raise ValueError("Message exceeds maximum frame size")
        # !I is a four-byte unsigned length in network (big-endian) byte order.
        packet = struct.pack("!I", len(body)) + body
        # TCP is a byte stream: sendall handles partial writes of the frame.
        if self.bytes_per_second is None:
            self.connection.sendall(packet)
        else:
            # Pace before writes so the peer cannot process the whole frame early.
            # Small chunks keep reads progressing even for a large, slow filter.
            chunk_size = max(1, min(65536, int(self.bytes_per_second * 0.05)))
            started = perf_counter()
            for offset in range(0, len(packet), chunk_size):
                end = min(len(packet), offset + chunk_size)
                # Deadlines avoid accumulating socket/loop overhead inside a frame.
                remaining = started + end / self.bytes_per_second - perf_counter()
                if remaining > 0:
                    sleep(remaining)
                self.connection.sendall(memoryview(packet)[offset:end])
        self.bytes_sent += len(packet)

    def _read(self, size):
        """Read exactly size bytes despite arbitrary TCP fragmentation."""
        data = bytearray()
        while len(data) < size:
            # One recv need not return the full requested body, even on loopback.
            chunk = self.connection.recv(size - len(data))
            if not chunk:
                raise ConnectionError("Peer closed before the message was complete")
            data.extend(chunk)
        # Successful queries count each header/body once at this endpoint.
        self.bytes_received += size
        return bytes(data)

    def receive(self):
        """Decode one bounded frame; reject incomplete or malformed messages."""
        size = struct.unpack("!I", self._read(4))[0]
        # Validate the advertised size before attempting to read its body.
        if size > MAX_MESSAGE_BYTES:
            raise ValueError("Message exceeds maximum frame size")
        return json.loads(self._read(size).decode("utf-8"))
