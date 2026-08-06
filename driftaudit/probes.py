"""Adversarial inputs for drift detectors.

Each probe is an input pair (reference, current) on which a distribution-shift
test is either undefined or degenerate. The audit asks one question of every
detector on every probe:

    Can the caller distinguish "no drift" from "the test could not be run"?

A detector that returns a bare low score for an undefined test silently
disables whatever gate is built on it. That is the failure this battery is
designed to expose, and it is not hypothetical: it is the defect that produced
a false negative for an entire experiment in prior work, because a constant
reference sample yields no quantile breaks and the implementation returned 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Expectation for what a *correct* detector should do on a probe.
UNDEFINED = "undefined"  # test is not computable; must not report "stable"
STABLE = "stable"  # genuinely no shift; reporting stable is correct
SHIFTED = "shifted"  # genuine shift; reporting stable is a false negative


@dataclass(frozen=True)
class Probe:
    key: str
    title: str
    reference: np.ndarray
    current: np.ndarray
    expectation: str
    rationale: str
    tags: tuple[str, ...] = field(default=())

    @property
    def dangerous_if_stable(self) -> bool:
        """True when reporting 'no drift' would hide something from the caller."""
        return self.expectation in (UNDEFINED, SHIFTED)


def _rng(seed: int = 20260802) -> np.random.Generator:
    return np.random.default_rng(seed)


def build_probes() -> list[Probe]:
    r = _rng()
    normal = r.normal(100.0, 15.0, 500)
    normal_b = _rng(7).normal(100.0, 15.0, 500)
    shifted = _rng(11).normal(140.0, 15.0, 500)

    return [
        # ---- degeneracy: the failure that motivates this work ------------
        Probe(
            "degenerate_reference",
            "Reference is constant, current varies",
            np.zeros(500),
            normal,
            UNDEFINED,
            "Quantile binning on a constant reference yields fewer than two "
            "distinct edges, so binned divergences are undefined. Arises "
            "whenever a reference window is computed at the wrong point in "
            "time and every value collapses to the same number.",
            ("degeneracy",),
        ),
        Probe(
            "degenerate_current",
            "Current is constant, reference varies",
            normal,
            np.zeros(500),
            SHIFTED,
            "The current window has collapsed to a point mass. This is an "
            "extreme shift, not stability, and is a common signature of a "
            "broken feature pipeline.",
            ("degeneracy",),
        ),
        Probe(
            "both_constant_equal",
            "Both windows constant and identical",
            np.full(500, 7.0),
            np.full(500, 7.0),
            STABLE,
            "Nothing changed. A detector may legitimately report stable, but "
            "should not crash.",
            ("degeneracy",),
        ),
        Probe(
            "both_constant_different",
            "Both windows constant, different values",
            np.full(500, 7.0),
            np.full(500, 99.0),
            SHIFTED,
            "Maximal shift with zero variance. Variance-normalised statistics "
            "divide by zero here; binned statistics see one bin.",
            ("degeneracy",),
        ),
        # ---- support and binning ----------------------------------------
        Probe(
            "disjoint_support",
            "Current lies entirely outside the reference range",
            normal,
            normal + 1000.0,
            SHIFTED,
            "Every current observation falls in an outer bin. Bin-wise ratios "
            "involve division by zero unless the implementation clips, and "
            "clipping silently caps the reported severity.",
            ("support",),
        ),
        Probe(
            "empty_reference_bins",
            "Reference has gaps the current window fills",
            np.concatenate([r.normal(0, 1, 250), r.normal(20, 1, 250)]),
            _rng(3).normal(10, 1, 500),
            SHIFTED,
            "The current mass sits in a region where the reference has zero "
            "density. log(p/q) is undefined without smoothing, and the choice "
            "of smoothing constant silently determines the score.",
            ("support",),
        ),
        # ---- sample size -------------------------------------------------
        Probe(
            "tiny_current_n3",
            "Current window has 3 observations",
            normal,
            _rng(5).normal(100.0, 15.0, 3),
            UNDEFINED,
            "Three points cannot populate ten bins. Any score is dominated by "
            "binning noise; published PSI thresholds are asymptotic and do "
            "not apply.",
            ("sample-size",),
        ),
        Probe(
            "tiny_both_n5",
            "Both windows have 5 observations",
            _rng(13).normal(100.0, 15.0, 5),
            _rng(17).normal(100.0, 15.0, 5),
            UNDEFINED,
            "Below any sample size at which a binned divergence is "
            "interpretable, yet nothing in the input signals that.",
            ("sample-size",),
        ),
        Probe(
            "empty_current",
            "Current window is empty",
            normal,
            np.array([]),
            UNDEFINED,
            "No data arrived. This is an outage, and it must not be reported "
            "as population stability.",
            ("sample-size", "missing"),
        ),
        # ---- missing and non-finite values -------------------------------
        Probe(
            "all_nan_current",
            "Current window is entirely NaN",
            normal,
            np.full(500, np.nan),
            UNDEFINED,
            "A fully failed feature computation. Implementations that drop "
            "NaN before binning see an empty window; those that do not "
            "propagate NaN into the score.",
            ("missing",),
        ),
        Probe(
            "partial_nan_current",
            "Half the current window is NaN",
            normal,
            np.concatenate([_rng(19).normal(100.0, 15.0, 250), np.full(250, np.nan)]),
            UNDEFINED,
            "Silent NaN dropping halves the effective sample size without "
            "telling the caller, which changes the score's meaning.",
            ("missing",),
        ),
        Probe(
            "inf_in_current",
            "Current window contains infinities",
            normal,
            np.concatenate([_rng(23).normal(100.0, 15.0, 495), np.full(5, np.inf)]),
            UNDEFINED,
            "Infinite values make range-based binning collapse; quantile "
            "binning may survive. Behaviour should at minimum be signalled.",
            ("missing",),
        ),
        # ---- true controls: a detector must get these right ---------------
        Probe(
            "control_no_shift",
            "Two samples from the same distribution",
            normal,
            normal_b,
            STABLE,
            "Control. A detector reporting drift here is producing a false "
            "alarm.",
            ("control",),
        ),
        Probe(
            "control_large_shift",
            "Mean shifted by more than two standard deviations",
            normal,
            shifted,
            SHIFTED,
            "Control. A detector missing this is producing a false negative.",
            ("control",),
        ),
    ]


PROBES: list[Probe] = build_probes()
PROBES_BY_KEY: dict[str, Probe] = {p.key: p for p in PROBES}
