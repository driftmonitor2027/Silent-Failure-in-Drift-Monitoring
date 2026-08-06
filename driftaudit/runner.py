"""Run every detector against every probe and emit the audit matrix."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from driftaudit.adapters.base import probe_detector
from driftaudit.outcomes import (
    DANGEROUS,
    ERROR,
    FAIL_ALARM,
    FAIL_MISS,
    FAIL_NOISY,
    FAIL_SILENT,
    PASS,
    SAFE_UNDEFINED,
    Observation,
    verdict,
)
from driftaudit.probes import PROBES, PROBES_BY_KEY

SYMBOL = {
    PASS: ".",           # behaved correctly for this probe
    SAFE_UNDEFINED: "u", # declined to answer; safe but uninformative
    FAIL_SILENT: "!!",   # undefined test reported as a stable measurement
    FAIL_NOISY: "!n",    # undefined test reported as drift: wrong, but visible
    FAIL_MISS: "!M",     # real shift reported as stable
    FAIL_ALARM: "!A",    # no shift reported as drift
    ERROR: "E",
}


def verdicts(obs: list[Observation]) -> dict[tuple[str, str], str]:
    return {
        (o.detector, o.probe): verdict(o, PROBES_BY_KEY[o.probe].expectation)
        for o in obs
    }


def load_detectors(include_libraries: bool = True) -> list:
    from driftaudit.adapters import textbook

    dets = list(textbook.detectors())
    if include_libraries:
        try:
            from driftaudit.adapters import libraries

            dets.extend(libraries.detectors())
        except ImportError as exc:  # library set is optional
            print(f"  (library adapters unavailable: {exc})")
    return dets


def run(detectors: list) -> list[Observation]:
    return [probe_detector(d, p) for d in detectors for p in PROBES]


def render(obs: list[Observation], detectors: list) -> str:
    names = [d.name for d in detectors]
    v = verdicts(obs)
    width = max(len(n) for n in names) + 2
    cell = 5

    lines = [
        "",
        "AUDIT MATRIX   . pass   u safe-undefined   !! silent-undefined   "
        "!M missed-shift   !A false-alarm   E error",
        "",
    ]
    header = " " * width + "".join(f"{i + 1:>{cell}}" for i in range(len(PROBES)))
    lines.append(header)
    for n in names:
        row = "".join(f"{SYMBOL.get(v[(n, p.key)], '?'):>{cell}}" for p in PROBES)
        lines.append(f"{n:<{width}}{row}")

    lines += ["", "PROBE KEY", ""]
    for i, p in enumerate(PROBES, 1):
        lines.append(f"  {i:>2}. {p.key:<24} expects {p.expectation}")

    lines += ["", "SUMMARY  (dangerous = gate silently disabled)", ""]
    for n in names:
        vs = [v[(n, p.key)] for p in PROBES]
        c = Counter(vs)
        danger = sum(c[d] for d in DANGEROUS)
        lines.append(
            f"  {n:<{width}} dangerous {danger}/{len(PROBES)}   "
            + " ".join(f"{k}={val}" for k, val in sorted(c.items()))
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/audit_matrix.csv")
    ap.add_argument("--no-libraries", action="store_true")
    args = ap.parse_args()

    detectors = load_detectors(include_libraries=not args.no_libraries)
    obs = run(detectors)

    v = verdicts(obs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["detector", "probe", "expectation", "outcome", "verdict",
                    "score", "flagged", "warned", "caller_can_tell", "detail"])
        for o in obs:
            w.writerow([
                o.detector, o.probe, PROBES_BY_KEY[o.probe].expectation, o.outcome,
                v[(o.detector, o.probe)],
                "" if o.score is None else f"{o.score:.6f}",
                "" if o.flagged is None else o.flagged,
                o.warned, o.caller_can_tell, o.detail,
            ])

    print(render(obs, detectors))
    danger = sum(1 for k in v if v[k] in DANGEROUS)
    print(f"\nWrote {out} ({len(obs)} cells, {len(detectors)} detectors, {len(PROBES)} probes)")
    print(f"Dangerous cells (gate silently disabled): {danger}/{len(obs)}")


if __name__ == "__main__":
    main()
