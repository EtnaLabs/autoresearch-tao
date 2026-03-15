"""
Autoresearch miner — runs training experiments on demand via Bittensor axon.

Registers on the Bittensor testnet, serves an axon endpoint that the
validator queries via dendrite. When queried with an ExperimentResult
synapse, the miner runs train_lite.py and returns metrics.

Usage:
    python miner.py --netuid <NETUID> --wallet.name miner --wallet.hotkey default
    python miner.py --netuid <NETUID> --wallet.name miner --wallet.hotkey default --time-budget 15
"""

import argparse
import hashlib
import os
import subprocess
import sys
import threading
import time

import bittensor as bt

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

        bt.logging.info(f"[{miner_id}] Starting experiment #{exp_num}...")

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
            bt.logging.warning(f"[{miner_id}] Experiment #{exp_num} FAILED (exit code {proc.returncode})")
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
            bt.logging.warning(f"[{miner_id}] Experiment #{exp_num} FAILED (no val_bpb in output)")
            return ExperimentResult(
                agent_id=miner_id,
                status="failed",
                description="no val_bpb in output",
                experiment_key=f"{miner_id}--exp-{exp_num}",
                result_timestamp=time.time(),
            )

        val_bpb = metrics["val_bpb"]
        bt.logging.info(f"[{miner_id}] Experiment #{exp_num} done — val_bpb={val_bpb:.4f}")

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
# Axon handler
# ---------------------------------------------------------------------------

def create_forward_fn(state: MinerState):
    """Create the forward function that handles incoming ExperimentResult synapses."""
    def forward_experiment(synapse: ExperimentResult) -> ExperimentResult:
        if not state.run_lock.acquire(blocking=False):
            bt.logging.warning(f"[{state.miner_id}] Busy — experiment already running")
            synapse.status = "failed"
            synapse.description = "miner busy"
            return synapse

        try:
            state.running = True
            # Use the time_budget from the synapse if provided, else use default
            original_budget = state.time_budget
            if synapse.time_budget > 0:
                state.time_budget = synapse.time_budget

            result = state.run_experiment()

            # Copy result fields into the synapse
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
    """Blacklist function — accept all requests for now (testnet)."""
    def blacklist(synapse: ExperimentResult) -> tuple[bool, str]:
        # On testnet, accept all requests. On mainnet, you'd verify the
        # caller is a registered validator on the subnet.
        return False, ""
    return blacklist


def create_priority_fn():
    """Priority function — equal priority for all (testnet)."""
    def priority(synapse: ExperimentResult) -> float:
        return 0.0
    return priority


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autoresearch miner (Bittensor testnet)")
    # Bittensor args
    parser.add_argument("--netuid", type=int, required=True, help="Subnet UID")
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
    # Miner args
    parser.add_argument("--miner-id", type=str, default="miner-1", help="Miner identifier")
    parser.add_argument("--time-budget", type=int, default=30, help="Training time budget in seconds")
    parser.add_argument("--reward-wallet", type=str, default="",
                        help="SS58 address to receive TAO rewards (defaults to this wallet's coldkey)")
    args = parser.parse_args()

    # --- Wallet ---
    wallet = bt.wallet(name=args.wallet_name, hotkey=args.wallet_hotkey)
    bt.logging.info(f"Wallet: {wallet}")

    # --- Subtensor ---
    if args.chain_endpoint:
        subtensor = bt.subtensor(chain_endpoint=args.chain_endpoint)
    else:
        subtensor = bt.subtensor(network=args.network)
    bt.logging.info(f"Subtensor: {subtensor}")

    # --- Verify registration ---
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

    # --- Reward wallet (default to this wallet's coldkey) ---
    reward_wallet = args.reward_wallet or wallet.coldkeypub.ss58_address
    bt.logging.info(f"Reward wallet: {reward_wallet}")

    # --- Miner state ---
    state = MinerState(miner_id=args.miner_id, time_budget=args.time_budget, reward_wallet=reward_wallet)

    # --- Axon ---
    axon = bt.axon(wallet=wallet, port=args.axon_port,
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
            # Periodically resync metagraph
            metagraph = subtensor.metagraph(args.netuid)
            bt.logging.debug(f"Metagraph synced. Nodes: {metagraph.n.item()}")
    except KeyboardInterrupt:
        bt.logging.info("Shutting down miner...")
        axon.stop()


if __name__ == "__main__":
    main()
