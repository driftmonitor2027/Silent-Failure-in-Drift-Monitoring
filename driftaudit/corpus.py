"""Static sweep for the silent-failure pattern in drift-statistic source code.

The behavioural audit (``runner.py``) measures what implementations *do*. This
sweep measures how they are *written*, and classifies the guards that fire when
a statistic cannot be computed:

    return 0.0             silent    -- indistinguishable from "perfectly stable"
    return NaN / None      explicit  -- a caller can test for it
    raise                  explicit  -- impossible to ignore
    clip / nan_to_num      smoothing -- no guard; the undefined case is quietly
                                        converted into a finite small number
    (none)                 no-guard  -- the arithmetic is left to produce
                                        whatever it produces

**Corpus definition.** The functions analysed are exactly the ones behind the
detectors in the behavioural audit, resolved from the live callables rather
than matched by name. This matters: an earlier name-matching version of this
sweep pulled in ``scipy.special.psi_1_1`` (the digamma function), scikit-learn's
t-SNE ``_kl_divergence`` objective, and assorted plumbing -- roughly seven false
positives for every true one, which would have made any reported rate
meaningless. Tying the corpus to the audited detectors also links the paper's
two halves: every static finding has a behavioural row beside it.
"""

from __future__ import annotations

import argparse
import ast
import csv
import inspect
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

SILENT_ZERO = "silent-zero"
EXPLICIT_NAN = "explicit-nan"
EXPLICIT_RAISE = "explicit-raise"
EXPLICIT_STATUS = "explicit-status"
SMOOTHING = "smoothing"
NO_GUARD = "no-guard"

#: Keyword names under which a wrapper object carries the statistic itself.
SCORE_KEYS = ("score", "value", "statistic", "psi", "distance", "metric")
#: Keyword names that carry a machine-readable "could not compute" signal.
STATUS_KEYS = ("status", "reason", "error", "undefined", "state")


@dataclass
class Finding:
    detector: str
    qualname: str
    module: str
    path: str
    line: int
    guards: set[str] = field(default_factory=set)
    error: str = ""

    @property
    def verdict(self) -> str:
        if self.error:
            return "unresolved"
        if SILENT_ZERO in self.guards:
            return SILENT_ZERO
        if self.guards & {EXPLICIT_NAN, EXPLICIT_RAISE, EXPLICIT_STATUS}:
            return "explicit"
        if SMOOTHING in self.guards:
            return SMOOTHING
        return NO_GUARD


def _is_zero(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
            and float(node.value) == 0.0)


def _is_nan(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Attribute) and node.attr in ("nan", "NaN", "NAN"):
        return True
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "float" and node.args):
        a = node.args[0]
        return isinstance(a, ast.Constant) and str(a.value).lower() == "nan"
    return False


def _first_of(node: ast.AST, pred) -> bool:
    """Match the statistic itself, however the return wraps it.

    Implementations return the value bare, as ``(value, flag)``, or inside a
    result object such as ``Result(score=0.0)``. Only understanding the bare
    form misclassified both the tutorial zero-guard (which returns a wrapper
    holding zero) and the status-returning reference implementation, so the
    wrapper forms are unwrapped here.
    """
    if isinstance(node, ast.Tuple) and node.elts:
        return pred(node.elts[0])
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg in SCORE_KEYS and pred(kw.value):
                return True
        if node.args and pred(node.args[0]):
            return True
        return False
    return pred(node)


def _is_status_return(node: ast.AST) -> bool:
    """A return that carries a machine-readable 'cannot compute' signal."""
    if not isinstance(node, ast.Call):
        return False
    for kw in node.keywords:
        if kw.arg in STATUS_KEYS and not (
            isinstance(kw.value, ast.Constant) and kw.value.value is None
        ):
            return True
    return False


class _GuardScan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.guards: set[str] = set()
        self._depth = 0

    def visit_If(self, node: ast.If) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None:
            # Only a *conditional* return of zero is a guard. An unconditional
            # trailing `return 0.0` is simply the function's result.
            if _is_status_return(node.value):
                self.guards.add(EXPLICIT_STATUS)
            elif self._depth and _first_of(node.value, _is_zero):
                self.guards.add(SILENT_ZERO)
            elif _first_of(node.value, _is_nan):
                self.guards.add(EXPLICIT_NAN)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.guards.add(EXPLICIT_RAISE)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        if name in ("clip", "clamp", "nan_to_num", "fillna"):
            self.guards.add(SMOOTHING)
        self.generic_visit(node)


#: Everything up to and including the environment's package root.
_PKG_ROOT = re.compile(r"^.*?[\\/](?:site-packages|dist-packages)[\\/]", re.I)

