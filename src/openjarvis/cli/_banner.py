"""Startup banner — AURA wordmark + tagline."""

from __future__ import annotations

_WORDMARK = (
    "     _   _   _ ____      _    ",
    "    / \\ | | | |  _ \\    / \\   ",
    "   / _ \\| | | | |_) |  / _ \\  ",
    "  / ___ \\ |_| |  _ <  / ___ \\ ",
    " /_/   \\_\\___/|_| \\_\\/_/   \\_\\",
)

_TAGLINE = "AURA — Personal AI, On Personal Devices"


def print_banner(quiet: bool = False) -> None:
    """Print the AURA startup banner. No-op when quiet."""
    if quiet:
        return
    try:
        from rich.console import Console

        console = Console()
        for line in _WORDMARK:
            console.print(line, style="bold bright_cyan", highlight=False, markup=False)
        console.print(f"  {_TAGLINE}", style="bold magenta", highlight=False, markup=False)
        console.print()
    except ImportError:
        for line in _WORDMARK:
            print(line)
        print(f"  {_TAGLINE}")
        print()
