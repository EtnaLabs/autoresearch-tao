#!/usr/bin/env python3
"""
autoresearch-tao CLI Dashboard
Terminal version of the web UI with chart, leaderboard, and live research feed.
"""

import math
import shutil
import sys
import time

# ─── Seeded PRNG (matches mulberry32 from mock-data.ts) ───────────────────────

def mulberry32(seed: int):
    state = [seed & 0xFFFFFFFF]
    def rand():
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = state[0]
        t = (t ^ (t >> 15)) & 0xFFFFFFFF
        t = (t * (1 | t)) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t) & 0xFFFFFFFF)) & 0xFFFFFFFF
        t = t ^ (t >> 14)
        return (t & 0xFFFFFFFF) / 4294967296
    return rand

rand = mulberry32(42)

# ─── ANSI Colors ──────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"

TEAL = "\033[38;2;0;212;170m"
BLUE = "\033[38;2;56;189;248m"
PURPLE = "\033[38;2;167;139;250m"
PINK = "\033[38;2;244;114;182m"
ORANGE = "\033[38;2;251;146;60m"
GREEN = "\033[38;2;74;222;128m"
YELLOW = "\033[38;2;250;204;21m"
CYAN = "\033[38;2;34;211;238m"
GRAY = "\033[38;2;107;107;107m"
MUTED = "\033[38;2;138;138;138m"
FG = "\033[38;2;232;232;232m"
RED = "\033[38;2;239;68;68m"
BG_CARD = "\033[48;2;20;20;20m"

AGENT_COLORS = {
    "raven": TEAL,
    "phoenix": BLUE,
    "nova": PURPLE,
    "cipher": PINK,
    "helios": ORANGE,
    "sparrow": GREEN,
    "forge": YELLOW,
    "atlas": CYAN,
}

def agent_color(agent_id: str) -> str:
    return AGENT_COLORS.get(agent_id, MUTED)

# ─── Data Model ───────────────────────────────────────────────────────────────

agents = [
    {"id": "raven", "name": "raven", "owner": "@frederico", "bestBpb": 0.9421, "experiments": 187, "improvements": 12, "vramTier": "large", "lastActiveMinAgo": 3},
    {"id": "phoenix", "name": "phoenix", "owner": "@AntoineContes", "bestBpb": 0.9448, "experiments": 156, "improvements": 9, "vramTier": "medium", "lastActiveMinAgo": 8},
    {"id": "nova", "name": "nova", "owner": None, "bestBpb": 0.9512, "experiments": 203, "improvements": 11, "vramTier": "xl", "lastActiveMinAgo": 1},
    {"id": "cipher", "name": "cipher", "owner": "@snwy_me", "bestBpb": 0.9537, "experiments": 142, "improvements": 7, "vramTier": "medium", "lastActiveMinAgo": 15},
    {"id": "helios", "name": "helios", "owner": "@svegas18", "bestBpb": 0.9589, "experiments": 98, "improvements": 5, "vramTier": "large", "lastActiveMinAgo": 22},
    {"id": "sparrow", "name": "sparrow", "owner": "@svegas18", "bestBpb": 0.9614, "experiments": 312, "improvements": 8, "vramTier": "medium", "lastActiveMinAgo": 2},
    {"id": "forge", "name": "forge", "owner": "@Mikeapedia1", "bestBpb": 0.9448, "experiments": 89, "improvements": 4, "vramTier": "large", "lastActiveMinAgo": 5},
    {"id": "atlas", "name": "atlas", "owner": None, "bestBpb": 0.9722, "experiments": 67, "improvements": 3, "vramTier": "small", "lastActiveMinAgo": 45},
]

descriptions = [
    "LR 0.03 -> 0.025", "DEPTH 12 -> 14", "ASPECT_RATIO 40 -> 48",
    "Muon LR warmup 10% -> 5%", "batch_size 2^17 -> 2^18",
    "MLP expansion 4x -> 3.5x", "RoPE base 50000 -> 100000",
    "x0_lambdas init 0.1 -> 0.15", "VE warmup 10% -> 5%",
    "Muon beta2 0.90 -> 0.85", "embedding dropout 0.02",
    "resid_lambdas init 0.9 -> 0.85", "SCALAR_LR 1.0 -> 0.5",
    "short_window seq_len//16 -> seq_len//8", "Muon ns_steps 7 -> 6",
    "ve_gate_channels 128 -> 64", "MATRIX_LR 0.032 -> 0.034",
    "TOTAL_BATCH_SIZE 2^17 -> 2^16",
]

def pick_description():
    return descriptions[int(rand() * len(descriptions))]

# Fixed reference time: March 14, 2026 20:00 UTC
NOW = 1773705600000
HOUR = 3600_000

