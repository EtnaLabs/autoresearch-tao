"""
Autoresearch validator — queries miners, scores results, serves REST API.

Periodically sends POST /run to each registered miner, collects experiment
results, scores them (lower val_bpb = better), stores everything in
results.json, and serves a REST API for the UI.

In production, queries would go through Bittensor dendrite/synapse and
weights would be set on-chain via subtensor.set_weights().

Usage:
    python validator.py --miners http://localhost:8091
    python validator.py --miners http://localhost:8091,http://localhost:8093 --interval 45
"""

import argparse
import json
import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

from protocol import ExperimentResult

# Anti-cheat constants
STALENESS_THRESHOLD = 3600  # 1 hour
MIN_VAL_BPB = 0.5          # sanity lower bound

# ---------------------------------------------------------------------------
# Submission store
# ---------------------------------------------------------------------------

class SubmissionStore:
    """Thread-safe store for all experiment results."""

    def __init__(self, results_file: str = "results.json"):
        self._lock = threading.Lock()
        self._results: list[dict] = []           # all results, chronological
        self._best_per_miner: dict[str, dict] = {}  # agent_id -> best result
        self._seen_hashes: dict[str, str] = {}   # train_py_hash -> first agent_id
        self._results_file = results_file
        self._load()

    def _load(self):
        """Load existing results from disk."""
        if os.path.exists(self._results_file):
            try:
                with open(self._results_file) as f:
                    data = json.load(f)
                self._results = data.get("results", [])
                for r in self._results:
                    aid = r.get("agent_id", "")
                    if r.get("status") == "completed":
                        existing = self._best_per_miner.get(aid)
                        if not existing or r["val_bpb"] < existing["val_bpb"]:
                            self._best_per_miner[aid] = r
                print(f"Loaded {len(self._results)} existing results from {self._results_file}")
            except Exception as e:
                print(f"Warning: could not load {self._results_file}: {e}")

    def receive(self, result: ExperimentResult) -> bool:
        """Validate and store a result. Returns True if accepted."""
        now = time.time()

        # Anti-cheat
        if result.val_bpb <= 0 or result.status != "completed":
            return False
        if result.val_bpb < MIN_VAL_BPB:
            return False
        if now - result.timestamp > STALENESS_THRESHOLD:
            return False

        with self._lock:
            # Dedup: first submitter of a train_py_hash wins
            if result.train_py_hash:
                first = self._seen_hashes.get(result.train_py_hash)
                if first and first != result.agent_id:
                    return False
                self._seen_hashes.setdefault(result.train_py_hash, result.agent_id)

            # Score the result
            global_best = self.get_global_best_bpb()
            if global_best and global_best > 0:
                result.score = min(1.0, (global_best / result.val_bpb) ** 2)
            else:
                result.score = 1.0

            result.accepted = True
            rd = result.to_dict()
            self._results.append(rd)

            # Track per-miner best
            existing = self._best_per_miner.get(result.agent_id)
            if not existing or result.val_bpb < existing["val_bpb"]:
                self._best_per_miner[result.agent_id] = rd

            self._save()
            return True

    def get_global_best_bpb(self) -> float:
        if not self._best_per_miner:
            return 0.0
        return min(r["val_bpb"] for r in self._best_per_miner.values())

    def get_results(self) -> list[dict]:
        with self._lock:
            return list(self._results)

    def get_leaderboard(self) -> list[dict]:
        with self._lock:
            entries = []
            # Count experiments and improvements per agent
            agent_experiments: dict[str, int] = {}
            agent_improvements: dict[str, int] = {}
            prev_best: dict[str, float] = {}
            for r in self._results:
                aid = r.get("agent_id", "")
                agent_experiments[aid] = agent_experiments.get(aid, 0) + 1
                if r.get("status") == "completed":
                    bpb = r["val_bpb"]
                    if aid not in prev_best or bpb < prev_best[aid]:
                        if aid in prev_best:
                            agent_improvements[aid] = agent_improvements.get(aid, 0) + 1
                        prev_best[aid] = bpb

            for aid, best in self._best_per_miner.items():
                entries.append({
                    "id": aid,
                    "name": aid,
                    "bestBpb": best["val_bpb"],
                    "experiments": agent_experiments.get(aid, 0),
                    "improvements": agent_improvements.get(aid, 0),
                    "score": best.get("score", 0),
                    "lastSeen": best.get("timestamp", 0),
                })
            entries.sort(key=lambda e: e["bestBpb"])
            return entries

    def get_feed(self, n: int = 20) -> list[dict]:
        with self._lock:
            recent = self._results[-n:]
            feed = []
            for r in reversed(recent):
                delta = 0.0
                # Compute delta vs previous result from this agent
                aid = r.get("agent_id", "")
                for prev in reversed(self._results):
                    if prev is r:
                        continue
                    if prev.get("agent_id") == aid and prev.get("status") == "completed":
                        delta = r.get("val_bpb", 0) - prev.get("val_bpb", 0)
                        break
                feed.append({
                    "agentId": r.get("agent_id", ""),
                    "status": r.get("status", ""),
                    "valBpb": r.get("val_bpb", 0),
                    "delta": round(delta, 6),
                    "description": r.get("description", ""),
                    "timestamp": r.get("timestamp", 0),
                    "score": r.get("score", 0),
                })
            return feed

    def get_summary(self) -> dict:
        with self._lock:
            total = len(self._results)
            completed = [r for r in self._results if r.get("status") == "completed"]
            global_best = self.get_global_best_bpb()
            return {
                "totalExperiments": total,
                "completedExperiments": len(completed),
                "totalMiners": len(self._best_per_miner),
                "globalBestBpb": global_best,
            }

    def _save(self):
        """Persist to disk (must hold lock)."""
        data = {
            "results": self._results,
            "meta": {
                "totalExperiments": len(self._results),
                "globalBestBpb": self.get_global_best_bpb(),
                "lastUpdated": time.time(),
            },
        }
        tmp = self._results_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._results_file)

