# drift-monitor-audit

Conformance audit of distribution-shift detectors, asking one question of every
implementation:

> When the statistic cannot be computed, can the caller tell?

A production drift gate is code — `if score >= threshold: retrain()` — and it
treats every non-raising return as a measurement. An implementation that answers
an undefined test with a bare low float silently disables that gate and leaves
the dashboard green. This repo measures which implementations do that.

Research plan (this paper and two follow-ups): [PLAN.md](PLAN.md).

## Run

```bash
python -m venv .venv && ./.venv/Scripts/python.exe -m pip install numpy scipy evidently river
./.venv/Scripts/python.exe -m driftaudit.runner --out results/audit_matrix.csv
```

`--no-libraries` restricts the run to the dependency-free implementations.

## What it produces

A verdict per (detector, probe) cell:

| Verdict | Meaning |
|---|---|
| `pass` | behaved correctly for this probe |
| `safe-undefined` | declined to answer where an answer was due — uninformative, never dangerous |
| `fail-silent` | **undefined test reported as a stable measurement** |
| `fail-miss` | real shift reported as stable |
| `fail-alarm` | no shift reported as drift |

`fail-silent` and `fail-miss` are the dangerous pair: both leave a monitoring
gate believing it measured something.

## Layout

```
driftaudit/probes.py            14 adversarial inputs + the expectation for each
driftaudit/outcomes.py          taxonomy and the expectation-aware verdict model
driftaudit/adapters/base.py     uniform interface; captures warnings and crashes
driftaudit/adapters/textbook.py PSI as tutorials write it, plus a status-returning fix
driftaudit/runner.py            runs the battery, prints the matrix, writes CSV
results/                        audit output
```

## Design note

The probes carry an `expectation` (`undefined` / `stable` / `shifted`) and
verdicts are judged against it, not in isolation. Without that, a detector
correctly reporting "stable" on the no-shift control looks identical to one
reporting "stable" on an empty window — which is precisely the conflation the
paper is about, and it would be embarrassing to reproduce it in the instrument.