#: The checkout this package runs from; its own adapters are reported relative to it.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _relative_source(path: str) -> str:
    """Where a detector's source lives, without saying whose machine it is.

    ``inspect.getsourcefile`` returns an absolute path, which on Windows
    embeds the operator's account name. This file ships to reviewers in a
    double-anonymous artifact, and the column is provenance rather than a
    result -- nothing reads it -- so the part before ``site-packages`` is
    dropped and the informative half kept. The audit's own implementations
    live in this checkout rather than in an environment, so they are made
    relative to it: an absolute path there names the directory it was cloned
    into, which is just as much the operator's business.
    """
    trimmed = _PKG_ROOT.sub("", path)
    if trimmed != path:
        return "site-packages/" + trimmed.replace("\\", "/")
    try:
        return Path(path).resolve().relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return path


def analyze_callable(detector_name: str, fn) -> Finding:
    """Resolve a live callable to source and classify its guards."""
    try:
        src = textwrap.dedent(inspect.getsource(fn))
        path = _relative_source(inspect.getsourcefile(fn) or "?")
        line = inspect.getsourcelines(fn)[1]
        module = getattr(fn, "__module__", "?") or "?"
        qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", "?"))
    except (OSError, TypeError) as exc:
        return Finding(detector_name, "?", "?", "?", 0, error=type(exc).__name__)

    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return Finding(detector_name, qualname, module, path, line,
                       error=f"SyntaxError: {exc.msg}")

    scan = _GuardScan()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in node.body:
                scan.visit(child)
            break
    return Finding(detector_name, qualname, module, path, line, scan.guards)


def _resolve(detector):
    """The callable that actually computes the statistic for this detector."""
    name = detector.name
    if name.startswith("scipy/"):
        from scipy import stats
        return getattr(stats, name.split("/", 1)[1], None)
    if name.startswith("evidently/"):
        return getattr(detector, "test", None) and detector.test.func
    if name.startswith("river/"):
        from river import drift
        cls = getattr(drift, detector.cls_name, None)
        return getattr(cls, "update", None) if cls else None
    if name.startswith("nannyml/"):
        try:
            import nannyml.drift.univariate.methods as m

            # NannyML splits each method by column type, so the continuous
            # variants are the ones our numeric contract exercises.
            cls = {
                "jensen_shannon": "ContinuousJensenShannonDistance",
                "hellinger": "ContinuousHellingerDistance",
                "kolmogorov_smirnov": "KolmogorovSmirnovStatistic",
                "wasserstein": "WassersteinDistance",
            }.get(detector.method)
            target = getattr(m, cls, None) if cls else None
            # The statistic itself lives in _calculate, not the class body.
            return getattr(target, "_calculate", None) or target
        except Exception:
            return None
    if name.startswith("alibi-detect/"):
        try:
            from alibi_detect.cd import KSDrift
            return KSDrift.score
        except Exception:
            return None
    if name.startswith(("textbook-psi", "field-psi", "reference-psi")):
        return type(detector).score
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/corpus_sweep.csv")
    args = ap.parse_args()

    from driftaudit.runner import load_detectors

    detectors = load_detectors(include_libraries=True)
    findings: list[Finding] = []
    for d in detectors:
        fn = _resolve(d)
        if fn is None:
            findings.append(Finding(d.name, "?", "?", "?", 0, error="unresolved"))
            continue
        findings.append(analyze_callable(d.name, fn))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["detector", "qualname", "module", "line", "verdict", "guards", "path"])
        for f in sorted(findings, key=lambda x: x.detector):
            w.writerow([f.detector, f.qualname, f.module, f.line, f.verdict,
                        "|".join(sorted(f.guards)) or f.error, f.path])

    from collections import Counter

    resolved = [f for f in findings if f.verdict != "unresolved"]
    c = Counter(f.verdict for f in resolved)
    print(f"\nCORPUS SWEEP -- {len(resolved)} of {len(findings)} audited detectors "
          f"resolved to source\n")
    print(f"{'detector':<30}{'verdict':<14}guards")
    for f in sorted(findings, key=lambda x: (x.verdict, x.detector)):
        print(f"  {f.detector:<28}{f.verdict:<14}{'|'.join(sorted(f.guards)) or f.error}")
    print(f"\n{'':<2}{'TOTAL':<28}" + "  ".join(f"{k}={v}" for k, v in sorted(c.items())))
    n = len(resolved) or 1
    print(f"\nNo guard at all: {c[NO_GUARD]}/{len(resolved)} ({c[NO_GUARD] / n:.0%}).")
    print(f"Explicit signal: {c['explicit']}/{len(resolved)} ({c['explicit'] / n:.0%}).")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