# ---------------------------------------------------------------------------
# Validator loop (queries miners)
# ---------------------------------------------------------------------------

def validator_loop(store: SubmissionStore, miner_urls: list[str], interval: int):
    """Background thread: periodically query miners and collect results."""
    round_num = 0

    while True:
        round_num += 1
        print(f"\n{'='*60}")
        print(f"  ROUND {round_num}")
        print(f"{'='*60}")

        for url in miner_urls:
            miner_name = url
            try:
                # Check if miner is idle
                status_resp = requests.get(f"{url}/status", timeout=5)
                status = status_resp.json()
                miner_name = status.get("miner_id", url)

                if status.get("status") == "running":
                    print(f"  [{miner_name}] busy, skipping")
                    continue

                print(f"  [{miner_name}] requesting experiment...")

                # Request an experiment (this blocks ~30s)
                resp = requests.post(f"{url}/run", timeout=120, json={})
                result_data = resp.json()

                if resp.status_code != 200:
                    print(f"  [{miner_name}] error: {result_data.get('error', 'unknown')}")
                    continue

                result = ExperimentResult.from_dict(result_data)

                if result.status == "completed":
                    accepted = store.receive(result)
                    status_str = "ACCEPTED" if accepted else "REJECTED"
                    print(f"  [{miner_name}] val_bpb={result.val_bpb:.4f} — {status_str} (score={result.score:.3f})")
                else:
                    print(f"  [{miner_name}] experiment failed: {result.description[:80]}")

            except requests.exceptions.ConnectionError:
                print(f"  [{miner_name}] offline")
            except requests.exceptions.Timeout:
                print(f"  [{miner_name}] timeout")
            except Exception as e:
                print(f"  [{miner_name}] error: {e}")

        # Print round summary
        summary = store.get_summary()
        leaderboard = store.get_leaderboard()

        print(f"\n  --- Round {round_num} Summary ---")
        print(f"  Total experiments: {summary['totalExperiments']}")
        print(f"  Global best BPB:   {summary['globalBestBpb']:.4f}" if summary['globalBestBpb'] else "  Global best BPB:   (none)")
        print(f"  Active miners:     {summary['totalMiners']}")

        if leaderboard:
            print(f"\n  --- Leaderboard ---")
            for i, entry in enumerate(leaderboard):
                print(f"  #{i+1} {entry['name']:12s}  val_bpb={entry['bestBpb']:.4f}  score={entry['score']:.3f}  experiments={entry['experiments']}")

        # Mock on-chain weight setting
        if leaderboard:
            print(f"\n  --- Setting Weights (mock) ---")
            total_score = sum(e["score"] for e in leaderboard)
            for entry in leaderboard:
                weight = entry["score"] / total_score if total_score > 0 else 0
                print(f"  {entry['name']:12s}  weight={weight:.4f}  →  TAO reward ∝ {weight:.4f}")

        print(f"\n  Next round in {interval}s...")
        time.sleep(interval)

# ---------------------------------------------------------------------------
# REST API handler
# ---------------------------------------------------------------------------

class ValidatorAPIHandler(BaseHTTPRequestHandler):

    def _send_json(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        store: SubmissionStore = self.server.store

        if self.path == "/api/results":
            self._send_json(200, store.get_results())
        elif self.path == "/api/leaderboard":
            self._send_json(200, store.get_leaderboard())
        elif self.path == "/api/feed":
            self._send_json(200, store.get_feed())
        elif self.path == "/api/status":
            self._send_json(200, store.get_summary())
        elif self.path == "/api/all":
            # Combined endpoint for the UI
            self._send_json(200, {
                "leaderboard": store.get_leaderboard(),
                "feed": store.get_feed(),
                "results": store.get_results(),
                **store.get_summary(),
            })
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autoresearch validator")
    parser.add_argument("--port", type=int, default=8092, help="REST API port")
    parser.add_argument("--miners", type=str, required=True, help="Comma-separated miner URLs")
    parser.add_argument("--interval", type=int, default=45, help="Seconds between query rounds")
    parser.add_argument("--results-file", type=str, default="results.json", help="Path to results file")
    args = parser.parse_args()

    miner_urls = [u.strip() for u in args.miners.split(",") if u.strip()]
    store = SubmissionStore(args.results_file)

    # Start REST API server
    api_server = HTTPServer(("0.0.0.0", args.port), ValidatorAPIHandler)
    api_server.store = store
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()

    print(f"=== Autoresearch Validator ===")
    print(f"REST API:    http://localhost:{args.port}")
    print(f"  GET /api/all          — full state for UI")
    print(f"  GET /api/leaderboard  — miner rankings")
    print(f"  GET /api/feed         — recent experiments")
    print(f"  GET /api/results      — all results")
    print(f"  GET /api/status       — summary stats")
    print(f"Miners:      {', '.join(miner_urls)}")
    print(f"Interval:    {args.interval}s between rounds")
    print(f"Results:     {args.results_file}")
    print()

    # Check miner connectivity
    for url in miner_urls:
        try:
            resp = requests.get(f"{url}/health", timeout=3)
            info = resp.json()
            print(f"  ✓ {url} — {info.get('miner_id', '?')} online")
        except Exception:
            print(f"  ✗ {url} — offline (will retry)")

    print()

    try:
        validator_loop(store, miner_urls, args.interval)
    except KeyboardInterrupt:
        print("\nShutting down validator...")
        api_server.shutdown()


if __name__ == "__main__":
    main()
