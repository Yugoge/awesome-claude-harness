"""The harness switch's one question: is this harness home switched off (/harness off)?

The owner's typed /harness off (commands/harness.md, scripts/harness-switch) creates
<harness home>/.harness-switch/off; /harness on removes it. While the file exists, every hook
settings.json registers and every background job of the harness (checkpoint snapshots, the
git-fswatch daemon, the landing, the post-commit auto-push, the keystone) does nothing and
prints nothing. One file decides, so every hook is on or every hook is off: a switch cut
halfway never leaves some hooks running and others not.

The harness home is the directory two levels above this file (hooks/lib/ -> the home),
symlinks resolved, the same home scripts/harness-switch derives from its own location.
Stdlib only, no other import: it runs first in every Python hook, before anything it could
break. hooks/lib/harness_switch.sh is the same test for the shell hooks and jobs (a test of the
same file, so a shell hook starts no interpreter for it).
"""
import os
import sys

DIR_NAME = ".harness-switch"
MARKER = "off"


def harness_home() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def marker_path(home: str | None = None) -> str:
    return os.path.join(home or harness_home(), DIR_NAME, MARKER)


def is_off(home: str | None = None) -> bool:
    """True while the switch is off for `home` (default: this file's harness home)."""
    return os.path.exists(marker_path(home))


def exit_if_off() -> None:
    """End the calling hook with exit 0 and no output while the switch is off."""
    if is_off():
        sys.exit(0)
