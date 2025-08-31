import unittest
from bmp2c.core import pack_row_major_lsb_first, bytes_per_image


class TestPacking(unittest.TestCase):
    def test_diagonal_8x8(self):
        # 8x8 with a diagonal of black pixels (1s), top-left -> bottom-right.
        bits = []
        for y in range(8):
            row = [1 if x == y else 0 for x in range(8)]
            bits.append(row)

        data = pack_row_major_lsb_first(bits)
        # For each row, exactly one bit set in its own byte: bit index = x (== y)
        # row 0 -> 0b00000001 = 0x01, row 1 -> 0x02, ..., row 7 -> 0x80
        expected = bytes([1 << i for i in range(8)])
        self.assertEqual(data, expected)
        self.assertEqual(bytes_per_image(8, 8), 8)

    def test_width_not_multiple_of_8(self):
        # 10x2: first row two black pixels at x=0,1; second row black at x=9
        bits = [
            [1, 1, 0, 0, 0, 0, 0, 0, 0, 0],  # row0 => byte0: bits 0..7 -> 0b00000011=0x03; byte1: x=8,9 -> 0b00000000=0x00
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 1],  # row1 => byte0: 0x00; byte1: bit1 set (x=9 -> bit1) => 0x02
        ]
        data = pack_row_major_lsb_first(bits)
        self.assertEqual(data, bytes([0x03, 0x00, 0x00, 0x02]))
        self.assertEqual(bytes_per_image(10, 2), 4)
