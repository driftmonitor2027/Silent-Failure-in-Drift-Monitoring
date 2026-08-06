"""Adapters for installed drift-monitoring libraries.

Each adapter calls the library the way its documentation says to, and records
what a caller would observe. Two rules keep the audit honest:

1. **No wrapping of edge cases.** The adapter must not pre-check for empty or
   degenerate input, because the question is precisely what the library does
   when the caller has not thought to check.
2. **Correct API use.** An adapter that mis-calls a library and records the
   resulting nonsense as a defect would be worse than no audit at all. Call
   surfaces are taken from the library's own signatures and registries rather
   than hand-transcribed, and the exact versions are pinned in
   ``results/environment.txt``.

Where a library exposes a registry of tests, the adapters are generated from
it. That keeps coverage honest -- we audit everything the library offers for
numeric data, not a subset chosen after seeing the results.
"""

from __future__ import annotations

import numpy as np

from driftaudit.adapters.base import Result

#: Gate thresholds, stated in one place because every verdict depends on them.
PSI_MODERATE = 0.15   # conventional PSI "investigate" point (0.1 minor, 0.25 major)
ALPHA = 0.05          # conventional significance level for p-value gates
EFFECT_SIZE_THRESHOLD = 0.25  # distances, normalised by reference dispersion
DISTANCE_THRESHOLD = 0.1      # library-native distances already on a 0-1 scale


# --------------------------------------------------------------------------
# scipy: hand-rolled gates
# --------------------------------------------------------------------------
class ScipyTest:
    """A generic two-sample SciPy test wired directly as a drift gate.

    This is the most common monitor of all -- no library, just
    ``if ks_2samp(a, b).pvalue < 0.05``. We audit these as *SciPy-as-gate*, not
    as monitoring products: SciPy does not claim to ship drift detectors, and
    any failure recorded here is a property of using the statistic this way.

    Call conventions differ between functions and are declared per detector
    rather than assumed. Getting this wrong is not hypothetical: an earlier
    version passed ``anderson_ksamp(a, b)``, whose second positional parameter
    is the ``midrank`` flag rather than a second sample, invalidating all 14 of
    its cells.
    """

    threshold = ALPHA

    def __init__(self, fn_name: str, *, kind: str = "pvalue",
                 call: str = "pair", threshold: float | None = None,
                 scale_by: str | None = None):
        self.fn_name, self.kind, self.call = fn_name, kind, call
        self.scale_by = scale_by
        self.name = f"scipy/{fn_name}"
        if threshold is not None:
            self.threshold = threshold

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        from scipy import stats

        fn = getattr(stats, self.fn_name)
        out = fn([reference, current]) if self.call == "list" else fn(reference, current)

        if self.kind == "pvalue":
            p = float(out.pvalue if hasattr(out, "pvalue") else out[1])
            return Result(score=p, flagged=p < self.threshold)

        value = float(out)
        # Distances are expressed in the data's own units, so an absolute
        # threshold is meaningless: Wasserstein distance between two samples of
        # N(100, 15) is ~1.9, which any small fixed cut-off would flag. We
        # normalise by the reference dispersion and gate on a dimensionless
        # effect size instead.
        if self.scale_by == "std":
            scale = float(np.std(reference)) if len(reference) else 0.0
            if not np.isfinite(scale) or scale == 0.0:
                # Degenerate reference: the normaliser is undefined. Say so
                # rather than dividing by zero and reporting a huge "drift".
                return Result(score=value, status="undefined-scale")
            value = value / scale
        return Result(score=value, flagged=value >= self.threshold)


def _scipy_detectors() -> list:
    return [
        ScipyTest("ks_2samp"),
        ScipyTest("cramervonmises_2samp"),
        ScipyTest("epps_singleton_2samp"),
        ScipyTest("mannwhitneyu"),
        ScipyTest("ttest_ind"),
        ScipyTest("ranksums"),
        ScipyTest("brunnermunzel"),
        ScipyTest("anderson_ksamp", call="list"),
        ScipyTest("mood"),
        ScipyTest("ansari"),
        # Dimensionless effect-size gate: a shift of a quarter of the reference
        # standard deviation, which is the low end of what is conventionally
        # called a small effect.
        ScipyTest("wasserstein_distance", kind="distance", scale_by="std",
                  threshold=EFFECT_SIZE_THRESHOLD),
        ScipyTest("energy_distance", kind="distance", scale_by="std",
                  threshold=EFFECT_SIZE_THRESHOLD),
    ]


# --------------------------------------------------------------------------
# evidently: generated from the library's own stat-test registry
# --------------------------------------------------------------------------
class EvidentlyStatTest:
    """Wrapper over one Evidently ``StatTest``.

    Signature verified from the library: ``func(reference: Series,
    current: Series, feature_type: ColumnType, threshold: float)`` returning
    ``(score, drift_detected)``.
    """

    def __init__(self, key: str, test, threshold: float):
        self.key, self.test, self.threshold = key, test, threshold
        self.name = f"evidently/{key}"

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        import pandas as pd
        from evidently.legacy.core import ColumnType

        value, flagged = self.test.func(
            pd.Series(reference), pd.Series(current), ColumnType.Numerical, self.threshold
        )
        return Result(score=float(value), flagged=bool(flagged))


