import unittest
from pathlib import Path
from bmp2c.core import _casefold_key


class TestSort(unittest.TestCase):
    def test_case_insensitive_stable(self):
        a = Path("Foo.bmp")
        b = Path("foo.bmp")
        c = Path("bar.bmp")
        arr = sorted([a, b, c], key=_casefold_key)
        # 'bar' first, then 'foo' (original order Foo before foo for tie-break)
        self.assertEqual([p.name for p in arr], ["bar.bmp", "Foo.bmp", "foo.bmp"])