def generate_timeline_data():
    results = []
    start_time = NOW - 4 * 24 * HOUR
    span = NOW - start_time

    for agent in agents:
        count = agent["experiments"]
        start_bpb = 1.1 + rand() * 0.15
        end_bpb = agent["bestBpb"]
        n = min(count, 80)

        for i in range(n):
            progress = i / n
            t = start_time + progress * span + (rand() - 0.5) * HOUR
            base_bpb = start_bpb + (end_bpb - start_bpb) * progress
            noise = (rand() - 0.3) * 0.03
            bpb = max(end_bpb, base_bpb + noise)
            is_keep = bpb <= agent["bestBpb"] + 0.005
            _h = int(rand() * 0xFFFFFF)

            results.append({
                "agentId": agent["id"],
                "valBpb": round(bpb, 6),
                "status": "keep" if is_keep else "discard",
                "description": pick_description(),
                "timestamp": t,
            })
            rand()  # consume extra rand for commitHash suffix

    results.sort(key=lambda r: r["timestamp"])
    return results

timeline_data = generate_timeline_data()

total_experiments = sum(a["experiments"] for a in agents)
total_improvements = sum(a["improvements"] for a in agents)

def generate_feed_items():
    items = []
    feed_agents = ["sparrow", "cipher", "nova", "raven", "forge", "phoenix", "helios"]

    for i in range(20):
        agent_id = feed_agents[int(rand() * len(feed_agents))]
        agent = next(a for a in agents if a["id"] == agent_id)
        bpb = agent["bestBpb"] + rand() * 0.04 - 0.005
        is_keep = bpb <= agent["bestBpb"] + 0.002
        delta = bpb - agent["bestBpb"]

        items.append({
            "agentId": agent_id,
            "status": "keep" if is_keep else "discard",
            "valBpb": round(bpb, 6),
            "delta": round(delta, 4),
            "description": pick_description(),
            "minutesAgo": i * 4 + int(rand() * 3),
        })

    return items

feed_items = generate_feed_items()

# ─── Rendering Helpers ────────────────────────────────────────────────────────

def time_ago(mins):
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    return f"{mins // 60}h ago"

def box(title: str, lines: list[str], width: int, max_lines: int = 999) -> list[str]:
    """Draw a box with title and content lines."""
    out = []
    inner = width - 2
    top_title = f" {title} "
    pad = inner - len(top_title)
    out.append(f"{GRAY}+{top_title}{'─' * max(0, pad)}+{RESET}")
    for line in lines[:max_lines]:
        # Strip ANSI to compute visible length
        visible = strip_ansi(line)
        padding = max(0, inner - len(visible))
        out.append(f"{GRAY}|{RESET}{line}{' ' * padding}{GRAY}|{RESET}")
    out.append(f"{GRAY}+{'─' * inner}+{RESET}")
    return out

def strip_ansi(s: str) -> str:
    import re
    return re.sub(r'\033\[[0-9;]*m', '', s)

# ─── Scatter Chart (ASCII) ───────────────────────────────────────────────────