def _evidently_detectors() -> list:
    """Every Evidently stat test that declares support for numerical data."""
    import evidently.legacy.calculations.stattests as st
    from evidently.legacy.core import ColumnType

    out = []
    for attr in sorted(n for n in dir(st) if n.endswith("_stat_test")):
        test = getattr(st, attr)
        allowed = getattr(test, "allowed_feature_types", ()) or ()
        if ColumnType.Numerical not in allowed:
            continue  # categorical- or text-only test; not our contract
        key = attr.removesuffix("_stat_test")
        default = getattr(test, "default_threshold", None)
        out.append(EvidentlyStatTest(key, test, float(default) if default else ALPHA))
    return out


# --------------------------------------------------------------------------
# river: streaming detectors
# --------------------------------------------------------------------------
class RiverStreaming:
    """A River streaming detector fed reference then current.

    Streaming detectors have a different contract: values arrive one at a time
    and the detector reports a drift state. The audit question is unchanged --
    with a degenerate or empty stream, can the caller tell the detector never
    had enough data to decide?
    """

    threshold = 0.5  # unused; these report their own boolean

    def __init__(self, cls_name: str, **kwargs):
        self.cls_name, self.kwargs = cls_name, kwargs
        self.name = f"river/{cls_name}"

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        from river import drift

        det = getattr(drift, self.cls_name)(**self.kwargs)
        for v in reference:
            det.update(float(v))
        drifted = False
        for v in current:
            det.update(float(v))
            if det.drift_detected:
                drifted = True
        return Result(score=1.0 if drifted else 0.0, flagged=drifted)


def _river_detectors() -> list:
    return [
        RiverStreaming("KSWIN", alpha=0.005, seed=42),
        RiverStreaming("ADWIN"),
        RiverStreaming("PageHinkley"),
    ]


# --------------------------------------------------------------------------
# optional heavy libraries
# --------------------------------------------------------------------------
class AlibiKS:
    """alibi-detect's KSDrift, a batch detector with a fit/predict contract."""

    name = "alibi-detect/KSDrift"
    threshold = ALPHA

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        from alibi_detect.cd import KSDrift

        det = KSDrift(reference.reshape(-1, 1), p_val=ALPHA)
        pred = det.predict(current.reshape(-1, 1))
        d = pred["data"]
        p = float(np.asarray(d["p_val"]).ravel()[0])
        return Result(score=p, flagged=bool(d["is_drift"]))


class NannyMLUnivariate:
    """NannyML's univariate drift calculator.

    Two API details matter and are easy to get wrong:

    * ``to_df()`` returns rows for **both** the reference and the analysis
      period. The reference row compares the reference against itself and is
      therefore always ~0; reading it instead of the analysis row makes any
      detector look like it never sees drift.
    * NannyML computes its own alert thresholds from the *variability across
      reference chunks*. Fitting with a single chunk leaves no variability, the
      threshold degenerates, and everything alerts -- including an unshifted
      control. Several chunks are therefore required for the library to work as
      designed, and ``alert`` is then the library's own decision rather than a
      threshold we imposed.

    Gate semantics: drift if **any** analysis chunk alerts, which is how a
    practitioner consumes a chunked report. The reported score is the mean
    across analysis chunks.
    """

    threshold = DISTANCE_THRESHOLD  # only a fallback if `alert` is absent

    def __init__(self, method: str = "jensen_shannon", chunks: int = 5):
        self.method, self.chunks = method, chunks
        self.name = f"nannyml/{method}"

    def score(self, reference: np.ndarray, current: np.ndarray) -> Result:
        import nannyml as nml
        import pandas as pd

        calc = nml.UnivariateDriftCalculator(
            column_names=["f"], continuous_methods=[self.method], chunk_number=self.chunks
        ).fit(pd.DataFrame({"f": reference}))
        df = calc.calculate(pd.DataFrame({"f": current})).to_df()

        analysis = df[df[("chunk", "chunk", "period")] == "analysis"]
        if analysis.empty:  # not enough data to form an analysis chunk at all
            return Result(status="no-analysis-chunk")

        values = analysis[("f", self.method, "value")]
        alerts = analysis[("f", self.method, "alert")]
        value = float(values.mean())
        flagged = bool(alerts.any()) if alerts.notna().any() else value >= self.threshold
        return Result(score=value, flagged=flagged)


def _optional_detectors() -> list:
    return [
        AlibiKS(),
        NannyMLUnivariate("jensen_shannon"),
        NannyMLUnivariate("kolmogorov_smirnov"),
        NannyMLUnivariate("wasserstein"),
        NannyMLUnivariate("hellinger"),
    ]


# --------------------------------------------------------------------------
def _smoke(detector) -> bool:
    """A detector is auditable if it runs at all on ordinary input."""
    a = np.random.default_rng(0).normal(0, 1, 80)
    b = np.random.default_rng(1).normal(0, 1, 80)
    try:
        detector.score(a, b)
        return True
    except ImportError:
        return False
    except Exception:
        # Imports fine but errors on ordinary input: that is itself worth
        # auditing, so keep it.
        return True


def detectors() -> list:
    candidates: list = []
    for factory in (_scipy_detectors, _evidently_detectors, _river_detectors,
                    _optional_detectors):
        try:
            candidates.extend(factory())
        except ImportError:
            continue
    return [d for d in candidates if _smoke(d)]
