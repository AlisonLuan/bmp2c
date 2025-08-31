from __future__ import annotations

import re
from typing import Iterable, List


def sanitize_symbol(name: str) -> str:
    """
    Sanitize into a valid C identifier:
    - Replace invalid chars with '_'
    - First char must be [A-Za-z_]
    - Preserve case
    """
    if not name:
        return "_"
    # Replace non-alnum/underscore with underscore
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    # If first char invalid, prefix underscore
    if not re.match(r"[A-Za-z_]", name[0]):
        name = "_" + name
    return name


def upper_macro(name: str) -> str:
    """
    Upper-case macro version of a (already sanitized) symbol.
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", name).upper()


def format_bytes_as_c_array(
    data: Iterable[int],
    items_per_line: int = 12,
) -> str:
    """
    Deterministic hex formatting: uppercase 0x00..0xFF, items_per_line per line.
    """
    items: List[str] = [f"0x{b:02X}" for b in data]
    lines = []
    for i in range(0, len(items), items_per_line):
        lines.append("    " + ", ".join(items[i : i + items_per_line]))
    return ",\n".join(lines)
