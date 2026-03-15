#!/usr/bin/env python3
"""
autoresearch-tao CLI Dashboard
Terminal version of the web UI with chart, leaderboard, and live research feed.
Fetches live data from the validator API, falls back to seeded mock data.
"""

import math
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone

try:
    import urllib.request
    import json
    HAS_HTTP = True
except ImportError:
    HAS_HTTP = False

# ─── Config ──────────────────────────────────────────────────────────────────

API_BASE = os.environ.get("NEXT_PUBLIC_VALIDATOR_URL") or os.environ.get("VALIDATOR_URL") or "http://localhost:8092"
POLL_INTERVAL = 5  # seconds

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

# ─── Mock Data (fallback) ────────────────────────────────────────────────────

MOCK_AGENTS = [
    {"id": "raven", "name": "raven", "bestBpb": 0.9421, "experiments": 187, "improvements": 12, "score": 0, "lastSeen": 0},
    {"id": "phoenix", "name": "phoenix", "bestBpb": 0.9448, "experiments": 156, "improvements": 9, "score": 0, "lastSeen": 0},
    {"id": "nova", "name": "nova", "bestBpb": 0.9512, "experiments": 203, "improvements": 11, "score": 0, "lastSeen": 0},
    {"id": "cipher", "name": "cipher", "bestBpb": 0.9537, "experiments": 142, "improvements": 7, "score": 0, "lastSeen": 0},
    {"id": "helios", "name": "helios", "bestBpb": 0.9589, "experiments": 98, "improvements": 5, "score": 0, "lastSeen": 0},
    {"id": "sparrow", "name": "sparrow", "bestBpb": 0.9614, "experiments": 312, "improvements": 8, "score": 0, "lastSeen": 0},
    {"id": "forge", "name": "forge", "bestBpb": 0.9448, "experiments": 89, "improvements": 4, "score": 0, "lastSeen": 0},
    {"id": "atlas", "name": "atlas", "bestBpb": 0.9722, "experiments": 67, "improvements": 3, "score": 0, "lastSeen": 0},
]

