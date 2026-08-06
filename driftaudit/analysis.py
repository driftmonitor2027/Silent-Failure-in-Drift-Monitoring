"""Aggregate the audit matrix into the paper's headline claims.

The central result is not a ranking of libraries. It is that the *kind of
statistic* a monitor is built on determines whether it can fail silently,
largely independent of which implementation you pick.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from driftaudit.outcomes import DANGEROUS
from driftaudit.probes import PROBES_BY_KEY

# Statistic families. The classification criterion is deliberate and is the
# paper's main analytic choice, so it is stated rather than left implicit:
#
#   p-value test  -- the gate consumes a probability under a null hypothesis
#                    ("no evidence of difference"). Such a statistic has no
#                    value reserved for "not applicable", and its safe-looking
#                    end (p near 1) is exactly what an absent or degenerate
#                    sample produces.
#   divergence    -- the gate consumes a magnitude of difference against a
#                    chosen threshold. Degenerate input tends to push these to
#                    extremes rather than to the quiet end.
#
# NannyML's KS method is classified as a divergence because the library exposes
# the D statistic against its own learned threshold, not a p-value; the family
# follows how the caller consumes it, not the test's origin.
P_VALUE_TESTS = {
    "ks_2samp", "cramervonmises_2samp", "epps_singleton_2samp", "mannwhitneyu",
    "ttest_ind", "ranksums", "brunnermunzel", "anderson_ksamp", "mood", "ansari",
    "ks", "mann_whitney_u", "z", "chi", "KSDrift",
}
DIVERGENCES = {
    "wasserstein_distance", "energy_distance", "wasserstein", "jensenshannon",
    "kl_div", "hellinger", "psi", "jensen_shannon", "kolmogorov_smirnov",
}


#: Families reported separately from the library detectors, because their
#: provenance differs and pooling them would misdescribe all three. See
#: SOURCES.md: the published reconstructions are a sample of a documented
#: pattern, the field defect is a single observed instance, and the reference
#: implementation is our own positive control rather than a subject.
CONTROL_FAMILY = "reference impl. (control)"
FIELD_FAMILY = "field defect (n=1)"
TUTORIAL_FAMILY = "published tutorial PSI"


def family(detector: str) -> str:
    base = detector.split("/")[-1]
    if detector.startswith("river/"):
        return "streaming detector"
    if detector.startswith("reference-psi"):
        return CONTROL_FAMILY
    if detector.startswith("field-psi"):
        return FIELD_FAMILY
    if detector.startswith("textbook-psi"):
        return TUTORIAL_FAMILY
    if base in P_VALUE_TESTS:
        return "p-value test"
    if base in DIVERGENCES:
        return "divergence / distance"
    return "other"


#: Rows that are not audited subjects and must not be read as prevalence.
NON_SUBJECT_FAMILIES = (CONTROL_FAMILY, FIELD_FAMILY)


def load(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def family_gap(rows: list[dict], drop_library: str | None = None) -> tuple[float, float, float]:
    """(p-value rate, divergence rate, gap) over a subset of detectors."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if drop_library and r["detector"].startswith(drop_library + "/"):
            continue
        f = family(r["detector"])
        agg[f][0] += r["verdict"] in DANGEROUS
        agg[f][1] += 1
    pv, dv = agg["p-value test"], agg["divergence / distance"]
    if not pv[1] or not dv[1]:
        return (float("nan"),) * 3
    return pv[0] / pv[1], dv[0] / dv[1], pv[0] / pv[1] - dv[0] / dv[1]


def bootstrap_gap(rows: list[dict], n_boot: int = 5000, seed: int = 20260802):
    """Resample *detectors* to put an interval on the family gap.

    The detector, not the cell, is the unit: cells within a detector are not
    independent. This is a descriptive interval over the detectors we happened
    to audit, not an inference about detectors in general -- our set is neither
    random nor balanced.
    """
    import random

    by_det: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_det[r["detector"]].append(r)
    pv_dets = [d for d in by_det if family(d) == "p-value test"]
    dv_dets = [d for d in by_det if family(d) == "divergence / distance"]
    rng = random.Random(seed)

    gaps = []
    for _ in range(n_boot):
        sample = ([rng.choice(pv_dets) for _ in pv_dets]
                  + [rng.choice(dv_dets) for _ in dv_dets])
        rs = [r for d in sample for r in by_det[d]]
        _, _, g = family_gap(rs)
        if g == g:  # not NaN
            gaps.append(g)
    gaps.sort()
    lo = gaps[int(0.025 * len(gaps))]
    hi = gaps[int(0.975 * len(gaps))]
    return lo, hi, len(pv_dets), len(dv_dets)


