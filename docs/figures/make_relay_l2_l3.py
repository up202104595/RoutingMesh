#!/usr/bin/env python3
"""Relay-hop comparison at N2: Layer 2 (MAC rewrite) vs Layer 3 (this work)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ENG = (0.549, 0.176, 0.098)     # FEUP engineering colour
GREY = (0.40, 0.40, 0.40)
USREG = (0.95, 0.92, 0.88)      # user-space band tint

LAYERS = ["Physical", "Data Link", "Network (IP)", "Transport / App"]
YS = {name: i for i, name in enumerate(LAYERS)}

def draw_panel(ax, title, peak_layer, tag, caption):
    ax.set_title(title, fontsize=12, color=ENG, pad=12, fontweight="bold")

    # user-space band (covers only the Transport/App layer)
    ax.axhspan(2.55, 3.55, xmin=0.03, xmax=0.97, color=USREG, zorder=0)
    ax.text(3.28, 2.74, "user space", ha="right", va="center",
            fontsize=8, style="italic", color=GREY, zorder=1)
    ax.text(3.28, 2.30, "kernel", ha="right", va="center",
            fontsize=8, style="italic", color=GREY, zorder=1)
    ax.plot([0.7, 3.3], [2.5, 2.5], ls=(0, (3, 3)), color=GREY, lw=1.0, zorder=1)

    # protocol-stack boxes for N2
    for name, y in YS.items():
        ax.add_patch(FancyBboxPatch((0.7, y - 0.26), 2.6, 0.52,
                     boxstyle="round,pad=0.02,rounding_size=0.08",
                     fc="white", ec=GREY, lw=1.3, zorder=2))
        ax.text(2.0, y, name, ha="center", va="center", fontsize=10,
                color="black", zorder=3)

    # neighbour markers
    ax.text(-0.42, 0.0, "from\nN1", ha="center", va="center", fontsize=9, color=GREY)
    ax.text(4.42, 0.0, "to\nN3", ha="center", va="center", fontsize=9, color=GREY)

    peak = YS[peak_layer]
    turn = peak + 0.42            # horizontal run sits in the clear gap above the box
    xin, xout = 0.32, 3.68

    def arr(p0, p1):
        ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=14,
                     color=ENG, lw=2.2, shrinkA=0, shrinkB=0, zorder=4))

    arr((-0.08, 0.0), (xin, 0.0))      # in from N1
    arr((xin, 0.0), (xin, turn))       # up the stack
    arr((xin, turn), (xout, turn))     # across, above the peak layer
    arr((xout, turn), (xout, 0.0))     # down the stack
    arr((xout, 0.0), (4.08, 0.0))      # out to N3

    # short tag on the horizontal run (white background for legibility)
    ax.text(2.0, turn, tag, ha="center", va="center", fontsize=9, color=ENG,
            fontweight="bold", zorder=5,
            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none"))

    # description under the panel
    ax.text(2.0, -1.35, caption, ha="center", va="center", fontsize=9.0,
            color="black", zorder=5)

    ax.set_xlim(-0.8, 4.8)
    ax.set_ylim(-1.95, 4.0)
    ax.axis("off")

fig, (axL, axR) = plt.subplots(1, 2, figsize=(10.6, 5.0))

draw_panel(axL, "Layer 2 (Morais)", "Data Link", "MAC rewrite",
           "The frame rises only to the Data Link layer.\n"
           "N2 rewrites the destination MAC and retransmits,\nentirely within the kernel.")
draw_panel(axR, "Layer 3 (this work)", "Transport / App", "TCP rx (user space)",
           "The packet rises to the user-space TCP thread,\n"
           r"then $\mathtt{tun\_write}$ hands it to the kernel" "\n"
           r"$\mathtt{ip\_forward}$ engine and back down.")

fig.tight_layout()
fig.savefig("relay_l2_l3.png", dpi=200, bbox_inches="tight")
print("wrote relay_l2_l3.png")
