"""Fail if the manuscript could disagree with the results.

Guarantees, checked mechanically because each was violated in practice here or
in the sibling paper:

1. No bare numeric literal that should be a generated macro appears in the
   prose. The manuscript once shipped a probe table and verdict spread copied
   from a run that predated an adapter fix, which is exactly the silent
   inconsistency the paper accuses others of.
2. Every generated fragment is newer than the results CSV it derives from, so
   a re-run of the audit without a re-run of the generator is caught.
3. No spelled-out number large enough to be a reported statistic sits in the
   prose, where no digit-based scan would ever find it.
4. Bibliography hygiene: no dangling cite, no uncited entry, no entry type the
   IEEEtran style cannot render.
5. Every documented command is runnable exactly as printed.
6. The clean-detector count is present.

Run before any submission or artifact freeze.
"""

from __future__ import annotations

import ast
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEX = REPO / "paper/silent-failure-in-drift-monitoring.tex"
CSV = REPO / "results/audit_matrix.csv"
GEN = REPO / "paper/generated"
DANGEROUS = {"fail-silent", "fail-miss"}


def live_facts() -> dict[str, str]:
    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
    v = Counter(r["verdict"] for r in rows)
    per_det: dict[str, int] = defaultdict(int)
    for r in rows:
        per_det[r["detector"]] += r["verdict"] in DANGEROUS
    return {
        "cells": str(len(rows)),
        "dangerous": str(sum(v[k] for k in DANGEROUS)),
        "detectors": str(len({r["detector"] for r in rows})),
        "clean": str(sum(1 for n in per_det.values() if n == 0)),
        "pass": str(v["pass"]),
    }