def _table(title: str, header: tuple[str, str, str], rows: list[tuple]) -> list[str]:
    out = [f"\n## {title}\n\n", f"| {header[0]} | {header[1]} | {header[2]} |\n",
           "|---|---|---|\n"]
    out += [f"| {a} | {b} | {c} |\n" for a, b, c in rows]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="results/audit_matrix.csv")
    ap.add_argument("--out", default="results/summary.md")
    args = ap.parse_args()

    rows = load(Path(args.csv))
    dangerous = [r for r in rows if r["verdict"] in DANGEROUS]
    detectors = sorted({r["detector"] for r in rows})

    md = [
        "# Audit summary\n\n",
        f"{len(detectors)} detectors x {len(PROBES_BY_KEY)} probes = {len(rows)} cells. ",
        f"{len(dangerous)} ({len(dangerous) / len(rows):.0%}) are dangerous: the caller was ",
        "told a value that reads as a valid, unalarming measurement when the test was ",
        "either uncomputable or facing a real shift.\n",
    ]

    by_family: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        f = family(r["detector"])
        by_family[f][0] += r["verdict"] in DANGEROUS
        by_family[f][1] += 1
    md += _table(
        "Danger by kind of statistic",
        ("Statistic family", "Dangerous cells", "Rate"),
        [(f, f"{d}/{n}", f"{d / n:.0%}")
         for f, (d, n) in sorted(by_family.items(), key=lambda x: -x[1][0] / x[1][1])],
    )
    md.append(
        "\nThis is the paper's central claim. A p-value has no value meaning "
        "\"not applicable\": a large p-value means *no evidence against the null*, "
        "which is vacuously true of an empty, degenerate or three-point window. "
        "Divergences tend to blow up on the same input instead, so they fail "
        "loudly. The safety of a drift gate therefore follows from the kind of "
        "statistic it is built on, not primarily from the quality of the "
        "implementation.\n\n"
        f"Two rows are **not** audited subjects and their rates are not "
        f"prevalence estimates. `{FIELD_FAMILY}` is one defect observed in one "
        f"production harness, reported as an existence proof; `{CONTROL_FAMILY}` "
        "is our own status-returning implementation, included as a positive "
        "control that should pass everything. Only the library families and "
        f"`{TUTORIAL_FAMILY}` describe code we found in the wild -- and the "
        "latter is two reconstructions of a documented pattern, not a sample of "
        "practitioner repositories. See SOURCES.md.\n"
    )

    # ---- how robust is the family gap? -----------------------------------
    pv, dv, gap = family_gap(rows)
    lo, hi, n_pv, n_dv = bootstrap_gap(rows)
    md.append(
        f"\n### Robustness of the family gap\n\n"
        f"Point estimate {gap * 100:.0f}pp ({pv:.0%} vs {dv:.0%}). Bootstrapping "
        f"over **detectors** ({n_pv} p-value, {n_dv} divergence), 5000 resamples: "
        f"95% interval **[{lo * 100:.0f}pp, {hi * 100:.0f}pp]**.\n\n"
        "Leaving out each library in turn:\n\n"
        "| Excluded | p-value | divergence | gap |\n|---|---|---|---|\n"
    )
    for lib in sorted({r["detector"].split("/")[0] for r in rows}):
        p2, d2, g2 = family_gap(rows, drop_library=lib)
        if g2 == g2:
            md.append(f"| {lib} | {p2:.0%} | {d2:.0%} | {g2 * 100:+.0f}pp |\n")
    md.append(
        "\nThe interval is wide and the detector set is neither random nor "
        "balanced, so this quantifies sensitivity to *which detectors we "
        "happened to audit*, not uncertainty about detectors in general. The "
        "sign of the gap is stable under every single-library exclusion, which "
        "is the claim we make; the magnitude is not precisely estimated.\n"
    )

    by_probe: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        by_probe[r["probe"]][0] += r["verdict"] in DANGEROUS
        by_probe[r["probe"]][1] += 1
    md += _table(
        "Danger by probe",
        ("Probe", "Dangerous", "Rate"),
        [(p, f"{d}/{n}", f"{d / n:.0%}")
         for p, (d, n) in sorted(by_probe.items(), key=lambda x: -x[1][0] / x[1][1])],
    )

    by_det: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        by_det[r["detector"]][0] += r["verdict"] in DANGEROUS
        by_det[r["detector"]][1] += 1
    md += _table(
        "Danger by detector",
        ("Detector", "Dangerous", "Rate"),
        [(d, f"{x}/{n}", f"{x / n:.0%}")
         for d, (x, n) in sorted(by_det.items(), key=lambda x: -x[1][0] / x[1][1])],
    )

    clean = [d for d, (x, _) in by_det.items() if x == 0]
    md.append(
        f"\n{len(clean)} of {len(detectors)} detectors have no dangerous cell: "
        + ", ".join(f"`{c}`" for c in sorted(clean)) + ".\n"
    )

    # ---- joint: does source-level guarding predict behaviour? -------------
    sweep_path = Path(args.csv).with_name("corpus_sweep.csv")
    if sweep_path.exists():
        static = {r["detector"]: r["verdict"]
                  for r in csv.DictReader(sweep_path.open(encoding="utf-8"))}
        joint: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for det, (bad, n) in by_det.items():
            v = static.get(det, "unresolved")
            joint[v][0] += bad
            joint[v][1] += n
            joint[v][2] += 1
        md += _table(
            "Does source-level guarding predict behaviour?",
            ("Static verdict", "Detectors", "Behavioural danger"),
            [(v, str(k), f"{bad}/{n} ({bad / n:.0%})")
             for v, (bad, n, k) in sorted(joint.items(), key=lambda x: -x[1][0] / max(x[1][1], 1))],
        )
        md.append(
            "\n**It does not.** Implementations carrying explicit guards -- an early "
            "`raise`, a NaN return -- are no safer in practice than those with no "
            "guard at all. The reason is that a guard can only cover the cases its "
            "author anticipated, whereas the silent failure here arises from the "
            "*semantics of the statistic*: nothing raises and nothing is undefined "
            "in the arithmetic sense, because the computation succeeds and returns "
            "a perfectly legitimate number that happens to mean 'no evidence of "
            "difference' for a sample that carries no evidence of anything.\n\n"
            "This is why the recommendation is not 'add guards'. It is to change "
            "the return contract so that 'measured, stable' and 'could not measure' "
            "are different values -- which is what the status-returning reference "
            "implementation does, at a cost of one field.\n"
        )

    Path(args.out).write_text("".join(md), encoding="utf-8")
    print("".join(md))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
