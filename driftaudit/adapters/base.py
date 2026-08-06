"""Uniform interface so every detector faces an identical battery."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from driftaudit.outcomes import Observation, classify
from driftaudit.probes import Probe


class Detector(Protocol):
    name: str
    threshold: float

    def score(self, reference: np.ndarray, current: np.ndarray) -> "Result": ...


@dataclass(frozen=True)
class Result:
    """What a detector hands back.

    `status` is the field most implementations lack. When a detector can say
    "not computable" in a machine-readable way, it sets this; the audit records
    that as the safe outcome.
    """

    score: float | None = None
    flagged: bool | None = None
    status: str | None = None


def probe_detector(detector: Detector, probe: Probe) -> Observation:
    """Run one detector against one probe, capturing warnings and exceptions."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # NumPy emits its own class of warning for degenerate arithmetic.
        with np.errstate(all="warn"):
            try:
                result = detector.score(probe.reference, probe.current)
                raised: BaseException | None = None
            except BaseException as exc:  # noqa: BLE001 - auditing crashes is the point
                result, raised = Result(), exc
        n_warn = len(caught)

    return classify(
        detector=detector.name,
        probe_key=probe.key,
        score=result.score,
        flagged=result.flagged,
        raised=raised,
        warnings_emitted=n_warn,
        threshold=detector.threshold,
        explicit_status=result.status,
    )
