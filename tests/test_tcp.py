"""Offline byte-framing and completion/error tests."""
import json
import struct
import unittest
from liminal_desk_cli.transports.base import send_complete
from liminal_desk_cli.transports.tcp import encode_frame, TcpReceipt, TcpClient


class TcpTests(unittest.TestCase):
    def test_length_prefix_is_big_endian_payload_bytes(self):
        payload={'device_id':'mm-1','value':'µ','timestamp_ms':123}
        frame=encode_frame(payload)
        self.assertEqual(struct.unpack('!I',frame[:4])[0],len(frame)-4)
        self.assertEqual(json.loads(frame[4:].decode('utf-8')),payload)
        self.assertNotEqual(frame[-1:],b'\n')

    def test_frame_limit_and_nonfinite_value(self):
        frame=encode_frame({'x':1})
        self.assertEqual(encode_frame({'x':1},len(frame)-4),frame)
        with self.assertRaisesRegex(ValueError,'limit'):
            encode_frame({'x':1},len(frame)-5)
        with self.assertRaises(ValueError):
            encode_frame({'x':float('inf')})

    def test_completion_and_error_are_explicit(self):
        receipt=TcpReceipt()
        self.assertFalse(send_complete(receipt))
        receipt.finish()
        self.assertTrue(send_complete(receipt))
        failed=TcpReceipt();failed.finish('partial write')
        with self.assertRaisesRegex(RuntimeError,'partial write'):
            send_complete(failed)

    def test_dry_run_validates_frames_and_close_is_idempotent(self):
        client=TcpClient('localhost',8080,dry_run=True,max_frame_bytes=10)
        with self.assertRaisesRegex(RuntimeError,'connection lost'):
            client.send('',{})
        client.connect()
        self.assertTrue(client.ready)
        self.assertIsNone(client.send('',{}))
        with self.assertRaises(ValueError):
            client.send('',{'large':'x'*100})
        client.close();client.close()
        self.assertFalse(client.connected)
