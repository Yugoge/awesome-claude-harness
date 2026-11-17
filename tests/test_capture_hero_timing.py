"""The hero capture correlates grant samples with the consumption marker on raw times.

scripts/capture-hero-run.py samples its own grant path and stamps each sample before the
observation; it stamps each demo line when the line is read from the pipe. The verdict
"present immediately before consumption, absent immediately after" compares those two
stamps. When the marker's stamp was taken back from the displayed "[%8.3f]" column it was
up to 0.5 ms off, so a present sample taken under 1 ms before the real marker could land
on or after the displayed one and the check failed although the run was correct
(CI runs 42924754530, 41295898191). These tests drive the script's own correlation with
fixed stamps, so no timing of this machine enters the verdict.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "capture-hero-run.py"
INSTALL_HASH = "a" * 64


def _load():
    spec = importlib.util.spec_from_file_location("capture_hero_run_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _present(t: float) -> dict:
    return {"t": t, "present": True, "sha256": INSTALL_HASH}


def _absent(t: float) -> dict:
    return {"t": t, "present": False, "sha256": None}


def test_present_sample_half_a_millisecond_before_the_marker_is_before_it():
    mod = _load()
    # Marker read at 5.00149 s; displayed as "[   5.001]". The grant's one present
    # sample was stamped 0.5 ms earlier, at 5.00099 s -- 5.0010 at four places, equal to
    # the displayed marker, so a display-resolution comparison put it neither before nor
    # after the marker.
    t_marker = 5.00149
    assert f"[{t_marker:8.3f}]" == "[   5.001]"
    samples = [_absent(4.95), _present(5.00099), _absent(5.05099), _absent(5.10099)]

    failures, present_pre, post = mod.correlate_consumption(
        samples, t_marker, INSTALL_HASH)

    assert failures == []
    assert present_pre == [samples[1]]
    assert post == samples[2:]


def test_present_sample_stamped_after_the_marker_still_fails():
    mod = _load()
    # A sample is stamped before its observation and the marker after the read, so a
    # present sample stamped later than the marker means the grant outlived its
    # consumption: a real failure, which no tolerance may absorb.
    t_marker = 5.00149
    samples = [_present(4.95099), _present(5.00159), _absent(5.05159)]

    failures, _present_pre, _post = mod.correlate_consumption(
        samples, t_marker, INSTALL_HASH)

    assert failures == ["grant was NOT absent immediately after consumption"]
