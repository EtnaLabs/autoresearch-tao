"""
Autoresearch validator — queries miners via Bittensor dendrite, scores results,
sets on-chain weights, and serves REST API for the UI.

Connects to Bittensor testnet, discovers miners via the metagraph, queries them
with ExperimentResult synapses, and sets weights proportional to performance.

Usage:
    python validator.py --netuid <NETUID> --wallet.name validator --wallet.hotkey default
    python validator.py --netuid <NETUID> --wallet.name validator --wallet.hotkey default --interval 60
"""

import argparse
import json
import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import bittensor as bt
import torch

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
        self._results: list[dict] = []
        self._best_per_miner: dict[str, dict] = {}
        self._seen_hashes: dict[str, str] = {}
        self._tao_earned: dict[str, float] = {}
        self._reward_wallets: dict[str, str] = {}  # agent_id -> SS58 reward address
        self._results_file = results_file
        self._load()

    def _load(self):
        if os.path.exists(self._results_file):
            try:
                with open(self._results_file) as f:
                    data = json.load(f)
                self._results = data.get("results", [])
                self._tao_earned = data.get("meta", {}).get("taoEarned", {})
                self._reward_wallets = data.get("meta", {}).get("rewardWallets", {})
                for r in self._results:
                    aid = r.get("agent_id", "")
                    if r.get("status") == "completed":
                        existing = self._best_per_miner.get(aid)
                        if not existing or r["val_bpb"] < existing["val_bpb"]:
                            self._best_per_miner[aid] = r
                bt.logging.info(f"Loaded {len(self._results)} existing results from {self._results_file}")
            except Exception as e:
                bt.logging.warning(f"Could not load {self._results_file}: {e}")

    def receive(self, result: ExperimentResult) -> bool:
        now = time.time()
        if result.val_bpb <= 0 or result.status != "completed":
            return False
        if result.val_bpb < MIN_VAL_BPB:
            return False
        if now - result.result_timestamp > STALENESS_THRESHOLD:
            return False

        with self._lock:
            global_best = self.get_global_best_bpb()
            if global_best and global_best > 0:
                result.score = min(1.0, (global_best / result.val_bpb) ** 2)
            else:
                result.score = 1.0

            result.accepted = True
            rd = result.to_dict()
            self._results.append(rd)

            # Track the miner's preferred reward wallet
            if result.reward_wallet:
                self._reward_wallets[result.agent_id] = result.reward_wallet

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
                    "taoEarned": round(self._tao_earned.get(aid, 0.0), 4),
                })
            entries.sort(key=lambda e: e["bestBpb"])
            return entries

    def get_scores_for_uids(self, metagraph, uid_to_agent: dict[int, str]) -> torch.Tensor:
        """Build a weight tensor indexed by UID from current scores."""
        n = metagraph.n.item()
        weights = torch.zeros(n)
        with self._lock:
            for uid, agent_id in uid_to_agent.items():
                best = self._best_per_miner.get(agent_id)
                if best:
                    weights[uid] = best.get("score", 0.0)
        total = weights.sum()
        if total > 0:
            weights = weights / total
        return weights

    def distribute_tao(self):
        with self._lock:
            if not self._best_per_miner:
                return {}
            total_score = sum(r.get("score", 0) for r in self._best_per_miner.values())
            if total_score <= 0:
                return {}
            rewards = {}
            for aid, best in self._best_per_miner.items():
                weight = best.get("score", 0) / total_score
                tao = weight  # normalized weight as TAO share
                self._tao_earned[aid] = self._tao_earned.get(aid, 0.0) + tao
                rewards[aid] = {"round_tao": tao, "total_tao": self._tao_earned[aid]}
            self._save()
            return rewards

    def get_feed(self, n: int = 20) -> list[dict]:
        with self._lock:
            recent = self._results[-n:]
            feed = []
            for r in reversed(recent):
                delta = 0.0
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
        data = {
            "results": self._results,
            "meta": {
                "totalExperiments": len(self._results),
                "globalBestBpb": self.get_global_best_bpb(),
                "lastUpdated": time.time(),
                "taoEarned": self._tao_earned,
            },
        }
        tmp = self._results_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self._results_file)


