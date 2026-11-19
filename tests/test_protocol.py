"""Regression checks for protocol."""
import json
import socket
import unittest
import struct
from bloomjoin.protocol import Channel, MAX_MESSAGE_BYTES, encode_json


class ProtocolTests(unittest.TestCase):
    """Check framing, partial reads, resource limits and exact byte accounting."""
    def test_sender_pacing_preserves_frames_and_charges_header_once(self):
        """Simulated time follows framed bytes/rate with bounded incremental writes."""
        from unittest.mock import Mock, patch
        now = [0.0]

        def advance(seconds):
            """Advance a fake clock instead of making this unit test sleep."""
            now[0] += seconds

        connection = Mock()
        message = {'payload': 'x' * 20000}
        body = encode_json(message)
        expected = struct.pack('!I', len(body)) + body
        with patch('bloomjoin.protocol.perf_counter', side_effect=lambda: now[0]), \
                patch('bloomjoin.protocol.sleep', side_effect=advance) as sleeper:
            channel = Channel(connection, bandwidth_mbps=1)
            channel.send(message)
        chunks = [bytes(call.args[0]) for call in connection.sendall.call_args_list]
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(map(len, chunks)), 6250)
        self.assertEqual(b''.join(chunks), expected)
        self.assertEqual(channel.bytes_sent, len(expected))
        self.assertAlmostEqual(now[0], len(expected) / 125000)
        self.assertTrue(all(0 < call.args[0] <= .050001 for call in sleeper.call_args_list))

    def test_unlimited_channel_does_not_sleep(self):
        """Default behavior remains a direct send without simulated delays."""
        from unittest.mock import Mock, patch
        connection = Mock()
        with patch('bloomjoin.protocol.sleep') as sleeper:
            Channel(connection).send({'done': True})
        sleeper.assert_not_called()
        connection.sendall.assert_called_once()

    def test_invalid_bandwidth_rejected(self):
        """Reject zero, negative, nonnumeric, nonfinite and unsupported tiny rates."""
        for value in (0, -1, .0001, True, '10', float('nan'), float('inf'), 10**1000):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Channel(None, bandwidth_mbps=value)

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
