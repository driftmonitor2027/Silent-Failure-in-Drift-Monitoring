"""Figures for the paper.

fig_matrix.pdf  the full audit matrix as a heatmap -- the paper's most direct
                artifact, showing at a glance that danger clusters in columns
                (probes) and in blocks of rows (statistic families)
fig_family.pdf  dangerous rate by statistic family
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from driftaudit.analysis import family
from driftaudit.outcomes import DANGEROUS

# Verdict -> (numeric code, colour). Ordered so danger is visually dominant.
CODES = {
    "pass": (0, "#e8f0e8"),
    "safe-undefined": (1, "#bcd4e6"),
    "fail-alarm": (2, "#f6d365"),
    "fail-noisy": (3, "#f3a683"),
    "fail-miss": (4, "#c44536"),
    "fail-silent": (5, "#7a1c1c"),
    "error": (1, "#bcd4e6"),
}
LABELS = ["pass", "safe-undef", "false alarm", "noisy fail", "missed shift",
          "silent fail"]


def _load(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="results/audit_matrix.csv")
    ap.add_argument("--out-dir", default="paper/figs")
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import numpy as np

    rows = _load(Path(args.csv))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    probes = list(dict.fromkeys(r["probe"] for r in rows))
    # Order detectors by family, then by how dangerous they are: the block
    # structure is the finding, so the figure should make it visible.
    danger = defaultdict(int)
    for r in rows:
        danger[r["detector"]] += r["verdict"] in DANGEROUS
    dets = sorted({r["detector"] for r in rows},
                  key=lambda d: (family(d), -danger[d], d))

    grid = np.zeros((len(dets), len(probes)))
    lookup = {(r["detector"], r["probe"]): r["verdict"] for r in rows}
    for i, d in enumerate(dets):
        for j, p in enumerate(probes):
            grid[i, j] = CODES.get(lookup.get((d, p), "pass"), (0, ""))[0]

    colours = [CODES[k][1] for k in
               ("pass", "safe-undefined", "fail-alarm", "fail-noisy",
                "fail-miss", "fail-silent")]
    cmap = matplotlib.colors.ListedColormap(colours)

    fig, ax = plt.subplots(figsize=(7.2, 8.0))
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=5, aspect="auto",
              interpolation="nearest")

    ax.set_xticks(range(len(probes)))
    ax.set_xticklabels([p.replace("_", " ") for p in probes], rotation=55,
                       ha="right", fontsize=7)
    ax.set_yticks(range(len(dets)))
    ax.set_yticklabels(dets, fontsize=7, family="monospace")

    # Separate the family blocks.
    fams = [family(d) for d in dets]
    for i in range(1, len(dets)):
        if fams[i] != fams[i - 1]:
            ax.axhline(i - 0.5, color="black", linewidth=1.1)
    ax.set_xticks(np.arange(-0.5, len(probes), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(dets), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.6)
    ax.tick_params(which="minor", length=0)

    ax.legend(handles=[mpatches.Patch(color=c, label=l)
                       for c, l in zip(colours, LABELS, strict=True)],
              loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=3,
              fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig_matrix.pdf", bbox_inches="tight")
    plt.close(fig)

    # --- family bar chart
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        f = family(r["detector"])
        agg[f][0] += r["verdict"] in DANGEROUS
        agg[f][1] += 1
    order = sorted(agg.items(), key=lambda x: -x[1][0] / x[1][1])
    names = [k for k, _ in order]
    vals = [v[0] / v[1] for _, v in order]

    fig, ax = plt.subplots(figsize=(5.6, 2.7))
    bars = ax.barh(range(len(names)), vals, color="#7a1c1c", edgecolor="black",
                   linewidth=0.4)
    # De-emphasise the two rows that are not audited subjects.
    for i, n in enumerate(names):
        if "n=1" in n or "control" in n:
            bars[i].set_color("#b9b9b9")
            bars[i].set_hatch("//")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("share of cells where a gate is silently disabled", fontsize=8)
    ax.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")
    for i, (v, (_, c)) in enumerate(zip(vals, order, strict=True)):
        ax.text(v + 0.008, i, f"{c[0]}/{c[1]}", va="center", fontsize=7)
    ax.set_xlim(0, max(vals) * 1.25)
    fig.tight_layout()
    fig.savefig(out / "fig_family.pdf", bbox_inches="tight")
    plt.close(fig)

    print(f"Wrote {out}/fig_matrix.pdf and {out}/fig_family.pdf")


if __name__ == "__main__":
    main()