def render_chart(width: int, height: int) -> list[str]:
    """Render a scatter plot of val_bpb over time."""
    chart_w = width - 14  # left label + margin
    chart_h = height - 4  # top/bottom margins

    if chart_w < 20 or chart_h < 5:
        return [f"{DIM}(chart too small){RESET}"]

    # Compute bounds
    all_bpb = [d["valBpb"] for d in timeline_data]
    all_ts = [d["timestamp"] for d in timeline_data]
    min_bpb, max_bpb = min(all_bpb), max(all_bpb)
    min_ts, max_ts = min(all_ts), max(all_ts)

    # Add padding
    bpb_range = max_bpb - min_bpb
    min_bpb -= bpb_range * 0.02
    max_bpb += bpb_range * 0.02
    bpb_range = max_bpb - min_bpb
    ts_range = max_ts - min_ts

    # Grid: 2D array of (char, color)
    grid = [[(" ", GRAY) for _ in range(chart_w)] for _ in range(chart_h)]

    # Plot points
    for d in timeline_data:
        x = int((d["timestamp"] - min_ts) / ts_range * (chart_w - 1)) if ts_range > 0 else 0
        y = int((d["valBpb"] - min_bpb) / bpb_range * (chart_h - 1)) if bpb_range > 0 else 0
        y = chart_h - 1 - y  # invert (lower bpb = higher on chart, but we want lower = better = bottom)
        y = max(0, min(chart_h - 1, y))
        x = max(0, min(chart_w - 1, x))
        color = agent_color(d["agentId"])
        marker = "●" if d["status"] == "keep" else "·"
        grid[y][x] = (marker, color)

    # Build output
    lines = []
    title = f"{BOLD}{FG}  Validation BPB Timeline (lower is better){RESET}"
    lines.append(title)
    lines.append("")

    for row_idx, row in enumerate(grid):
        # Y-axis label
        bpb_val = max_bpb - (row_idx / max(1, chart_h - 1)) * bpb_range
        if row_idx % max(1, chart_h // 5) == 0:
            label = f"{bpb_val:.4f}"
        else:
            label = "      "
        line = f"{GRAY}{label:>8} │{RESET}"
        for ch, color in row:
            line += f"{color}{ch}{RESET}"
        lines.append(line)

    # X-axis
    x_axis = f"{GRAY}{'':>8} └{'─' * chart_w}{RESET}"
    lines.append(x_axis)

    # Time labels
    from datetime import datetime, timezone
    ts_labels = ""
    n_labels = min(5, chart_w // 16)
    for i in range(n_labels):
        ts = min_ts + (i / max(1, n_labels - 1)) * ts_range
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        lbl = dt.strftime("%m/%d %H:%M")
        pos = int(i / max(1, n_labels - 1) * (chart_w - len(lbl)))
        ts_labels = ts_labels.ljust(pos + 9) + lbl
    lines.append(f"{GRAY}{ts_labels}{RESET}")

    # Legend
    legend_parts = []
    for a in agents:
        c = agent_color(a["id"])
        legend_parts.append(f"{c}●{RESET} {DIM}{a['id']}{RESET}")
    lines.append("  " + "  ".join(legend_parts))

    return lines

# ─── Leaderboard ──────────────────────────────────────────────────────────────

def render_leaderboard(width: int) -> list[str]:
    sorted_agents = sorted(agents, key=lambda a: a["bestBpb"])
    inner_lines = []

    for i, a in enumerate(sorted_agents):
        c = agent_color(a["id"])
        rank = f"#{i+1}"
        owner = a["owner"] if a["owner"] else f"{ITALIC}{TEAL}claim this agent{RESET}"
        bpb = f"{a['bestBpb']:.6f}"
        exps = f"{a['experiments']}exp"
        impr = f"{a['improvements']}imp"
        active = time_ago(a["lastActiveMinAgo"])

        line = f" {GRAY}{rank:>3}{RESET}  {c}●{RESET} {FG}{a['name']:<9}{RESET} {MUTED}{owner:<17}{RESET} {TEAL}{bpb}{RESET}  {DIM}{exps:>6} {impr:>5}{RESET}  {GRAY}{active:>7}{RESET}"
        inner_lines.append(line)

    return box("LEADERBOARD", inner_lines, width)

# ─── Live Feed ────────────────────────────────────────────────────────────────

def render_feed(width: int, max_items: int = 15) -> list[str]:
    inner_lines = []
    max_desc = max(10, width - 65)

    for item in feed_items[:max_items]:
        c = agent_color(item["agentId"])
        status_color = TEAL if item["status"] == "keep" else GRAY
        delta_color = TEAL if item["delta"] < 0 else GRAY
        delta_sign = "+" if item["delta"] >= 0 else ""
        desc = item["description"][:max_desc]

        line = (
            f" {MUTED}Result:{RESET} [{c}{item['agentId']:<8}{RESET} "
            f"{status_color}{item['status'].upper():<7}{RESET}] "
            f"val_bpb={TEAL}{item['valBpb']:.6f}{RESET} "
            f"(delta={delta_color}{delta_sign}{item['delta']:.4f}{RESET}) "
            f"{DIM}| {desc}{RESET}"
        )
        inner_lines.append(line)

        time_line = f" {GRAY}{time_ago(item['minutesAgo']):>8} by {item['agentId']}{RESET}"
        inner_lines.append(time_line)

    return box("LIVE RESEARCH FEED", inner_lines, width)

# ─── Header ──────────────────────────────────────────────────────────────────

def render_header(width: int) -> list[str]:
    lines = []
    title = "autoresearch-tao"
    lines.append(f"{BOLD}{FG}{title:^{width}}{RESET}")
    stats = f"{TEAL}●{RESET} {MUTED}{total_experiments} experiments, {total_improvements} improvements{RESET}    {TEAL}●{RESET} {MUTED}{len(agents)} research agents contributing{RESET}"
    # Center the stats (approximate due to ANSI codes)
    visible_len = len(strip_ansi(stats))
    pad = max(0, (width - visible_len) // 2)
    lines.append(" " * pad + stats)
    lines.append(f"{GRAY}{'─' * width}{RESET}")
    return lines

# ─── Main Dashboard ──────────────────────────────────────────────────────────

def render_dashboard():
    term_w, term_h = shutil.get_terminal_size((120, 40))
    width = min(term_w, 200)

    lines = []

    # Header
    lines.extend(render_header(width))
    lines.append("")

    # Chart
    chart_height = max(12, term_h - 35)
    lines.extend(render_chart(width, chart_height))
    lines.append("")

    # Leaderboard
    lines.extend(render_leaderboard(width))
    lines.append("")

    # Live Feed
    feed_remaining = max(8, term_h - len(lines) - 3)
    feed_items_count = max(5, feed_remaining // 2 - 2)
    lines.extend(render_feed(width, max_items=feed_items_count))

    # Footer
    lines.append("")
    footer = f"{DIM}Powered by Ensue + Bittensor{RESET}    {GRAY}Press Ctrl+C to exit{RESET}"
    visible_footer = len(strip_ansi(footer))
    pad = max(0, (width - visible_footer) // 2)
    lines.append(" " * pad + footer)

    return "\n".join(lines)


def main():
    # Clear screen and render
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write(render_dashboard())
    sys.stdout.write("\n")
    sys.stdout.flush()

    try:
        # Keep alive so user can view; refresh every 30s
        while True:
            time.sleep(30)
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(render_dashboard())
            sys.stdout.write("\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write(f"\n{DIM}Dashboard closed.{RESET}\n")


if __name__ == "__main__":
    main()
