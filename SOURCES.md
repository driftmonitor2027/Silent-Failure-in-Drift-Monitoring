# Provenance of the non-library implementations

The audit includes four implementations that are not shipped by a monitoring
library. Because the paper makes claims about how drift statistics are written
outside libraries, each one's origin is recorded here, and the claim is scoped
to what these sources actually support.

## What we claim, and what we do not

**We claim:** the patterns below appear in *published* PSI implementations —
widely referenced tutorials, blog posts, and a public reference repository —
and we audit faithful reconstructions of those patterns.

**We do not claim** to have measured how common any pattern is across
practitioner code at large. That would need a sample of real-world
repositories, which we did not collect. Rates reported for these
implementations describe the reconstructions, not a population.

---

## `textbook-psi/clipped` — epsilon smoothing

Reconstruction of the dominant published pattern: quantile bins, zero-count
cells replaced by a small constant so the logarithm stays finite.

Attested in:

- `mwburke/population-stability-index` (`psi.py`), the most widely referenced
  standalone Python PSI implementation, which substitutes `0.0001` for zero
  proportions. Inspected 2026-08-02.
- Multiple tutorial write-ups using the same device with varying constants
  (`np.clip(..., a_min=0.0001)`, `np.where(pct == 0, 1e-6, pct)`).

Notably, the reference repository has **no** handling for a constant reference
distribution — its range scaling divides by zero and yields `inf`/`nan` — and
no sample-size validation. Our reconstruction is faithful on both counts.

## `textbook-psi/equal-width` — fixed-width binning

Reconstruction of the "fixed" binning mode documented alongside quantile
binning in PSI tutorials, where bins are equal width across the reference
range. Fragile to outliers and to any current-window mass falling outside the
reference range.

## `field-psi/zero-guard` — the guard that returns zero

**This one is not from a tutorial, and it would be wrong to present it as one.**
A search of published PSI implementations did not find the pattern; the
tutorials we inspected either smooth zero cells or handle nothing at all.

Its actual provenance is a production monitoring harness in which it shipped
and caused a measurable false negative: the guard correctly detected that
quantile binning could not produce breaks from a degenerate reference, and
then returned `0.0` — the value meaning "perfectly stable" — so the retraining
trigger it fed never fired for an entire experiment.

It is retained because it is the clearest possible illustration of the failure
mode, and because it is real rather than invented. It is named `field-psi`
rather than `textbook-psi` so that no reader infers a tutorial origin, and any
claim about its prevalence is explicitly out of scope: **n = 1 observed
instance**, reported as an existence proof, not a rate.

## `reference-psi/status` — the constructive fix

Ours. Identical arithmetic to the clipped variant, plus a machine-readable
`status` field distinguishing "measured, stable" from "could not measure".
Included to show the cost of the fix is one field, and to give the audit a
positive control that should pass every probe.
