"""Length-prefixed UTF-8 JSON; counters include the four-byte prefix.

Each endpoint counts its own sends/receives. Report one endpoint's sum to
avoid counting the same wire bytes twice. TCP/IP headers are excluded.
"""
import json
import struct

# Accommodates the maximum 8 MiB filter after base64/JSON expansion.
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


def encode_json(message):
    """The shared wire serializer, also used for row-width estimation."""
    # Compact separators avoid whitespace; UTF-8 turns JSON text into socket bytes.
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


class Channel:
    """One synchronous framed connection and its application-byte counters."""

    def __init__(self, connection):
        """Wrap an owned-by-caller socket with initially empty counters."""
        self.connection = connection
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
        self.connection.sendall(packet)
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
