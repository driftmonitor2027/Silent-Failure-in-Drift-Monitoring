"""Classifying what a detector did, from the caller's point of view.

The audit does not ask whether a detector's number is statistically ideal. It
asks a weaker and more consequential question: given only what the detector
returned, could a program decide whether to trust it?

That framing matters because production monitors are consumed by code, not by
people. A retraining gate written as `if psi >= 0.15: retrain()` treats every
non-raising return as a measurement. Whether that is safe depends entirely on
what the library does when the measurement is impossible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# ---- what the caller observed -------------------------------------------
SILENT_STABLE = "silent-stable"
SILENT_DRIFT = "silent-drift"
EXPLICIT_UNDEFINED = "explicit-undefined"
WARNED = "warned"
RAISED = "raised"
UNSUPPORTED = "unsupported"

#: Ordering by how much the caller can tell. Used for ranking in the paper.
SEVERITY = {
    SILENT_STABLE: 0,  # worst: undefined result indistinguishable from "fine"
    SILENT_DRIFT: 1,  # noisy but at least not a silent all-clear
    WARNED: 2,  # signalled, but only to a log
    EXPLICIT_UNDEFINED: 3,  # best: machine-readable "cannot compute"
    RAISED: 3,  # equally safe: impossible to ignore
    UNSUPPORTED: 4,
}


@dataclass(frozen=True)
class Observation:
    """One (detector, probe) cell of the audit matrix."""

    detector: str
    probe: str
    outcome: str
    score: float | None
    flagged: bool | None
    detail: str = ""
    #: Whether the library emitted a warning. Recorded alongside the outcome
    #: rather than replacing it: a warning does not change what value the
    #: caller got back, and Python warnings are trivially suppressed and
    #: routinely invisible in production logs. Treating "warned" as a distinct
    #: outcome silently discarded the detector's actual verdict.
    warned: bool = False

    @property
    def caller_can_tell(self) -> bool:
        """Could a program distinguish this result from a valid measurement?"""
        return self.outcome in (EXPLICIT_UNDEFINED, RAISED, UNSUPPORTED)


def classify(
    *,
    detector: str,
    probe_key: str,
    score: Any,
    flagged: Any,
    raised: BaseException | None = None,
    warnings_emitted: int = 0,
    threshold: float,
    explicit_status: str | None = None,
) -> Observation:
    """Map a detector's raw return into the taxonomy.

    `explicit_status` is for libraries that return a machine-readable
    "not computable" signal of their own; those are the good citizens and the
    paper should say so by name.
    """
    warned = warnings_emitted > 0

    if raised is not None:
        return Observation(
            detector, probe_key, RAISED, None, None,
            f"{type(raised).__name__}: {str(raised)[:120]}", warned,
        )

    if explicit_status is not None:
        return Observation(
            detector, probe_key, EXPLICIT_UNDEFINED, None, None,
            f"status={explicit_status}", warned,
        )

    # A NaN/None score is itself a machine-readable "undefined" -- the caller
    # can test for it, so this counts as explicit.
    numeric: float | None
    try:
        numeric = None if score is None else float(score)
    except (TypeError, ValueError):
        numeric = None

    if numeric is None or math.isnan(numeric):
        return Observation(
            detector, probe_key, EXPLICIT_UNDEFINED, numeric, _as_bool(flagged),
            "score is None/NaN", warned,
        )

    is_flagged = _as_bool(flagged)
    if is_flagged is None:
        is_flagged = numeric >= threshold

    return Observation(
        detector, probe_key, SILENT_DRIFT if is_flagged else SILENT_STABLE,
        numeric, is_flagged,
        f"{warnings_emitted} warning(s)" if warnings_emitted else "", warned,
    )


# ---- verdicts: outcome judged against what the probe expected -------------
PASS = "pass"
SAFE_UNDEFINED = "safe-undefined"  # declined to answer where an answer was due
FAIL_SILENT = "fail-silent"  # undefined test reported as a stable measurement
FAIL_NOISY = "fail-noisy"  # undefined test reported as drift
FAIL_MISS = "fail-miss"  # real shift reported as stable
FAIL_ALARM = "fail-alarm"  # no shift reported as drift
ERROR = "error"

#: Verdicts that leave a monitoring gate believing it measured something and
#: seeing nothing wrong. These are the paper's subject.
#:
#: FAIL_NOISY is deliberately excluded. Reporting drift on an uncomputable test
#: is still incorrect -- it triggers a spurious retrain and, per prior work, a
#: spurious retrain carries a real accuracy cost -- but it is *visible*. Someone
#: investigates. Grouping it with silent failure would overstate the thesis and
#: be unfair to implementations that at least fail loudly.
DANGEROUS = (FAIL_SILENT, FAIL_MISS)


def verdict(observation: "Observation", expectation: str) -> str:
    """Judge one cell. `expectation` comes from the probe.

    The asymmetry is deliberate: declining to answer is never dangerous, while
    answering "stable" when the test was undefined is the failure that hides
    an outage behind a green dashboard.
    """
    from driftaudit.probes import SHIFTED, STABLE, UNDEFINED

    o = observation.outcome
    if o == RAISED:
        return ERROR if expectation == STABLE else PASS
    if o in (EXPLICIT_UNDEFINED, UNSUPPORTED):
        return PASS if expectation == UNDEFINED else SAFE_UNDEFINED
    if expectation == UNDEFINED:
        # Both are wrong; only one is quiet about it.
        return FAIL_NOISY if o == SILENT_DRIFT else FAIL_SILENT
    if expectation == SHIFTED:
        return PASS if o == SILENT_DRIFT else FAIL_MISS
    if expectation == STABLE:
        return FAIL_ALARM if o == SILENT_DRIFT else PASS
    return ERROR


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    try:
        return bool(value)
    except Exception:
        return None
