"""
Autoresearch miner — runs training experiments on demand.

Supports two modes:
  --local   : HTTP server (no Bittensor needed, for local dev)
  --netuid  : Bittensor testnet mode via axon/dendrite

Usage (local):
    python miner.py --local --port 8091 --miner-id raven --time-budget 15

Usage (testnet):
    python miner.py --netuid <NETUID> --wallet.name miner --wallet.hotkey default
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

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
# Experiment runner
# ---------------------------------------------------------------------------

class MinerState:
    def __init__(self, miner_id: str, time_budget: int, reward_wallet: str = ""):
        self.miner_id = miner_id
        self.time_budget = time_budget
        self.reward_wallet = reward_wallet  # SS58 address for receiving rewards
        self.exp_counter = 0
        self.running = False
        self.run_lock = threading.Lock()

    def run_experiment(self) -> ExperimentResult:
        """Run train_lite.py and return the parsed result as a synapse."""
        self.exp_counter += 1
        exp_num = self.exp_counter
        miner_id = self.miner_id

        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "train_lite.py")
        train_py_hash = hash_file(script)

        print(f"[{miner_id}] Starting experiment #{exp_num}...")

        env = os.environ.copy()
        env["AUTORESEARCH_TIME_BUDGET"] = str(self.time_budget)

        proc = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            timeout=self.time_budget + 60,
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
                result_timestamp=time.time(),
            )

        metrics = parse_train_output(proc.stdout)

        if not metrics.get("val_bpb"):
            print(f"[{miner_id}] Experiment #{exp_num} FAILED (no val_bpb in output)")
            return ExperimentResult(
                agent_id=miner_id,
                status="failed",
                description="no val_bpb in output",
                experiment_key=f"{miner_id}--exp-{exp_num}",
                result_timestamp=time.time(),
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
            result_timestamp=time.time(),
        )


# ---------------------------------------------------------------------------
# Local HTTP handler (for --local mode)
# ---------------------------------------------------------------------------

class LocalMinerHandler(BaseHTTPRequestHandler):

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        state: MinerState = self.server.state
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "miner_id": state.miner_id})
        elif self.path == "/status":
            status = "running" if state.running else "idle"
            self._send_json(200, {
                "status": status,
                "miner_id": state.miner_id,
                "experiments_run": state.exp_counter,
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            self._send_json(404, {"error": "not found"})
            return

        state: MinerState = self.server.state
        if not state.run_lock.acquire(blocking=False):
            self._send_json(429, {"error": "busy — experiment already running"})
            return

        try:
            state.running = True
            result = state.run_experiment()
            self._send_json(200, result.to_dict())
        except Exception as e:
            self._send_json(500, {"error": str(e)})
        finally:
            state.running = False
            state.run_lock.release()

    def log_message(self, format, *args):
        pass


# ---------------------------------------------------------------------------
# Axon handler (for --netuid testnet mode)
# ---------------------------------------------------------------------------

def create_forward_fn(state: MinerState):
    """Create the forward function that handles incoming ExperimentResult synapses."""
    import bittensor as bt

    def forward_experiment(synapse: ExperimentResult) -> ExperimentResult:
        if not state.run_lock.acquire(blocking=False):
            bt.logging.warning(f"[{state.miner_id}] Busy — experiment already running")
            synapse.status = "failed"
            synapse.description = "miner busy"
            return synapse

        try:
            state.running = True
            original_budget = state.time_budget
            if synapse.time_budget > 0:
                state.time_budget = synapse.time_budget

            result = state.run_experiment()

            synapse.agent_id = result.agent_id
            synapse.reward_wallet = state.reward_wallet
            synapse.val_bpb = result.val_bpb
            synapse.memory_gb = result.memory_gb
            synapse.training_seconds = result.training_seconds
            synapse.total_tokens_M = result.total_tokens_M
            synapse.num_steps = result.num_steps
            synapse.num_params_M = result.num_params_M
            synapse.mfu_percent = result.mfu_percent
            synapse.depth = result.depth
            synapse.status = result.status
            synapse.description = result.description
            synapse.experiment_key = result.experiment_key
            synapse.train_py_hash = result.train_py_hash
            synapse.result_timestamp = result.result_timestamp

            state.time_budget = original_budget
            return synapse
        except Exception as e:
            bt.logging.error(f"[{state.miner_id}] Experiment error: {e}")
            synapse.status = "failed"
            synapse.description = str(e)
            return synapse
        finally:
            state.running = False
            state.run_lock.release()

    return forward_experiment


def create_blacklist_fn():
    def blacklist(synapse: ExperimentResult) -> tuple[bool, str]:
        return False, ""
    return blacklist


def create_priority_fn():
    def priority(synapse: ExperimentResult) -> float:
        return 0.0
    return priority


# ---------------------------------------------------------------------------
# Helper: register with validator + poll TAO (local mode)
# ---------------------------------------------------------------------------

def register_with_validator(validator_url: str, miner_url: str, miner_id: str):
    try:
        resp = requests.post(
            f"{validator_url}/api/register",
            json={"url": miner_url, "miner_id": miner_id},
            timeout=5,
        )
        if resp.status_code == 200:
            print(f"Registered with validator at {validator_url}")
        else:
            print(f"Warning: registration returned {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"Warning: could not register with validator: {e}")


def poll_tao(validator_url: str, miner_id: str):
    last_tao = 0.0
    while True:
        time.sleep(15)
        try:
            resp = requests.get(f"{validator_url}/api/miner-stats/{miner_id}", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                tao = data.get("taoEarned", 0.0)
                if tao != last_tao:
                    print(f"[{miner_id}] TAO earned: {tao:.4f}")
                    last_tao = tao
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autoresearch miner")
    # Mode
    parser.add_argument("--local", action="store_true",
                        help="Run in local HTTP mode (no Bittensor)")
    parser.add_argument("--port", type=int, default=8091, help="[local mode] HTTP port")
    parser.add_argument("--validator", type=str, default="http://localhost:8092",
                        help="[local mode] Validator URL to register with")
    parser.add_argument("--external-url", type=str, default="",
                        help="[local mode] External URL for this miner (e.g. ngrok)")
    # Bittensor args (testnet mode)
    parser.add_argument("--netuid", type=int, default=None, help="Subnet UID (enables testnet mode)")
    parser.add_argument("--subtensor.network", type=str, default="test", dest="network",
                        help="Subtensor network (default: test)")
    parser.add_argument("--subtensor.chain_endpoint", type=str, default=None, dest="chain_endpoint",
                        help="Subtensor chain endpoint (overrides network)")
    parser.add_argument("--wallet.name", type=str, default="miner", dest="wallet_name",
                        help="Wallet name")
    parser.add_argument("--wallet.hotkey", type=str, default="default", dest="wallet_hotkey",
                        help="Wallet hotkey")
    parser.add_argument("--axon.port", type=int, default=8091, dest="axon_port",
                        help="Axon port")
    parser.add_argument("--axon.external_ip", type=str, default=None, dest="axon_external_ip",
                        help="External IP for axon (if behind NAT)")
    parser.add_argument("--axon.external_port", type=int, default=None, dest="axon_external_port",
                        help="External port for axon (if behind NAT)")
    # Shared args
    parser.add_argument("--miner-id", type=str, default="miner-1", help="Miner identifier")
    parser.add_argument("--time-budget", type=int, default=30, help="Training time budget in seconds")
    parser.add_argument("--reward-wallet", type=str, default="",
                        help="SS58 address to receive TAO rewards (defaults to wallet coldkey in testnet mode)")
    args = parser.parse_args()

    local_mode = args.local or args.netuid is None

    if local_mode:
        # --- Local HTTP mode ---
        state = MinerState(miner_id=args.miner_id, time_budget=args.time_budget,
                           reward_wallet=args.reward_wallet)

        miner_url = args.external_url or f"http://localhost:{args.port}"

        server = HTTPServer(("0.0.0.0", args.port), LocalMinerHandler)
        server.state = state

        print(f"=== Autoresearch Miner (Local Mode) ===")
        print(f"Miner ID:    {args.miner_id}")
        print(f"Port:        {args.port}")
        print(f"Miner URL:   {miner_url}")
        print(f"Validator:   {args.validator}")
        print(f"Time budget: {args.time_budget}s per experiment")
        print(f"Endpoints:   POST /run  |  GET /status  |  GET /health")
        print()

        register_with_validator(args.validator, miner_url, args.miner_id)

        tao_thread = threading.Thread(target=poll_tao, args=(args.validator, args.miner_id), daemon=True)
        tao_thread.start()

        print(f"Waiting for validator queries...")
        print()

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print(f"\n[{args.miner_id}] Shutting down.")
            server.server_close()

    else:
        # --- Bittensor testnet mode ---
        import bittensor as bt

        wallet = bt.Wallet(name=args.wallet_name, hotkey=args.wallet_hotkey)
        bt.logging.info(f"Wallet: {wallet}")

        if args.chain_endpoint:
            subtensor = bt.Subtensor(chain_endpoint=args.chain_endpoint)
        else:
            subtensor = bt.Subtensor(network=args.network)
        bt.logging.info(f"Subtensor: {subtensor}")

        metagraph = subtensor.metagraph(args.netuid)
        if wallet.hotkey.ss58_address not in metagraph.hotkeys:
            bt.logging.error(
                f"Hotkey {wallet.hotkey.ss58_address} is NOT registered on netuid {args.netuid}.\n"
                f"Register with: btcli subnet register --netuid {args.netuid} --subtensor.network {args.network} "
                f"--wallet.name {args.wallet_name} --wallet.hotkey {args.wallet_hotkey}"
            )
            return

        my_uid = metagraph.hotkeys.index(wallet.hotkey.ss58_address)
        bt.logging.info(f"Registered on netuid {args.netuid} with UID {my_uid}")

        reward_wallet = args.reward_wallet or wallet.coldkeypub.ss58_address
        bt.logging.info(f"Reward wallet: {reward_wallet}")

        state = MinerState(miner_id=args.miner_id, time_budget=args.time_budget, reward_wallet=reward_wallet)

        axon = bt.Axon(wallet=wallet, port=args.axon_port,
                       external_ip=args.axon_external_ip,
                       external_port=args.axon_external_port)

        axon.attach(
            forward_fn=create_forward_fn(state),
            blacklist_fn=create_blacklist_fn(),
            priority_fn=create_priority_fn(),
        )

        axon.serve(netuid=args.netuid, subtensor=subtensor)
        axon.start()

        print(f"\n{'='*60}")
        print(f"  Autoresearch Miner (Bittensor Testnet)")
        print(f"{'='*60}")
        print(f"  Network:     {args.network}")
        print(f"  Netuid:      {args.netuid}")
        print(f"  UID:         {my_uid}")
        print(f"  Wallet:      {args.wallet_name}/{args.wallet_hotkey}")
        print(f"  Hotkey:      {wallet.hotkey.ss58_address}")
        print(f"  Axon:        port {args.axon_port}")
        print(f"  Miner ID:    {args.miner_id}")
        print(f"  Reward to:   {reward_wallet}")
        print(f"  Time budget: {args.time_budget}s per experiment")
        print(f"{'='*60}")
        print(f"  Waiting for validator queries via dendrite...")
        print()

        try:
            while True:
                time.sleep(60)
                metagraph = subtensor.metagraph(args.netuid)
                bt.logging.debug(f"Metagraph synced. Nodes: {metagraph.n.item()}")
        except KeyboardInterrupt:
            bt.logging.info("Shutting down miner...")
            axon.stop()


if __name__ == "__main__":
    main()