DESCRIPTIONS = [
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

# Fixed reference time: March 14, 2026 20:00 UTC
MOCK_NOW = 1773705600000
HOUR = 3600_000

def generate_mock_data():
    rand = mulberry32(42)

    def pick_desc():
        return DESCRIPTIONS[int(rand() * len(DESCRIPTIONS))]

    # Timeline
    timeline = []
    start_time = MOCK_NOW - 4 * 24 * HOUR
    span = MOCK_NOW - start_time

    for agent in MOCK_AGENTS:
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
            rand()  # consume extra

            timeline.append({
                "agentId": agent["id"],
                "valBpb": round(bpb, 6),
                "status": "completed" if is_keep else "discard",
                "description": pick_desc(),
                "timestamp": t,
            })

    timeline.sort(key=lambda r: r["timestamp"])

    # Feed
    feed = []
    feed_agent_ids = ["sparrow", "cipher", "nova", "raven", "forge", "phoenix", "helios"]
    for i in range(20):
        agent_id = feed_agent_ids[int(rand() * len(feed_agent_ids))]
        agent = next(a for a in MOCK_AGENTS if a["id"] == agent_id)
        bpb = agent["bestBpb"] + rand() * 0.04 - 0.005
        is_keep = bpb <= agent["bestBpb"] + 0.002
        delta = bpb - agent["bestBpb"]

        feed.append({
            "agentId": agent_id,
            "status": "completed" if is_keep else "discard",
            "valBpb": round(bpb, 6),
            "delta": round(delta, 4),
            "description": pick_desc(),
            "timestamp": MOCK_NOW - (i * 4 + int(rand() * 3)) * 60_000,
        })

    total_exp = sum(a["experiments"] for a in MOCK_AGENTS)
    total_imp = sum(a["improvements"] for a in MOCK_AGENTS)
    best = min(a["bestBpb"] for a in MOCK_AGENTS)

    return MOCK_AGENTS, timeline, feed, total_exp, total_imp, best

# ─── Live Data Fetching ──────────────────────────────────────────────────────

def fetch_live_data():
    """Fetch data from the validator API. Returns None on failure."""
    if not HAS_HTTP:
        return None
    try:
        req = urllib.request.Request(
            f"{API_BASE}/api/all",
            headers={"User-Agent": "autoresearch-tao-cli/1.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        agents_list = []
        for e in (data.get("leaderboard") or []):
            agents_list.append({
                "id": e.get("id", ""),
                "name": e.get("name", e.get("id", "")),
                "bestBpb": e.get("bestBpb", 0),
                "experiments": e.get("experiments", 0),
                "improvements": e.get("improvements", 0),
                "score": e.get("score", 0),
                "lastSeen": e.get("lastSeen", 0),
            })

        timeline = []
        for r in (data.get("results") or []):
            timeline.append({
                "agentId": r.get("agent_id", ""),
                "valBpb": r.get("val_bpb", 0),
                "status": r.get("status", "discard"),
                "description": r.get("description", ""),
                "timestamp": r.get("timestamp", 0) * 1000,  # seconds to ms
            })

        feed = []
        for f in (data.get("feed") or []):
            feed.append({
                "agentId": f.get("agentId", ""),
                "status": f.get("status", "discard"),
                "valBpb": f.get("valBpb", 0),
                "delta": f.get("delta", 0),
                "description": f.get("description", ""),
                "timestamp": f.get("timestamp", 0) * 1000,
            })

        total_exp = data.get("totalExperiments") or sum(a["experiments"] for a in agents_list)
        total_imp = sum(a["improvements"] for a in agents_list)
        best = data.get("globalBestBpb") or (min(a["bestBpb"] for a in agents_list) if agents_list else 0)

        return agents_list, timeline, feed, total_exp, total_imp, best
    except Exception:
        return None

# ─── Dashboard State ─────────────────────────────────────────────────────────

agents = []
timeline_data = []
feed_items = []
total_experiments = 0
total_improvements = 0
global_best_bpb = 0
using_live = False

def refresh_data():
    global agents, timeline_data, feed_items, total_experiments, total_improvements, global_best_bpb, using_live

    result = fetch_live_data()
    if result:
        agents, timeline_data, feed_items, total_experiments, total_improvements, global_best_bpb = result
        using_live = True
    elif not agents:
        # First load failed — use mock data
        agents, timeline_data, feed_items, total_experiments, total_improvements, global_best_bpb = generate_mock_data()
        using_live = False

# ─── Rendering Helpers ────────────────────────────────────────────────────────

def time_ago(ts_ms):
    mins = int((time.time() * 1000 - ts_ms) / 60_000)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}h ago"
    return f"{hrs // 24}d ago"

def strip_ansi(s: str) -> str:
    return re.sub(r'\033\[[0-9;]*m', '', s)

def box(title: str, lines: list[str], width: int, max_lines: int = 999) -> list[str]:
    out = []
    inner = width - 2
    top_title = f" {title} "
    pad = inner - len(top_title)
    out.append(f"{GRAY}+{top_title}{'─' * max(0, pad)}+{RESET}")
    for line in lines[:max_lines]:
        visible = strip_ansi(line)
        padding = max(0, inner - len(visible))
        out.append(f"{GRAY}|{RESET}{line}{' ' * padding}{GRAY}|{RESET}")
    out.append(f"{GRAY}+{'─' * inner}+{RESET}")
    return out

# ─── Scatter Chart (ASCII) ───────────────────────────────────────────────────

def render_chart(width: int, height: int) -> list[str]:
    chart_w = width - 14
    chart_h = height - 4

    if chart_w < 20 or chart_h < 5 or not timeline_data:
        return [f"{DIM}(no data yet){RESET}"]

    all_bpb = [d["valBpb"] for d in timeline_data]
    all_ts = [d["timestamp"] for d in timeline_data]
    min_bpb, max_bpb = min(all_bpb), max(all_bpb)
    min_ts, max_ts = min(all_ts), max(all_ts)

    bpb_range = max_bpb - min_bpb
    if bpb_range == 0:
        bpb_range = 0.01
    min_bpb -= bpb_range * 0.02
    max_bpb += bpb_range * 0.02
    bpb_range = max_bpb - min_bpb
    ts_range = max_ts - min_ts
    if ts_range == 0:
        ts_range = 1

    grid = [[(" ", GRAY) for _ in range(chart_w)] for _ in range(chart_h)]

    # Build running best BPB step-line (same logic as web UI)
    completed = sorted(
        [d for d in timeline_data if d["status"] == "completed"],
        key=lambda d: d["timestamp"],
    )
    best_steps = []  # list of (timestamp, bestBpb)
    running_best = float("inf")
    improvement_set = set()  # timestamps of actual improvements
    for d in completed:
        if d["valBpb"] < running_best:
            if best_steps:
                best_steps.append((d["timestamp"], running_best))  # horizontal to here
            running_best = d["valBpb"]
            best_steps.append((d["timestamp"], running_best))  # vertical drop
            improvement_set.add((d["timestamp"], d["valBpb"]))
    if completed and best_steps and best_steps[-1][0] < completed[-1]["timestamp"]:
        best_steps.append((completed[-1]["timestamp"], running_best))  # extend to end

    # Precompute running best BPB at each completed timestamp
    _best_at = {}
    _rb = float("inf")
    for d in completed:
        if d["valBpb"] < _rb:
            _rb = d["valBpb"]
        _best_at[d["timestamp"]] = _rb

    def best_at_ts(ts):
        """Return the running best BPB at timestamp ts."""
        cur_best = float("inf")
        for t, b in _best_at.items():
            if t <= ts:
                cur_best = b
            else:
                break
        return cur_best

    # Draw the improvement step-line on the grid
    for i in range(len(best_steps) - 1):
        ts0, bpb0 = best_steps[i]
        ts1, bpb1 = best_steps[i + 1]
        x0 = int((ts0 - min_ts) / ts_range * (chart_w - 1))
        x1 = int((ts1 - min_ts) / ts_range * (chart_w - 1))
        y0 = chart_h - 1 - int((bpb0 - min_bpb) / bpb_range * (chart_h - 1))
        y1 = chart_h - 1 - int((bpb1 - min_bpb) / bpb_range * (chart_h - 1))
        y0 = max(0, min(chart_h - 1, y0))
        y1 = max(0, min(chart_h - 1, y1))
        x0 = max(0, min(chart_w - 1, x0))
        x1 = max(0, min(chart_w - 1, x1))
        # Horizontal segment
        if y0 == y1:
            for x in range(min(x0, x1), max(x0, x1) + 1):
                if grid[y0][x][0] == " ":
                    grid[y0][x] = ("─", GREEN)
        else:
            # Vertical segment
            for y in range(min(y0, y1), max(y0, y1) + 1):
                if grid[y][x1][0] == " ":
                    grid[y][x1] = ("│", GREEN)

    # Plot data points: improvements in green, dots above best line in gray
    for d in timeline_data:
        x = int((d["timestamp"] - min_ts) / ts_range * (chart_w - 1))
        y = int((d["valBpb"] - min_bpb) / bpb_range * (chart_h - 1))
        y = chart_h - 1 - y
        y = max(0, min(chart_h - 1, y))
        x = max(0, min(chart_w - 1, x))

        if d["status"] != "completed":
            grid[y][x] = ("·", GRAY)
        elif (d["timestamp"], d["valBpb"]) in improvement_set:
            grid[y][x] = ("●", GREEN)
        elif d["valBpb"] > best_at_ts(d["timestamp"]):
            grid[y][x] = ("·", GRAY)
        else:
            grid[y][x] = ("●", agent_color(d["agentId"]))

    lines = []
    title = f"{BOLD}{FG}  Validation BPB Timeline (lower is better){RESET}"
    lines.append(title)
    lines.append("")

    for row_idx, row in enumerate(grid):
        bpb_val = max_bpb - (row_idx / max(1, chart_h - 1)) * bpb_range
        if row_idx % max(1, chart_h // 5) == 0:
            label = f"{bpb_val:.4f}"
        else:
            label = "      "
        line = f"{GRAY}{label:>8} │{RESET}"
        for ch, color in row:
            line += f"{color}{ch}{RESET}"
        lines.append(line)

    x_axis = f"{GRAY}{'':>8} └{'─' * chart_w}{RESET}"
    lines.append(x_axis)

    ts_labels = ""
    n_labels = min(5, chart_w // 16)
    for i in range(n_labels):
        ts = min_ts + (i / max(1, n_labels - 1)) * ts_range
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        lbl = dt.strftime("%m/%d %H:%M")
        pos = int(i / max(1, n_labels - 1) * (chart_w - len(lbl)))
        ts_labels = ts_labels.ljust(pos + 9) + lbl
    lines.append(f"{GRAY}{ts_labels}{RESET}")

    # Legend — show unique agents from data
    seen = []
    for d in timeline_data:
        if d["agentId"] not in seen:
            seen.append(d["agentId"])
    legend_parts = []
    for aid in seen:
        c = agent_color(aid)
        legend_parts.append(f"{c}●{RESET} {DIM}{aid}{RESET}")
    legend_parts.append(f"{GREEN}──●{RESET} {DIM}improvements{RESET}")
    lines.append("  " + "  ".join(legend_parts))

    return lines

# ─── Leaderboard ──────────────────────────────────────────────────────────────

def render_leaderboard(width: int) -> list[str]:
    sorted_agents = sorted(agents, key=lambda a: a["bestBpb"])
    inner_lines = []

    for i, a in enumerate(sorted_agents):
        c = agent_color(a["id"])
        rank = f"#{i+1}"
        bpb = f"{a['bestBpb']:.6f}"
        exps = f"{a['experiments']}exp"
        impr = f"{a['improvements']}imp"

        # Time since last seen
        if a.get("lastSeen"):
            active = time_ago(a["lastSeen"] * 1000 if a["lastSeen"] < 1e12 else a["lastSeen"])
        else:
            active = ""

        line = f" {GRAY}{rank:>3}{RESET}  {c}●{RESET} {FG}{a['name']:<12}{RESET} {TEAL}{bpb}{RESET}  {DIM}{exps:>6} {impr:>5}{RESET}  {GRAY}{active:>7}{RESET}"
        inner_lines.append(line)

    if not inner_lines:
        inner_lines.append(f" {DIM}No agents yet{RESET}")

    return box("LEADERBOARD", inner_lines, width)

# ─── Live Feed ────────────────────────────────────────────────────────────────

def render_feed(width: int, max_items: int = 15) -> list[str]:
    inner_lines = []
    max_desc = max(10, width - 65)

    for item in feed_items[:max_items]:
        c = agent_color(item["agentId"])
        status_color = TEAL if item["status"] == "completed" else GRAY
        status_label = item["status"].upper()
        delta_color = TEAL if item["delta"] < 0 else GRAY
        delta_sign = "+" if item["delta"] >= 0 else ""
        desc = item["description"][:max_desc]

        line = (
            f" {MUTED}Result:{RESET} [{c}{item['agentId']:<8}{RESET} "
            f"{status_color}{status_label:<10}{RESET}] "
            f"val_bpb={TEAL}{item['valBpb']:.6f}{RESET} "
            f"(delta={delta_color}{delta_sign}{item['delta']:.4f}{RESET}) "
            f"{DIM}| {desc}{RESET}"
        )
        inner_lines.append(line)

        time_line = f" {GRAY}{time_ago(item['timestamp']):>8} by {item['agentId']}{RESET}"
        inner_lines.append(time_line)

    if not inner_lines:
        inner_lines.append(f" {DIM}No experiments yet{RESET}")

    return box("LIVE RESEARCH FEED", inner_lines, width)

# ─── Header ──────────────────────────────────────────────────────────────────

def render_header(width: int) -> list[str]:
    lines = []
    title = "τ autoresearch-tao"
    lines.append(f"{BOLD}{FG}{title:^{width}}{RESET}")

    parts = [
        f"{TEAL}●{RESET} {MUTED}{total_experiments} experiments, {total_improvements} improvements{RESET}",
        f"{TEAL}●{RESET} {MUTED}{len(agents)} research agents contributing{RESET}",
    ]
    if global_best_bpb > 0:
        parts.append(f"{TEAL}●{RESET} {MUTED}best: {global_best_bpb:.4f}{RESET}")

    stats = "    ".join(parts)
    visible_len = len(strip_ansi(stats))
    pad = max(0, (width - visible_len) // 2)
    lines.append(" " * pad + stats)

    source = f"{TEAL}LIVE{RESET}" if using_live else f"{YELLOW}MOCK{RESET}"
    source_line = f"{DIM}[{source}{DIM}]{RESET}"
    source_visible = len(strip_ansi(source_line))
    source_pad = max(0, (width - source_visible) // 2)
    lines.append(" " * source_pad + source_line)

    lines.append(f"{GRAY}{'─' * width}{RESET}")
    return lines

# ─── Main Dashboard ──────────────────────────────────────────────────────────

def render_dashboard():
    term_w, term_h = shutil.get_terminal_size((120, 40))
    width = min(term_w, 200)

    lines = []

    lines.extend(render_header(width))
    lines.append("")

    chart_height = max(12, term_h - 35)
    lines.extend(render_chart(width, chart_height))
    lines.append("")

    lines.extend(render_leaderboard(width))
    lines.append("")

    feed_remaining = max(8, term_h - len(lines) - 3)
    feed_items_count = max(5, feed_remaining // 2 - 2)
    lines.extend(render_feed(width, max_items=feed_items_count))

    lines.append("")
    footer = f"{DIM}Powered by Ensue + Bittensor{RESET}    {GRAY}Press Ctrl+C to exit{RESET}"
    visible_footer = len(strip_ansi(footer))
    pad = max(0, (width - visible_footer) // 2)
    lines.append(" " * pad + footer)

    return "\n".join(lines)


def main():
    refresh_data()

    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write(render_dashboard())
    sys.stdout.write("\n")
    sys.stdout.flush()

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            refresh_data()
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(render_dashboard())
            sys.stdout.write("\n")
            sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write(f"\n{DIM}Dashboard closed.{RESET}\n")


if __name__ == "__main__":
    main()
