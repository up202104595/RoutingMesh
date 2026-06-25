#!/usr/bin/env python3
"""Generate a clean multi-hop MANET illustration for chapter 2."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch

ENG = (0.549, 0.176, 0.098)   # FEUP engineering colour
GREY = (0.45, 0.45, 0.45)
LGREY = (0.7, 0.7, 0.7)

# node positions
N = {
    "S": (1.0, 3.0),
    "A": (3.0, 4.1),
    "B": (5.2, 2.6),
    "D": (7.6, 3.6),
    "C": (3.1, 1.4),
    "E": (5.6, 4.6),
    "F": (6.9, 1.3),
}
# in-range links (undirected)
links = [("S", "A"), ("S", "C"), ("A", "B"), ("A", "E"), ("C", "B"),
         ("B", "D"), ("E", "D"), ("B", "F")]
route = [("S", "A"), ("A", "B"), ("B", "D")]   # highlighted multi-hop path
breaking = ("B", "F")                          # link about to break (mobility)

fig, ax = plt.subplots(figsize=(8.4, 4.6))

# radio range around the source (limited range -> needs multi-hop)
ax.add_patch(Circle(N["S"], 2.35, fill=False, ls=(0, (4, 3)),
                    ec=LGREY, lw=1.2, zorder=1))
ax.text(N["S"][0] - 2.0, N["S"][1] + 1.7, "radio range",
        color=GREY, fontsize=9, style="italic")

# ordinary links
for a, b in links:
    if (a, b) == breaking or (b, a) == breaking:
        continue
    if (a, b) in route or (b, a) in route:
        continue
    (x1, y1), (x2, y2) = N[a], N[b]
    ax.plot([x1, x2], [y1, y2], color=LGREY, lw=1.4, zorder=2)

# breaking link (dashed) due to mobility
(x1, y1), (x2, y2) = N[breaking[0]], N[breaking[1]]
ax.plot([x1, x2], [y1, y2], color=GREY, lw=1.4, ls=(0, (2, 2)), zorder=2)
mx, my = (x1 + x2) / 2, (y1 + y2) / 2
ax.text(mx + 0.05, my - 0.35, "link breaking", color=GREY, fontsize=8.5,
        style="italic")

# highlighted multi-hop route with arrowheads
for a, b in route:
    arr = FancyArrowPatch(N[a], N[b], arrowstyle="-|>", mutation_scale=16,
                          color=ENG, lw=2.6, shrinkA=16, shrinkB=16, zorder=3)
    ax.add_patch(arr)

# mobility arrow on F (moving away)
ax.add_patch(FancyArrowPatch(N["F"], (N["F"][0] + 0.9, N["F"][1] - 0.7),
             arrowstyle="-|>", mutation_scale=14, color=GREY, lw=1.6,
             shrinkA=14, shrinkB=0, zorder=3))

# nodes
for name, (x, y) in N.items():
    endpoint = name in ("S", "D")
    fc = "white"
    ec = ENG if endpoint else GREY
    ax.add_patch(Circle((x, y), 0.30, fc=fc, ec=ec, lw=2.2, zorder=4))
    # small antenna stub to suggest a wireless device
    ax.plot([x, x], [y + 0.30, y + 0.52], color=ec, lw=1.6, zorder=4)
    ax.plot([x], [y + 0.52], marker="o", ms=3, color=ec, zorder=4)
    ax.text(x, y, name, ha="center", va="center", fontsize=11,
            fontweight="bold", color=ec, zorder=5)

# endpoint labels
ax.text(N["S"][0], N["S"][1] - 0.62, "source", ha="center", color=ENG,
        fontsize=9.5)
ax.text(N["D"][0], N["D"][1] - 0.62, "destination", ha="center", color=ENG,
        fontsize=9.5)
ax.text((N["A"][0] + N["B"][0]) / 2, 3.55, "multi-hop route",
        ha="center", color=ENG, fontsize=9.5, style="italic")

ax.set_xlim(-1.4, 9.0)
ax.set_ylim(0.2, 5.6)
ax.set_aspect("equal")
ax.axis("off")
fig.tight_layout()
fig.savefig("manet.png", dpi=200, bbox_inches="tight")
print("wrote manet.png")
