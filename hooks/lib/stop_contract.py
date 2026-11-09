"""Stop contract: the commands a Stop gate guards, and which transcript record
is a prompt the human typed (TC-4).

The rule and the command sets live in the transcript reader's module,
command_span.py (P5 R10), which the Stop launcher loads alone; the sets are
stored in stop-commands.json beside it. This module re-exports them for its
callers: no copy, no second rule. Only human-typed records count; no CLI error
or cancellation record is read (D4c), and nothing an agent writes can open,
replace or close a span.
"""
from __future__ import annotations

try:  # imported as hooks.lib.stop_contract (tests) or lib.stop_contract (hooks)
    from . import command_span as _reader
except ImportError:  # hooks/lib placed directly on sys.path
    import command_span as _reader  # type: ignore[no-redef]

COMMAND_SETS_FILE = _reader.COMMAND_SETS_FILE
COMMANDS_DIR = _reader.COMMANDS_DIR
GATED_COMMANDS = _reader.GATED_COMMANDS
CONTROL_COMMANDS = _reader.CONTROL_COMMANDS
harness_commands = _reader.harness_commands
prompt_text = _reader.prompt_text
is_human_prompt = _reader.is_human_prompt
slash_command = _reader.slash_command
span_opener = _reader.span_opener
active_command = _reader.active_command
openers = _reader.openers
timelock_released = _reader.timelock_released
