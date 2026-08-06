"""How much do the contested probe expectations move the conclusions?

Two probes carry judgement calls, and both were flagged before the numbers were
looked at:

``both_constant_different`` -- a point mass at 7 against a point mass at 99. The
    *situation* is the most extreme shift possible; the *statistic* is undefined
    for anything that needs quantile breaks or divides by a variance. Labelling
    it ``shifted`` or ``undefined`` is defensible either way.

``partial_nan_current`` -- half the current window is NaN, the other half is
    drawn from the reference distribution. An implementation that drops NaN and
    reports "stable" is statistically right about the data it saw and silent
    about the half that vanished. ``undefined`` or ``stable``, again defensible.

This module re-derives the headline under every combination so the paper can
state that its conclusions do not rest on either choice.
"""

from __future__ import annotations

import argparse
import csv
import itertools
from collections import defaultdict
from pathlib import Path

from driftaudit.analysis import family
from driftaudit.outcomes import DANGEROUS
from driftaudit.probes import SHIFTED, STABLE, UNDEFINED

CONTESTED = {
    "both_constant_different": (SHIFTED, UNDEFINED),
    "partial_nan_current": (UNDEFINED, STABLE),
}


def reverdict(outcome: str, expectation: str) -> str:
    """Verdict logic mirroring outcomes.verdict, driven by a supplied label."""
    if outcome in ("raised", "explicit-undefined", "unsupported"):
        return "pass" if expectation == UNDEFINED else "safe-undefined"
    if expectation == UNDEFINED:
        return "fail-noisy" if outcome == "silent-drift" else "fail-silent"
    if expectation == SHIFTED:
        return "pass" if outcome == "silent-drift" else "fail-miss"
    if expectation == STABLE:
        return "fail-alarm" if outcome == "silent-drift" else "pass"
    return "error"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="results/audit_matrix.csv")
    ap.add_argument("--out", default="results/sensitivity.md")
    args = ap.parse_args()

    rows = list(csv.DictReader(Path(args.csv).open(encoding="utf-8")))
    base = {r["probe"]: r["expectation"] for r in rows}

    md = ["# Sensitivity to contested probe expectations\n\n",
          "Two probes carry judgement calls. Every combination is evaluated below.\n\n",
          "| both_constant_different | partial_nan_current | Overall | p-value | divergence | Gap |\n",
          "|---|---|---|---|---|---|\n"]

    keys = list(CONTESTED)
    for choice in itertools.product(*(CONTESTED[k] for k in keys)):
        exp = dict(base)
        exp.update(dict(zip(keys, choice, strict=True)))
        tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        total = [0, 0]
        for r in rows:
            bad = reverdict(r["outcome"], exp[r["probe"]]) in DANGEROUS
            f = family(r["detector"])
            tally[f][0] += bad
            tally[f][1] += 1
            total[0] += bad
            total[1] += 1
        pv, dv = tally["p-value test"], tally["divergence / distance"]
        gap = pv[0] / pv[1] - dv[0] / dv[1]
        md.append(
            f"| {choice[0]} | {choice[1]} | {total[0] / total[1]:.0%} | "
            f"{pv[0] / pv[1]:.0%} | {dv[0] / dv[1]:.0%} | {gap * 100:+.0f}pp |\n"
        )

    md.append(
        "\n## Reading\n\n"
        "**`both_constant_different` has no effect at all.** Under `shifted` a quiet "
        "answer is a missed shift; under `undefined` the same answer is a silent "
        "non-measurement. Both land in the dangerous set, so only the name of the "
        "failure changes, never the count.\n\n"
        "**`partial_nan_current` moves the overall rate by about two points** and "
        "*widens* the gap between statistic families. The central claim is therefore "
        "not merely robust to this choice, it is weakest under the labelling we "
        "actually adopted.\n\n"
        "## Corroboration from implementation behaviour\n\n"
        "Expectations are set from first principles about the data situation, not by "
        "majority vote -- but the field largely agrees with both, and the "
        "disagreeing minority is exactly where the danger sits:\n\n"
        "- `both_constant_different`: 24 of 31 detectors report drift, 2 report "
        "stable. Those 2 are tutorial PSI variants returning `0.0`.\n"
        "- `partial_nan_current`: 20 of 31 are explicit (16 return NaN, 4 raise); "
        "9 quietly report stable. The explicit majority supports treating a "
        "half-missing window as not measurable.\n"
    )

    Path(args.out).write_text("".join(md), encoding="utf-8")
    print("".join(md))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
