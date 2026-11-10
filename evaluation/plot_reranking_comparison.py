# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib>=3.9"]
# ///
"""Visualize the completed MemSearch reranking evaluation from recorded aggregates."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / "docs/assets/evaluation"
OUTPUT.mkdir(parents=True, exist_ok=True)
report = json.loads((ROOT / "reranking-results.json").read_text())
metrics = {(r["language"], r["query_type"], r["method"]): r for r in report["metrics"]}
usage = {(r["provider"], r["language"]): r for r in report["usage"]}
methods = ["baseline", "jev", "voyage"]
colors = {"baseline": "#8997aa", "jev": "#008775", "voyage": "#5753ac"}
labels = {
    "baseline": "Original BGE-M3 order",
    "jev": "Jev 1.13.0",
    "voyage": "Voyage rerank-3",
}
bg, ink, muted = "#fbfcfe", "#192b40", "#64768a"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "svg.fonttype": "none",
        "svg.hashsalt": "memsearch-reranking",
    }
)
fig = plt.figure(figsize=(14, 10.5), facecolor=bg)
grid = fig.add_gridspec(
    2, 2, left=0.205, right=0.96, top=0.73, bottom=0.16, hspace=0.92, wspace=0.28
)
axes = [fig.add_subplot(grid[r, c]) for r in range(2) for c in range(2)]


def base(ax, title, subtitle):
    ax.set_facecolor(bg)
    ax.set_title(title, loc="left", fontsize=16, fontweight="bold", color=ink, pad=32)
    ax.text(0, 1.065, subtitle, transform=ax.transAxes, fontsize=10, color=muted)
    ax.xaxis.grid(True, color="#e4e9ef", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", length=0, labelcolor=muted, pad=8)
    for spine in ax.spines.values():
        spine.set_visible(False)


for c, (field, title, subtitle) in enumerate(
    [
        ("recall_at_5", "Evidence in the top 5", "Recall@5 · higher is better"),
        ("mrr_at_10", "First relevant result", "MRR@10 · higher is better"),
        ("ndcg_at_10", "Overall ranking quality", "NDCG@10 · higher is better"),
    ]
):
    ax = axes[c]
    base(ax, title, subtitle)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1], ["0", ".25", ".50", ".75", "1.0"])
    ax.set_ylim(2.6, -0.6)
    for i, method in enumerate(methods):
        value = metrics[("all", "all", method)][field]
        ax.barh(i, value, height=0.38, color=colors[method], alpha=0.88)
        ax.text(
            value + 0.025,
            i,
            f"{value:.4f}",
            va="center",
            color=colors[method],
            fontsize=12,
            fontweight="bold",
        )
    ax.set_yticks(
        range(3), [labels[m] for m in methods] if c in (0, 2) else ["", "", ""]
    )
    ax.tick_params(axis="y", labelcolor=ink, labelsize=11)

ax = axes[3]
base(ax, "Estimated API cost", "USD / 1,000 queries · lower is better")
ax.set_xlim(0, 0.225)
ax.set_xticks([0, 0.05, 0.10, 0.15, 0.20], ["$0", ".05", ".10", ".15", ".20"])
ax.set_ylim(1.55, -0.6)
ax.set_yticks([0, 1], ["Jev", "Voyage"])
for i, method in enumerate(["jev", "voyage"]):
    rows = [usage[(method, lang)] for lang in ["zh", "en"]]
    cost = (
        sum(r["estimated_cost_usd"] for r in rows)
        / sum(r["requests"] for r in rows)
        * 1000
    )
    ax.barh(i, cost, height=0.36, color=colors[method], alpha=0.88)
    ax.text(
        cost + 0.007,
        i,
        f"${cost:.3f}",
        color=colors[method],
        va="center",
        fontweight="bold",
        fontsize=12,
    )

fig.text(
    0.045,
    0.942,
    "MemSearch Reranking Comparison",
    fontsize=27,
    fontweight="bold",
    color=ink,
)
fig.text(
    0.045,
    0.895,
    "Jev improves the original order; Voyage leads on ranking quality in this evaluation.",
    fontsize=12,
    color=muted,
)
fig.legend(
    handles=[Line2D([0], [0], color=colors[m], lw=7, label=labels[m]) for m in methods],
    loc="upper left",
    bbox_to_anchor=(0.04, 0.86),
    ncol=3,
    frameon=False,
    fontsize=12,
    columnspacing=3,
)
fig.text(
    0.045,
    0.080,
    "2,172 questions in Chinese and English translation · same 10 candidates per question · no input truncation",
    fontsize=11,
    color=muted,
)
fig.text(
    0.045,
    0.047,
    "Costs cover reranking API calls only, using recorded tokens and evaluation-time list prices; account credits are excluded.",
    fontsize=10,
    color=muted,
)
for ext in ["png", "svg"]:
    path = OUTPUT / f"memsearch-reranking-comparison.{ext}"
    fig.savefig(
        path, dpi=220, facecolor=bg, metadata={"Date": None} if ext == "svg" else None
    )
print(OUTPUT / "memsearch-reranking-comparison.png")

svg = OUTPUT / "memsearch-reranking-comparison.svg"
svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
