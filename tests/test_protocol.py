"""Regression checks for protocol."""
import json
import socket
import unittest
import struct
from bloomjoin.protocol import Channel, MAX_MESSAGE_BYTES


class ProtocolTests(unittest.TestCase):
    """Check framing, partial reads, resource limits and exact byte accounting."""
    def test_oversized_incoming_frame_rejected_before_body_read(self):
        """A malicious length cannot trigger an unbounded allocation or read."""
        left, right = socket.socketpair()
        with left, right:
            left.sendall(struct.pack('!I', MAX_MESSAGE_BYTES + 1))
            with self.assertRaises(ValueError):
                Channel(right).receive()

    def test_fragmented_reads(self):
        """Read a frame correctly even when recv returns just one byte."""
        from unittest.mock import Mock
        packet = struct.pack('!I', 2) + b'{}'
        connection = Mock()
        connection.recv.side_effect = [bytes([byte]) for byte in packet]
        channel = Channel(connection)
        self.assertEqual(channel.receive(), {})
        self.assertEqual(channel.bytes_received, len(packet))

    def test_round_trip_and_exact_byte_accounting(self):
        """Compare the actual frame counters with independently serialized expected bytes."""
        left, right = socket.socketpair()
        with left, right:
            sender, receiver = Channel(left), Channel(right)
            message = {"rows": [[7, "payload"]]}
            sender.send(message)
            self.assertEqual(receiver.receive(), message)
            expected = 4 + len(json.dumps(message, separators=(",", ":")).encode("utf-8"))
            self.assertEqual(sender.bytes_sent, expected)
            self.assertEqual(receiver.bytes_received, expected)

    def test_truncated_message_raises(self):
        """Report early EOF rather than accepting an incomplete frame."""
        left, right = socket.socketpair()
        with left, right:
            left.sendall(b"\x00\x00")
            left.shutdown(socket.SHUT_WR)
            with self.assertRaises(ConnectionError):
                Channel(right).receive()