def main() -> int:
    problems: list[str] = []
    facts = live_facts()
    tex = TEX.read_text(encoding="utf-8")
    body = tex.split(r"\begin{document}")[1]

    # 1. No value that has a generated macro may appear as a literal in the
    #    prose. Checking only a hand-picked few let six stale figures through
    #    -- the guard list is now derived from numbers.tex itself, so every
    #    macro added to the generator is policed automatically.
    numbers = (GEN / "numbers.tex")
    if not numbers.exists():
        problems.append("  paper/generated/numbers.tex missing; run driftaudit.paper_numbers")
        macros = {}
    else:
        # Several macros can share a value (e.g. NumProbes and a cell count
        # both being 14), so collect every candidate rather than the last.
        macros: dict[str, list[str]] = {}
        for m in re.finditer(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}",
                             numbers.read_text(encoding="utf-8")):
            macros.setdefault(m.group(2), []).append(m.group(1))

    # Values too generic to police (small integers appear in ordinary prose).
    def policeable(value: str) -> bool:
        if value.endswith("\\%"):
            return True
        return value.isdigit() and int(value) > 12

    for value, names in sorted(macros.items()):
        if not policeable(value):
            continue
        needle = value.replace("\\%", "%")
        pattern = re.escape(needle).replace(r"\%", r"\\?%")
        for n, line in enumerate(body.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("%") or "\\input{" in stripped:
                continue
            # Numbers inside inline math are distribution parameters, effect
            # sizes and the like -- not reported statistics.
            masked = re.sub(r"\$[^$]*\$", lambda mo: " " * len(mo.group(0)), stripped)
            for hit in re.finditer(rf"(?<![\d.]){pattern}(?![\d.])", masked):
                ctx = stripped[max(0, hit.start() - 40):hit.end() + 40]
                problems.append(
                    f"  line {n}: literal '{needle}' -> "
                    f"{' or '.join('\\' + x for x in names)}\n      ...{ctx}...")

    # 2. Generated fragments must be at least as new as the results.
    if not GEN.exists():
        problems.append("  paper/generated/ is missing; run driftaudit.paper_numbers")
    else:
        csv_mtime = CSV.stat().st_mtime
        for frag in sorted(GEN.glob("*.tex")):
            if frag.stat().st_mtime < csv_mtime:
                problems.append(
                    f"  {frag.name} is older than {CSV.name}; regenerate")
        # Figures are rendered from the same CSV and go stale the same way.
        figs = REPO / "paper/figs"
        for fig in sorted(figs.glob("*.pdf")) if figs.exists() else []:
            if fig.stat().st_mtime < csv_mtime:
                problems.append(
                    f"  {fig.name} is older than {CSV.name}; "
                    f"run driftaudit.figures")

    # 3. Spelled-out numbers evade the literal scan entirely -- "Sixteen of our
    #    detectors" survived every earlier pass because it contains no digits.
    #    Any number-word large enough to be a reported statistic is suspect.
    WORDS = ("eleven twelve thirteen fourteen fifteen sixteen seventeen "
             "eighteen nineteen twenty thirty forty fifty sixty seventy "
             "eighty ninety hundred").split()
    for n, line in enumerate(body.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("%"):
            continue
        for w in WORDS:
            for mo in re.finditer(rf"\b{w}\b", stripped, re.IGNORECASE):
                ctx = stripped[max(0, mo.start() - 40):mo.end() + 40]
                problems.append(
                    f"  line {n}: spelled-out number '{mo.group(0)}' -- use a "
                    f"macro if this is a reported statistic\n      ...{ctx}...")

    # 4. Bibliography hygiene: no dangling \cite, no uncited dead weight, and
    #    no entry type that IEEEtran's .bst cannot render.
    bib = REPO / "paper/references.bib"
    if bib.exists():
        btext = bib.read_text(encoding="utf-8")
        cited = {
            k.strip()
            for group in re.findall(r"\\cite\{([^}]*)\}", tex)
            for k in group.split(",")
        }
        # findall yields (type, key); keying by type would collapse every
        # entry sharing a type down to one.
        types = {key.strip(): kind.lower()
                 for kind, key in re.findall(r"^@(\w+)\{([^,]+),", btext, re.M)}
        keys = set(types)
        for missing in sorted(cited - keys):
            problems.append(f"  \\cite{{{missing}}} has no bib entry")
        for unused in sorted(keys - cited):
            problems.append(f"  bib entry '{unused}' is never cited; drop or use it")
        # IEEEtran's bst understands a fixed set; @software is not among them.
        SUPPORTED = {"article", "book", "booklet", "inbook", "incollection",
                     "inproceedings", "manual", "mastersthesis", "misc",
                     "phdthesis", "proceedings", "techreport", "unpublished"}
        for key, kind in sorted(types.items()):
            if kind not in SUPPORTED:
                problems.append(
                    f"  bib entry '{key}' has type @{kind}, which IEEEtran's "
                    f"style file does not define; use @misc")

    # 5. Every documented command must be runnable exactly as printed. Nothing
    #    here checked this class: the sibling paper shipped a reproduction
    #    command reading `--seeds 1,2,3,...,30`, where the ellipsis is not a
    #    seed and the command dies before it starts. Checked statically, so a
    #    missing scientific dependency cannot make the check pass by accident.
    def declared_flags(path: Path) -> set[str]:
        flags: set[str] = set()
        source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(source):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                flags.update(
                    a.value
                    for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                )
        return flags

    for doc in ("ARTIFACT.md", "README.md"):
        path = REPO / doc
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            cmd = line.strip().split("#")[0].strip()
            m = re.match(r"^python (?:-m ([\w.]+)|([\w/]+\.py))\b(.*)", cmd)
            if not m:
                continue
            module, script, rest = m.groups()
            if module:
                target = REPO / (module.replace(".", "/") + ".py")
                if not target.exists():
                    # A stdlib module (python -m venv) is fine; anything else
                    # documented but absent is not.
                    if module.split(".")[0] not in sys.stdlib_module_names:
                        problems.append(f"  {doc}: '{cmd}' names a module that is not here")
                    continue
            else:
                target = REPO / script
                if not target.exists():
                    problems.append(f"  {doc}: '{cmd}' names a script that is not here")
                    continue
            known = declared_flags(target)
            for flag in re.findall(r"(--[\w-]+)", rest):
                if flag not in known:
                    problems.append(
                        f"  {doc}: '{cmd.split()[2] if module else script}' does not "
                        f"accept {flag}"
                    )
            # An input path that does not exist makes the command unrunnable
            # just as surely as an unknown flag.
            for flag, value in re.findall(r"(--csv|--bib)\s+(\S+)", rest):
                if not (REPO / value).exists():
                    problems.append(f"  {doc}: '{cmd}' reads {value}, which is missing")

    # 6. The clean-detector count must match.
    if f"\\NumClean" not in tex and facts["clean"] not in tex:
        problems.append("  clean-detector count is neither a macro nor present")

    print(f"live: {facts['dangerous']}/{facts['cells']} dangerous, "
          f"{facts['detectors']} detectors, {facts['clean']} clean")
    if problems:
        print("FRESHNESS PROBLEMS:")
        print("\n".join(problems))
        return 1
    print("manuscript is consistent with results/audit_matrix.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
