# Replication package

Artifact for the submission *Silent Failure in Drift Monitoring: What Detectors
Return When They Cannot Measure*.

This package contains the probe battery, every detector adapter, the audit and
analysis tooling, the raw results the paper reports, and the generators that
turn those results into every number, table and figure in the manuscript.

**Anonymity.** This export carries no version-control history, author metadata
or institutional identifiers. Please do not deanonymize by inspecting hosting
accounts.

---

## Reproducing the paper

### Tier 1 — every table, figure and number (~1 minute, no libraries under test)

All reported values derive from `results/audit_matrix.csv`, which is included.

```bash
pip install numpy scipy matplotlib
python -m driftaudit.analysis      --csv results/audit_matrix.csv --out results/summary.md
python -m driftaudit.sensitivity   --csv results/audit_matrix.csv --out results/sensitivity.md
python -m driftaudit.figures       --csv results/audit_matrix.csv --out-dir paper/figs
python -m driftaudit.paper_numbers --csv results/audit_matrix.csv --out-dir paper/generated
```

The last command regenerates `paper/generated/`, which the manuscript
`\input`s. **The paper contains no hand-typed figure**: every scalar is a macro
and every data table is a generated `tabular`. Two scripts enforce this:

```bash
python paper/check_freshness.py   # literals, stale fragments, bibliography hygiene
python paper/check_tables.py      # per-detector table vs the CSV
```

Both must exit 0. They exist because hand-transcribed numbers went stale twice
during this work, which is the same class of silent inconsistency the paper is
about.

### Tier 2 — re-run the audit against the libraries (~2 minutes)

```bash
pip install -e ".[libraries]"
python -m driftaudit.runner --out results/audit_matrix.csv
python -m driftaudit.corpus --out results/corpus_sweep.csv
```

**Python 3.12 is required for full coverage.** NannyML and alibi-detect have no
Python 3.13 release; under 3.13 the run silently drops to 26 detectors instead
of 31. Exact versions are pinned in `results/environment.txt`.

Results are deterministic: probes are fixed arrays built from seeded generators,
and no detector we audit is stochastic. A Tier 2 re-run should reproduce
`results/audit_matrix.csv` exactly, apart from library-version differences.

---

## Layout

```
driftaudit/probes.py            14 adversarial inputs + the behaviour each owes
driftaudit/outcomes.py          outcome taxonomy and expectation-aware verdicts
driftaudit/adapters/base.py     uniform interface; captures warnings and crashes
driftaudit/adapters/textbook.py PSI outside libraries, plus the status-returning fix
driftaudit/adapters/libraries.py scipy / evidently / river / nannyml / alibi-detect
driftaudit/runner.py            runs the battery -> results/audit_matrix.csv
driftaudit/corpus.py            static guard analysis -> results/corpus_sweep.csv
driftaudit/analysis.py          headline tables, family gap, bootstrap, leave-one-out
driftaudit/sensitivity.py       contested probe expectations, all four labellings
driftaudit/figures.py           paper figures
driftaudit/paper_numbers.py     macros + generated tables for the manuscript

paper/                          manuscript, bibliography, generated fragments, checks
results/                        audit matrix, corpus sweep, summaries, pinned versions
SOURCES.md                      provenance of the four non-library implementations
```

## Mapping from paper to artifact

| Paper element | Produced by |
|---|---|
| Table I (probes) | `driftaudit/probes.py` |
| Table II (thresholds) | `driftaudit/adapters/libraries.py`, top of file |
| Table III (family) | `paper/generated/tab_family.tex` |
| Table IV (per detector) | `paper/generated/tab_detectors.tex` |
| Table V (per probe) | `paper/generated/tab_probes.tex` |
| Table VI (sensitivity) | `paper/generated/tab_sensitivity.tex` |
| Table VII (static guards) | `paper/generated/tab_corpus.tex` |
| Figures 1–2 | `driftaudit/figures.py` |
| Every in-text number | `paper/generated/numbers.tex` |

## Column contract: `results/audit_matrix.csv`

434 rows = 31 detectors × 14 probes. One row is one detector's behaviour on one
probe.

| Column | Meaning |
|---|---|
| `detector` | `vendor/name`. `scipy/*` are general-purpose tests wired as gates, not monitoring products. |
| `probe` | Probe key; see `driftaudit/probes.py` for the construction and the rationale. |
| `expectation` | What a correct detector owes the caller: `undefined`, `stable` or `shifted`. |
| `outcome` | What the caller observed: `silent-stable`, `silent-drift`, `explicit-undefined`, `raised`, `unsupported`. |
| `verdict` | `outcome` judged against `expectation`. **`fail-silent` and `fail-miss` are the dangerous pair.** |
| `score` | The value returned, when there was one. |
| `flagged` | Whether the detector said drift, by its own threshold or ours (Table II). |
| `warned` | Whether a warning was emitted. Recorded beside the outcome, never instead of it. |
| `caller_can_tell` | Whether a program could distinguish this from a valid measurement. |
| `detail` | Exception type, status string, or warning count. |

`fail-noisy` (an undefined test reported as drift) is deliberately **not**
counted as dangerous: it is wrong but visible. Grouping it with silent failure
would overstate the paper's claim.

## Things a reviewer may want to check

1. **Adapters do not pre-check their inputs.** The question is what a library
   does when the caller has not thought to guard, so no adapter filters empty
   or degenerate windows before calling.
2. **Call conventions are declared, not assumed.** `ScipyTest` carries an
   explicit `call` strategy because `anderson_ksamp` takes a list of samples
   rather than two positional arguments; getting this wrong silently
   invalidated all 14 of its cells in an earlier run.
3. **Distance thresholds are dimensionless.** Wasserstein and energy distance
   are in data units, so they are normalised by reference dispersion before
   gating; an absolute cut-off flags two samples from the same distribution.
4. **Baseline sanity.** Both control probes are reported in full, including the
   two detectors that miss the large shift (`scipy/mood`, `scipy/ansari`, which
   test scale rather than location) and the seven that alarm on stable data.
   The battery is not constructed to pass itself.
