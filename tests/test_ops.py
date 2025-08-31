import unittest
from bmp2c.ops import (
    apply_edits,
    EditOptions,
    op_flip_h,
    op_flip_v,
    op_rotate,
    op_trim,
    op_pad,
)

class TestOps(unittest.TestCase):
    def setUp(self):
        # 3x2 bits
        self.bits = [
            [0, 1, 0],
            [1, 0, 1],
        ]

    def test_flip_h(self):
        out = op_flip_h(self.bits)
        self.assertEqual(out, [
            [0, 1, 0][::-1],
            [1, 0, 1][::-1],
        ])

    def test_flip_v(self):
        out = op_flip_v(self.bits)
        self.assertEqual(out, [self.bits[1], self.bits[0]])

    def test_rotate_180(self):
        out = op_rotate(self.bits, 180)
        # rotate 180 is flip_h then flip_v
        self.assertEqual(out, [[1, 0, 1][::-1], [0, 1, 0][::-1]][::-1])

    def test_trim_noop_on_all_white(self):
        w = [[0, 0, 0], [0, 0, 0]]
        out = op_trim(w)
        self.assertEqual(out, w)  # stays same (avoid 0x0)

    def test_pad(self):
        out = op_pad(self.bits, 1, 0, 1, 0)
        self.assertEqual(len(out), 3)  # +1 top
        self.assertEqual(len(out[1]), 4)  # +1 left

    def test_apply_edits_chain(self):
        opts = EditOptions(invert=True, flip_h=True, pad_left=1)
        out = apply_edits(self.bits, opts)
        self.assertEqual(len(out[0]), 4)  # padded