# ---------------------------------------------------------------------------
# Validator loop (queries miners via dendrite)
# ---------------------------------------------------------------------------

def validator_loop(
    store: SubmissionStore,
    subtensor: bt.subtensor,
    dendrite: bt.dendrite,
    wallet: bt.wallet,
    netuid: int,
    interval: int,
    time_budget: int,
):
    """Background thread: periodically query miners via dendrite and set weights."""
    round_num = 0
    uid_to_agent: dict[int, str] = {}

    while True:
        round_num += 1
        bt.logging.info(f"\n{'='*60}\n  ROUND {round_num}\n{'='*60}")

        # Sync metagraph to discover miners
        metagraph = subtensor.metagraph(netuid)
        my_uid = metagraph.hotkeys.index(wallet.hotkey.ss58_address)

        # Query all UIDs except ourselves
        uids_to_query = [uid for uid in range(metagraph.n.item()) if uid != my_uid]

        if not uids_to_query:
            bt.logging.info("  No miners registered yet. Waiting...")
            time.sleep(interval)
            continue

        bt.logging.info(f"  Querying {len(uids_to_query)} miners...")

        for uid in uids_to_query:
            hotkey = metagraph.hotkeys[uid]
            axon_info = metagraph.axons[uid]

            # Skip if axon has no IP (not serving)
            if not axon_info.ip or axon_info.ip == "0.0.0.0":
                bt.logging.debug(f"  [UID {uid}] not serving, skipping")
                continue

            try:
                bt.logging.info(f"  [UID {uid}] querying {axon_info.ip}:{axon_info.port}...")

                # Send synapse via dendrite
                synapse = ExperimentResult(time_budget=time_budget)
                response = dendrite.query(
                    axons=[axon_info],
                    synapse=synapse,
                    timeout=time_budget + 60,
                )

                # dendrite.query returns a list when given a list of axons
                result = response[0] if isinstance(response, list) else response

                if result.status == "completed" and result.val_bpb > 0:
                    # Map UID to agent_id for weight setting
                    uid_to_agent[uid] = result.agent_id

                    accepted = store.receive(result)
                    status_str = "ACCEPTED" if accepted else "REJECTED"
                    bt.logging.info(
                        f"  [UID {uid} / {result.agent_id}] "
                        f"val_bpb={result.val_bpb:.4f} — {status_str} (score={result.score:.3f})"
                    )
                else:
                    bt.logging.info(f"  [UID {uid}] experiment failed: {result.description[:80]}")

            except Exception as e:
                bt.logging.warning(f"  [UID {uid}] error: {e}")

        # Print round summary
        summary = store.get_summary()
        leaderboard = store.get_leaderboard()

        bt.logging.info(f"\n  --- Round {round_num} Summary ---")
        bt.logging.info(f"  Total experiments: {summary['totalExperiments']}")
        if summary['globalBestBpb']:
            bt.logging.info(f"  Global best BPB:   {summary['globalBestBpb']:.4f}")
        bt.logging.info(f"  Active miners:     {summary['totalMiners']}")

        if leaderboard:
            bt.logging.info(f"\n  --- Leaderboard ---")
            for i, entry in enumerate(leaderboard):
                bt.logging.info(
                    f"  #{i+1} {entry['name']:12s}  val_bpb={entry['bestBpb']:.4f}  "
                    f"score={entry['score']:.3f}  experiments={entry['experiments']}"
                )

        # --- Set on-chain weights ---
        if uid_to_agent:
            weights = store.get_scores_for_uids(metagraph, uid_to_agent)
            nonzero_uids = torch.nonzero(weights).squeeze().tolist()
            if isinstance(nonzero_uids, int):
                nonzero_uids = [nonzero_uids]

            if nonzero_uids:
                uid_tensor = torch.tensor(nonzero_uids, dtype=torch.long)
                weight_tensor = weights[uid_tensor]

                bt.logging.info(f"\n  --- Setting On-Chain Weights ---")
                for uid_val, w_val in zip(nonzero_uids, weight_tensor.tolist()):
                    agent = uid_to_agent.get(uid_val, f"uid-{uid_val}")
                    bt.logging.info(f"  UID {uid_val} ({agent}): weight={w_val:.4f}")

                try:
                    result = subtensor.set_weights(
                        wallet=wallet,
                        netuid=netuid,
                        uids=uid_tensor,
                        weights=weight_tensor,
                        wait_for_inclusion=True,
                    )
                    bt.logging.info(f"  Weights set on-chain: {result}")
                except Exception as e:
                    bt.logging.error(f"  Failed to set weights: {e}")

        # Track TAO distribution locally
        store.distribute_tao()

        bt.logging.info(f"\n  Next round in {interval}s...")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# REST API handler (serves UI — same as before)
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
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        store: SubmissionStore = self.server.store
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/results":
            self._send_json(200, store.get_results())
        elif path == "/api/leaderboard":
            self._send_json(200, store.get_leaderboard())
        elif path == "/api/feed":
            self._send_json(200, store.get_feed())
        elif path == "/api/status":
            self._send_json(200, store.get_summary())
        elif path == "/api/all":
            self._send_json(200, {
                "leaderboard": store.get_leaderboard(),
                "feed": store.get_feed(),
                "results": store.get_results(),
                **store.get_summary(),
            })
        elif path.startswith("/api/miner-stats/"):
            miner_id = path.split("/api/miner-stats/")[1]
            lb = store.get_leaderboard()
            entry = next((e for e in lb if e["id"] == miner_id), None)
            if entry:
                self._send_json(200, entry)
            else:
                self._send_json(404, {"error": "miner not found"})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Autoresearch validator (Bittensor testnet)")
    # Bittensor args
    parser.add_argument("--netuid", type=int, required=True, help="Subnet UID")
    parser.add_argument("--subtensor.network", type=str, default="test", dest="network",
                        help="Subtensor network (default: test)")
    parser.add_argument("--subtensor.chain_endpoint", type=str, default=None, dest="chain_endpoint",
                        help="Subtensor chain endpoint (overrides network)")
    parser.add_argument("--wallet.name", type=str, default="validator", dest="wallet_name",
                        help="Wallet name")
    parser.add_argument("--wallet.hotkey", type=str, default="default", dest="wallet_hotkey",
                        help="Wallet hotkey")
    # Validator args
    parser.add_argument("--api-port", type=int, default=8092, help="REST API port for the UI")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between query rounds")
    parser.add_argument("--results-file", type=str, default="results.json", help="Path to results file")
    parser.add_argument("--time-budget", type=int, default=30, help="Time budget sent to miners")
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

    # --- Dendrite ---
    dendrite = bt.dendrite(wallet=wallet)

    # --- Submission store ---
    store = SubmissionStore(args.results_file)

    # --- REST API server (for the web UI / CLI dashboard) ---
    api_server = HTTPServer(("0.0.0.0", args.api_port), ValidatorAPIHandler)
    api_server.store = store
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()

    print(f"\n{'='*60}")
    print(f"  Autoresearch Validator (Bittensor Testnet)")
    print(f"{'='*60}")
    print(f"  Network:     {args.network}")
    print(f"  Netuid:      {args.netuid}")
    print(f"  UID:         {my_uid}")
    print(f"  Wallet:      {args.wallet_name}/{args.wallet_hotkey}")
    print(f"  Hotkey:      {wallet.hotkey.ss58_address}")
    print(f"  REST API:    http://localhost:{args.api_port}")
    print(f"  Interval:    {args.interval}s between rounds")
    print(f"  Time budget: {args.time_budget}s per miner")
    print(f"  Results:     {args.results_file}")
    print(f"  Metagraph:   {metagraph.n.item()} nodes")
    print(f"{'='*60}")
    print()

    try:
        validator_loop(store, subtensor, dendrite, wallet, args.netuid, args.interval, args.time_budget)
    except KeyboardInterrupt:
        bt.logging.info("Shutting down validator...")
        api_server.shutdown()


if __name__ == "__main__":
    main()
