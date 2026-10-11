import unittest

from opengk6x import protocol as p

# Replies from the user's GK104 Pro (wired, 2026-10-11), first 24 bytes; the rest of each report is zero.
REPLY_MATRIX = bytes.fromhex("01 09 01 00 00 00 35 9a 10 08") + bytes(54)
REPLY_FIRMWARE = bytes.fromhex("01 01 01 00 00 00 f6 e8 11 33 22 84 76 05") + bytes(50)
REPLY_MODEL = bytes.fromhex("01 08 01 00 00 00 ff b3 08 01 26 27 ff ff 8d a7") + bytes(48)


class TestFraming(unittest.TestCase):
    def test_crc_reference_value(self):
        self.assertEqual(p.crc16(b"123456789"), 0x29B1)   # CRC-16/CCITT-FALSE check value

    def test_packet_layout(self):
        pkt = p.packet(0x22, 0x01, header=b"\x38\x00\x38", payload=b"\xAA" * 56)
        self.assertEqual(len(pkt), 64)
        self.assertEqual(pkt[:6], bytes([0x22, 0x01, 0x38, 0x00, 0x38, 0x00]))
        self.assertEqual(pkt[8:], b"\xAA" * 56)
        self.assertTrue(p.crc_ok(pkt))

    def test_too_long(self):
        with self.assertRaises(ValueError):
            p.packet(0x01, payload=bytes(57))

    def test_captured_replies_have_valid_crc(self):
        for r in (REPLY_MATRIX, REPLY_FIRMWARE, REPLY_MODEL):
            self.assertTrue(p.crc_ok(r))
        bad = bytearray(REPLY_MODEL)
        bad[10] ^= 1
        self.assertFalse(p.crc_ok(bad))


class TestInfo(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(p.parse_matrix(REPLY_MATRIX), (16, 8))
        fw = p.parse_firmware(REPLY_FIRMWARE)
        self.assertEqual(fw.id, 0x84223311)
        self.assertEqual(fw.version, "v5.118")
        self.assertEqual(p.parse_model(REPLY_MODEL), 656802056)
        self.assertTrue(p.is_reply(REPLY_MODEL, p.OP_INFO, p.INFO_MODEL))

    def test_model_check(self):
        bad = bytearray(REPLY_MODEL)
        bad[8] ^= 1
        with self.assertRaises(ValueError):
            p.parse_model(bytes(bad))


if __name__ == "__main__":
    unittest.main()
