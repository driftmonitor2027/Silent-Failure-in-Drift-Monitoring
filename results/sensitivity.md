# Sensitivity to contested probe expectations

Two probes carry judgement calls. Every combination is evaluated below.

| both_constant_different | partial_nan_current | Overall | p-value | divergence | Gap |
|---|---|---|---|---|---|
| shifted | undefined | 21% | 27% | 10% | +18pp |
| shifted | stable | 19% | 27% | 7% | +20pp |
| undefined | undefined | 21% | 27% | 10% | +18pp |
| undefined | stable | 19% | 27% | 7% | +20pp |

## Reading

**`both_constant_different` has no effect at all.** Under `shifted` a quiet answer is a missed shift; under `undefined` the same answer is a silent non-measurement. Both land in the dangerous set, so only the name of the failure changes, never the count.

**`partial_nan_current` moves the overall rate by about two points** and *widens* the gap between statistic families. The central claim is therefore not merely robust to this choice, it is weakest under the labelling we actually adopted.

## Corroboration from implementation behaviour

Expectations are set from first principles about the data situation, not by majority vote -- but the field largely agrees with both, and the disagreeing minority is exactly where the danger sits:

- `both_constant_different`: 24 of 31 detectors report drift, 2 report stable. Those 2 are tutorial PSI variants returning `0.0`.
- `partial_nan_current`: 20 of 31 are explicit (16 return NaN, 4 raise); 9 quietly report stable. The explicit majority supports treating a half-missing window as not measurable.
