"""Verify every number in the paper's per-detector table against the results CSV.

Hand-transcribing 31 counts into LaTeX introduced two errors on the first
attempt. This script makes that class of mistake impossible to leave in.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DANGEROUS = {"fail-silent", "fail-miss"}

# LaTeX abbreviations used in the table -> full detector name.
ABBREV = {
    "scipy/wasserstein_dist.": "scipy/wasserstein_distance",
    "nannyml/kolmogorov_sm.": "nannyml/kolmogorov_smirnov",
    "scipy/epps_singleton": "scipy/epps_singleton_2samp",
    "scipy/cramervonmises": "scipy/cramervonmises_2samp",
}


def truth() -> dict[str, int]:
    rows = list(csv.DictReader(
        (REPO / "results/audit_matrix.csv").open(encoding="utf-8")))
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["detector"]] += r["verdict"] in DANGEROUS
    return dict(counts)


def table_entries(_tex: str) -> dict[str, int]:
    """Parse the generated per-detector fragment.

    The table used to be hand-written in the manuscript and this function
    parsed it there. It is now emitted from the results by
    ``driftaudit.paper_numbers``, so this check verifies the *fragment on disk*
    rather than the prose -- which still catches a fragment that was generated
    from a different run than the one in ``results/``.
    """
    frag = REPO / "paper/generated/tab_detectors.tex"
    if not frag.exists():
        raise SystemExit(f"missing {frag}; run driftaudit.paper_numbers")
    out: dict[str, int] = {}
    for name, n in re.findall(r"\\texttt\{([^}]+)\}\s*&\s*(\d+)", frag.read_text(encoding="utf-8")):
        key = name.replace("\\_", "_").strip()
        out[ABBREV.get(key, key)] = int(n)
    return out


def main() -> int:
    expected = truth()
    tex = (REPO / "paper/silent-failure-in-drift-monitoring.tex").read_text(
        encoding="utf-8")
    found = table_entries(tex)

    problems: list[str] = []
    for name, claimed in sorted(found.items()):
        if name not in expected:
            problems.append(f"  table names an unknown detector: {name}")
        elif expected[name] != claimed:
            problems.append(
                f"  {name}: table says {claimed}, data says {expected[name]}")
    for name in sorted(set(expected) - set(found)):
        problems.append(f"  missing from table: {name} ({expected[name]})")

    print(f"checked {len(found)} table entries against {len(expected)} detectors")
    if problems:
        print("MISMATCHES:")
        print("\n".join(problems))
        return 1
    print("all per-detector counts match the results CSV")
    return 0


if __name__ == "__main__":
    sys.exit(main())
