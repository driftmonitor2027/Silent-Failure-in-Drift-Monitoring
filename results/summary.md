# Audit summary

31 detectors x 14 probes = 434 cells. 93 (21%) are dangerous: the caller was told a value that reads as a valid, unalarming measurement when the test was either uncomputable or facing a real shift.

## Danger by kind of statistic

| Statistic family | Dangerous cells | Rate |
|---|---|---|
| field defect (n=1) | 6/14 | 43% |
| streaming detector | 16/42 | 38% |
| p-value test | 50/182 | 27% |
| published tutorial PSI | 6/28 | 21% |
| divergence / distance | 15/154 | 10% |
| reference impl. (control) | 0/14 | 0% |

This is the paper's central claim. A p-value has no value meaning "not applicable": a large p-value means *no evidence against the null*, which is vacuously true of an empty, degenerate or three-point window. Divergences tend to blow up on the same input instead, so they fail loudly. The safety of a drift gate therefore follows from the kind of statistic it is built on, not primarily from the quality of the implementation.

Two rows are **not** audited subjects and their rates are not prevalence estimates. `field defect (n=1)` is one defect observed in one production harness, reported as an existence proof; `reference impl. (control)` is our own status-returning implementation, included as a positive control that should pass everything. Only the library families and `published tutorial PSI` describe code we found in the wild -- and the latter is two reconstructions of a documented pattern, not a sample of practitioner repositories. See SOURCES.md.

### Robustness of the family gap

Point estimate 18pp (27% vs 10%). Bootstrapping over **detectors** (13 p-value, 11 divergence), 5000 resamples: 95% interval **[9pp, 27pp]**.

Leaving out each library in turn:

| Excluded | p-value | divergence | gap |
|---|---|---|---|
| alibi-detect | 28% | 10% | +18pp |
| evidently | 27% | 17% | +11pp |
| field-psi | 27% | 10% | +18pp |
| nannyml | 27% | 3% | +24pp |
| reference-psi | 27% | 10% | +18pp |
| river | 27% | 10% | +18pp |
| scipy | 26% | 10% | +16pp |
| textbook-psi | 27% | 10% | +18pp |

The interval is wide and the detector set is neither random nor balanced, so this quantifies sensitivity to *which detectors we happened to audit*, not uncertainty about detectors in general. The sign of the gap is stable under every single-library exclusion, which is the claim we make; the magnitude is not precisely estimated.

## Danger by probe

| Probe | Dangerous | Rate |
|---|---|---|
| tiny_both_n5 | 20/31 | 65% |
| inf_in_current | 18/31 | 58% |
| tiny_current_n3 | 17/31 | 55% |
| empty_reference_bins | 9/31 | 29% |
| partial_nan_current | 9/31 | 29% |
| degenerate_reference | 4/31 | 13% |
| empty_current | 4/31 | 13% |
| degenerate_current | 3/31 | 10% |
| all_nan_current | 3/31 | 10% |
| both_constant_different | 2/31 | 6% |
| disjoint_support | 2/31 | 6% |
| control_large_shift | 2/31 | 6% |
| both_constant_equal | 0/31 | 0% |
| control_no_shift | 0/31 | 0% |

## Danger by detector

| Detector | Dangerous | Rate |
|---|---|---|
| scipy/mood | 7/14 | 50% |
| scipy/ansari | 7/14 | 50% |
| field-psi/zero-guard | 6/14 | 43% |
| river/KSWIN | 6/14 | 43% |
| river/ADWIN | 6/14 | 43% |
| evidently/mann_whitney_u | 5/14 | 36% |
| textbook-psi/clipped | 4/14 | 29% |
| scipy/mannwhitneyu | 4/14 | 29% |
| scipy/ranksums | 4/14 | 29% |
| scipy/brunnermunzel | 4/14 | 29% |
| river/PageHinkley | 4/14 | 29% |
| nannyml/kolmogorov_smirnov | 4/14 | 29% |
| nannyml/wasserstein | 4/14 | 29% |
| scipy/ks_2samp | 3/14 | 21% |
| scipy/cramervonmises_2samp | 3/14 | 21% |
| scipy/ttest_ind | 3/14 | 21% |
| scipy/anderson_ksamp | 3/14 | 21% |
| evidently/ks | 3/14 | 21% |
| alibi-detect/KSDrift | 3/14 | 21% |
| nannyml/jensen_shannon | 3/14 | 21% |
| textbook-psi/equal-width | 2/14 | 14% |
| scipy/energy_distance | 2/14 | 14% |
| scipy/epps_singleton_2samp | 1/14 | 7% |
| evidently/hellinger | 1/14 | 7% |
| nannyml/hellinger | 1/14 | 7% |
| reference-psi/status | 0/14 | 0% |
| scipy/wasserstein_distance | 0/14 | 0% |
| evidently/jensenshannon | 0/14 | 0% |
| evidently/kl_div | 0/14 | 0% |
| evidently/psi | 0/14 | 0% |
| evidently/wasserstein | 0/14 | 0% |

6 of 31 detectors have no dangerous cell: `evidently/jensenshannon`, `evidently/kl_div`, `evidently/psi`, `evidently/wasserstein`, `reference-psi/status`, `scipy/wasserstein_distance`.

## Does source-level guarding predict behaviour?

| Static verdict | Detectors | Behavioural danger |
|---|---|---|
| silent-zero | 1 | 6/14 (43%) |
| smoothing | 3 | 9/42 (21%) |
| explicit | 12 | 36/168 (21%) |
| no-guard | 15 | 42/210 (20%) |

**It does not.** Implementations carrying explicit guards -- an early `raise`, a NaN return -- are no safer in practice than those with no guard at all. The reason is that a guard can only cover the cases its author anticipated, whereas the silent failure here arises from the *semantics of the statistic*: nothing raises and nothing is undefined in the arithmetic sense, because the computation succeeds and returns a perfectly legitimate number that happens to mean 'no evidence of difference' for a sample that carries no evidence of anything.

This is why the recommendation is not 'add guards'. It is to change the return contract so that 'measured, stable' and 'could not measure' are different values -- which is what the status-returning reference implementation does, at a cost of one field.
