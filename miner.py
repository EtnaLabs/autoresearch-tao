"""
Autoresearch miner — runs training experiments on demand.

Exposes an HTTP server. When the validator sends POST /run, the miner
executes train_lite.py, parses the results, and returns them as JSON.

In production, this HTTP server would be a Bittensor axon and the
POST /run endpoint would be a Synapse handler.

Usage:
    python miner.py
    python miner.py --port 8091 --miner-id raven
    python miner.py --port 8091 --miner-id raven --time-budget 15
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from protocol import ExperimentResult

# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------

def parse_train_output(stdout: str) -> dict:
    """Parse the summary block after '---' in train_lite.py output."""
    metrics = {}
    lines = stdout.replace("\r", "\n").split("\n")

    found_separator = False
    for line in lines:
        line = line.strip()
        if line == "---":
            found_separator = True
            continue
        if found_separator and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            try:
                if "." in value:
                    metrics[key] = float(value)
                else:
                    metrics[key] = int(value)
            except ValueError:
                metrics[key] = value

    return metrics


def hash_file(path: str) -> str:
    """SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:16]

# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class MinerHandler(BaseHTTPRequestHandler):

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "miner_id": self.server.miner_id})
        elif self.path == "/status":
            status = "running" if self.server.running else "idle"
            self._send_json(200, {
                "status": status,
                "miner_id": self.server.miner_id,
                "experiments_run": self.server.exp_counter,
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            self._send_json(404, {"error": "not found"})
            return

        # Only one experiment at a time
        if not self.server.run_lock.acquire(blocking=False):
            self._send_json(429, {"error": "busy — experiment already running"})
            return

        try:
            self.server.running = True
            result = self._run_experiment()
            self._send_json(200, result.to_dict())
        except Exception as e:
            self._send_json(500, {"error": str(e)})
        finally:
            self.server.running = False
            self.server.run_lock.release()

    def _run_experiment(self) -> ExperimentResult:
        """Run train_lite.py and return the parsed result."""
        self.server.exp_counter += 1
        exp_num = self.server.exp_counter
        miner_id = self.server.miner_id

        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "train_lite.py")
        train_py_hash = hash_file(script)

        print(f"[{miner_id}] Starting experiment #{exp_num}...")

        env = os.environ.copy()
        env["AUTORESEARCH_TIME_BUDGET"] = str(self.server.time_budget)

        proc = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=self.server.time_budget + 60,  # generous timeout
            env=env,
        )

        if proc.returncode != 0:
            print(f"[{miner_id}] Experiment #{exp_num} FAILED (exit code {proc.returncode})")
            stderr_tail = proc.stderr[-500:] if proc.stderr else ""
            return ExperimentResult(
                agent_id=miner_id,
                status="failed",
                description=f"exit code {proc.returncode}: {stderr_tail}",
                experiment_key=f"{miner_id}--exp-{exp_num}",
                timestamp=time.time(),
            )

        metrics = parse_train_output(proc.stdout)

        if not metrics.get("val_bpb"):
            print(f"[{miner_id}] Experiment #{exp_num} FAILED (no val_bpb in output)")
            return ExperimentResult(
                agent_id=miner_id,
                status="failed",
                description="no val_bpb in output",
                experiment_key=f"{miner_id}--exp-{exp_num}",
                timestamp=time.time(),
            )

        val_bpb = metrics["val_bpb"]
        print(f"[{miner_id}] Experiment #{exp_num} done — val_bpb={val_bpb:.4f}")

        return ExperimentResult(
            agent_id=miner_id,
            val_bpb=val_bpb,
            memory_gb=metrics.get("peak_vram_mb", 0) / 1024,
            training_seconds=metrics.get("training_seconds", 0),
            total_tokens_M=metrics.get("total_tokens_M", 0),
            num_steps=int(metrics.get("num_steps", 0)),
            num_params_M=metrics.get("num_params_M", 0),
            mfu_percent=metrics.get("mfu_percent", 0),
            depth=int(metrics.get("depth", 0)),
            status="completed",
            description=f"baseline (depth={int(metrics.get('depth', 0))}, params={metrics.get('num_params_M', 0):.1f}M)",
            experiment_key=f"{miner_id}--exp-{exp_num}--{train_py_hash[:6]}",
            train_py_hash=train_py_hash,
            timestamp=time.time(),
        )

    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autoresearch miner")
    parser.add_argument("--port", type=int, default=8091, help="Port to listen on")
    parser.add_argument("--miner-id", type=str, default="miner-1", help="Miner identifier")
    parser.add_argument("--time-budget", type=int, default=30, help="Training time budget in seconds")
    args = parser.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), MinerHandler)
    server.miner_id = args.miner_id
    server.time_budget = args.time_budget
    server.run_lock = threading.Lock()
    server.running = False
    server.exp_counter = 0

    print(f"=== Autoresearch Miner ===")
    print(f"Miner ID:    {args.miner_id}")
    print(f"Port:        {args.port}")
    print(f"Time budget: {args.time_budget}s per experiment")
    print(f"Endpoints:   POST /run  |  GET /status  |  GET /health")
    print(f"Waiting for validator queries...")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[{args.miner_id}] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
