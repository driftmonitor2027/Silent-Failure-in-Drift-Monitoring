"""PSI outside the monitoring libraries.

PSI is four lines of arithmetic, so many teams never install anything and write
it themselves. These implementations reconstruct patterns from *published*
sources -- a widely referenced public repository and tutorial write-ups -- plus
one pattern observed in a production harness.

Scope discipline matters here and is recorded per implementation in
``SOURCES.md``. We audit reconstructions of published patterns; we do **not**
claim to have measured how common any pattern is across practitioner code at
large, which would require a sample of real repositories that we did not
collect. In particular the zero-returning guard is an existence proof from one
observed production defect, not a rate.

The variants differ only in how they handle the arithmetic's edge cases, and
that difference is the whole story: none of them can tell a caller that the
statistic was undefined, because all of them return a bare float.
"""

from __future__ import annotations

import numpy as np

from driftaudit.adapters.base import Result

PSI_MODERATE = 0.15  # the conventional "investigate" threshold


class TextbookPSIClipped:
    """The most common form: quantile bins, clip zero cells to a small epsilon.

    Clipping keeps the logarithm finite, which is why this version is popular.
    It also converts every undefined case into a finite, small-looking number.
    """

    name = "textbook-psi/clipped"
    threshold = PSI_MODERATE

    def __init__(self, bins: int = 10, eps: float = 1e-4) -> None:
        self.bins, self.eps = bins, eps

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        edges = np.unique(np.percentile(reference, np.linspace(0, 100, self.bins + 1)))
        exp, _ = np.histogram(reference, bins=edges)
        act, _ = np.histogram(current, bins=edges)
        e = np.clip(exp / max(exp.sum(), 1), self.eps, None)
        a = np.clip(act / max(act.sum(), 1), self.eps, None)
        return Result(score=float(np.sum((a - e) * np.log(a / e))))


class FieldPSIZeroGuard:
    """The variant that noticed degeneracy -- and handled it by returning zero.

    This is the defect at the centre of the paper: the guard is correct that
    the statistic cannot be computed, and then reports the value that means
    "perfectly stable". The caller cannot distinguish the two.

    Unlike the other variants here, this pattern was **not** found in any
    published tutorial we inspected; it comes from a production harness where
    it shipped and silenced a retraining trigger for an entire experiment.
    Named ``field-psi`` so no reader infers a tutorial origin. See SOURCES.md.
    """

    name = "field-psi/zero-guard"
    threshold = PSI_MODERATE

    def __init__(self, bins: int = 10) -> None:
        self.bins = bins

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        if len(reference) < 5 or len(current) < 5:
            return Result(score=0.0)
        edges = np.unique(np.percentile(reference, np.linspace(0, 100, self.bins + 1)))
        if len(edges) < 3:
            return Result(score=0.0)
        exp, _ = np.histogram(reference, bins=edges)
        act, _ = np.histogram(current, bins=edges)
        e = np.clip(exp / max(exp.sum(), 1), 1e-4, None)
        a = np.clip(act / max(act.sum(), 1), 1e-4, None)
        return Result(score=float(np.sum((a - e) * np.log(a / e))))


class TextbookPSIEqualWidth:
    """Equal-width bins over the reference range instead of quantiles.

    Equal-width binning is more fragile than quantile binning under outliers
    and infinities, and it silently discards current-window mass that falls
    outside the reference range.
    """

    name = "textbook-psi/equal-width"
    threshold = PSI_MODERATE

    def __init__(self, bins: int = 10, eps: float = 1e-6) -> None:
        self.bins, self.eps = bins, eps

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        lo, hi = float(np.min(reference)), float(np.max(reference))
        edges = np.linspace(lo, hi, self.bins + 1)
        exp, _ = np.histogram(reference, bins=edges)
        act, _ = np.histogram(current, bins=edges)
        e = exp / max(exp.sum(), 1) + self.eps
        a = act / max(act.sum(), 1) + self.eps
        return Result(score=float(np.sum((a - e) * np.log(a / e))))


class StatusReportingPSI:
    """Reference implementation: same arithmetic, machine-readable status.

    Included as the constructive half of the argument. The fix costs one extra
    return field, and it is what makes a gate expressible as
    `if r.status == "ok" and r.score >= t`. The paper recommends this shape.
    """

    name = "reference-psi/status"
    threshold = PSI_MODERATE

    def __init__(self, bins: int = 10, min_samples: int = 30) -> None:
        self.bins, self.min_samples = bins, min_samples

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        ref = reference[np.isfinite(reference)]
        cur = current[np.isfinite(current)]
        if len(ref) != len(reference) or len(cur) != len(current):
            dropped = (len(reference) - len(ref)) + (len(current) - len(cur))
            if len(cur) == 0 or len(ref) == 0:
                return Result(status="empty-after-dropping-non-finite")
            if dropped:
                # Non-finite input changes the effective sample size; say so.
                return Result(status=f"non-finite-input-dropped-{dropped}")
        if len(ref) < self.min_samples or len(cur) < self.min_samples:
            return Result(status="insufficient-samples")
        edges = np.unique(np.percentile(ref, np.linspace(0, 100, self.bins + 1)))
        if len(edges) < 3:
            return Result(status="degenerate-reference")
        exp, _ = np.histogram(ref, bins=edges)
        act, _ = np.histogram(cur, bins=edges)
        e = np.clip(exp / max(exp.sum(), 1), 1e-4, None)
        a = np.clip(act / max(act.sum(), 1), 1e-4, None)
        value = float(np.sum((a - e) * np.log(a / e)))
        return Result(score=value, flagged=value >= self.threshold, status=None)


def detectors() -> list:
    return [
        TextbookPSIClipped(),
        FieldPSIZeroGuard(),
        TextbookPSIEqualWidth(),
        StatusReportingPSI(),
    ]
