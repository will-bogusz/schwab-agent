"""
Output Formatting
-----------------
Consistent formatting helpers for CLI output.
"""

import json
import sys


def emit(data, raw: bool = False):
    """Output data. JSON if raw, else print as-is."""
    if raw:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


def emit_error(message: str, code: int = 1):
    """Print error to stderr and exit."""
    print(json.dumps({"error": message}, default=str), file=sys.stderr)
    sys.exit(code)


def fmt_currency(value) -> str:
    """Format a value as currency."""
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def fmt_percent(value) -> str:
    """Format a value as percentage with sign."""
    if value is None:
        return "N/A"
    return f"{value:+.2f}%"


def fmt_table(headers: list[str], rows: list[list], alignments: str | None = None) -> str:
    """
    Format data as an aligned table.

    Args:
        headers: Column header strings.
        rows: List of rows, each a list of values.
        alignments: String of '<' (left) and '>' (right) per column.
                    Defaults to left-align first col, right-align rest.
    """
    if not rows:
        return ""

    ncols = len(headers)
    if alignments is None:
        alignments = "<" + ">" * (ncols - 1)

    # Convert all values to strings
    str_rows = [[str(v) for v in row] for row in rows]

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, val in enumerate(row):
            if i < ncols:
                widths[i] = max(widths[i], len(val))

    # Build format string
    def fmt_cell(val: str, width: int, align: str) -> str:
        if align == ">":
            return val.rjust(width)
        return val.ljust(width)

    lines = []

    # Header
    header_line = "  ".join(
        fmt_cell(h, widths[i], alignments[i]) for i, h in enumerate(headers)
    )
    lines.append(header_line)

    # Separator
    lines.append("-" * len(header_line))

    # Data rows
    for row in str_rows:
        # Pad row if needed
        padded = row + [""] * (ncols - len(row))
        line = "  ".join(
            fmt_cell(padded[i], widths[i], alignments[i]) for i in range(ncols)
        )
        lines.append(line)

    return "\n".join(lines)
