"""
Local demo of the autoresearch-tao Bittensor integration.

Tests protocol, miner state, validator submission store and scoring
without a live subtensor.
"""

import time

import bittensor as bt

# --- 1. Protocol ---
print("=" * 60)
print("1. Protocol: ExperimentResult synapse")
print("=" * 60)

from protocol import ExperimentResult

synapse = ExperimentResult()
synapse.agent_id = "agent-alice"
synapse.val_bpb = 1.23
synapse.memory_gb = 24.0
synapse.status = "completed"
synapse.description = "Increase LR to 0.04"
synapse.experiment_key = "exp-001"
synapse.train_py_hash = "abc123"
synapse.timestamp = time.time()

print(f"  agent_id:      {synapse.agent_id}")
print(f"  val_bpb:       {synapse.val_bpb}")
print(f"  memory_gb:     {synapse.memory_gb}")
print(f"  status:        {synapse.status}")
print(f"  description:   {synapse.description}")
print(f"  train_py_hash: {synapse.train_py_hash}")
print(f"  accepted:      {synapse.accepted}")
print(f"  OK: Synapse created and fields set correctly")
print()

# --- 2. SubmissionStore ---
print("=" * 60)
print("2. SubmissionStore: validator receives miner submissions")
print("=" * 60)

from validator import SubmissionStore

store = SubmissionStore()

# No submissions yet
assert store.get_all() == {}, "Should start empty"
print("  Initial state: empty (correct)")

# First submission
ok = store.receive("hotkey-alice", {
    "val_bpb": 1.5, "agent_id": "alice", "status": "completed", "timestamp": time.time(),
    "train_py_hash": "hash_a",
})
assert ok, "Should accept first submission"
print(f"  First submission: accepted (correct)")

# Worse submission from same miner — should reject
ok = store.receive("hotkey-alice", {
    "val_bpb": 2.0, "agent_id": "alice", "status": "completed", "timestamp": time.time(),
    "train_py_hash": "hash_b",
})
assert not ok, "Should reject worse submission"
print(f"  Worse submission from same miner: rejected (correct)")

# Better submission from same miner — should accept
ok = store.receive("hotkey-alice", {
    "val_bpb": 1.1, "agent_id": "alice", "status": "completed", "timestamp": time.time(),
    "train_py_hash": "hash_c",
})
assert ok, "Should accept better submission"
subs = store.get_all()
assert subs["hotkey-alice"]["val_bpb"] == 1.1
print(f"  Better submission: accepted, val_bpb={subs['hotkey-alice']['val_bpb']} (correct)")

# Submission from different miner
ok = store.receive("hotkey-bob", {
    "val_bpb": 1.3, "agent_id": "bob", "status": "completed", "timestamp": time.time(),
    "train_py_hash": "hash_d",
})
assert ok
print(f"  Second miner submission: accepted (correct)")
print()

# --- 3. Anti-cheat checks ---
print("=" * 60)
print("3. Anti-cheat: submission validation")
print("=" * 60)

store2 = SubmissionStore()

# Stale result
ok = store2.receive("hotkey-stale", {
    "val_bpb": 0.8, "status": "completed", "timestamp": time.time() - 7200,
    "train_py_hash": "hash_stale",
})
assert not ok
print("  Stale result (2hr old): rejected (correct)")

# Invalid status
ok = store2.receive("hotkey-fail", {
    "val_bpb": 0.9, "status": "failed", "timestamp": time.time(),
    "train_py_hash": "hash_fail",
})
assert not ok
print("  Failed status: rejected (correct)")

# Below sanity bound
ok = store2.receive("hotkey-low", {
    "val_bpb": 0.3, "status": "completed", "timestamp": time.time(),
    "train_py_hash": "hash_low",
})
assert not ok
print("  val_bpb below 0.5: rejected (correct)")

# Duplicate train_py_hash from different miner
store2.receive("hotkey-first", {
    "val_bpb": 1.0, "status": "completed", "timestamp": time.time(),
    "train_py_hash": "hash_dup",
})
ok = store2.receive("hotkey-copycat", {
    "val_bpb": 0.9, "status": "completed", "timestamp": time.time(),
    "train_py_hash": "hash_dup",
})
assert not ok
print("  Duplicate train_py_hash (copycat): rejected (correct)")
print()

# --- 4. MinerState push logic ---
print("=" * 60)
print("4. MinerState: tracks best and triggers push")
print("=" * 60)

from unittest.mock import MagicMock
from miner import MinerState

mock_dendrite = MagicMock()
mock_subtensor = MagicMock()
state = MinerState(dendrite=mock_dendrite, subtensor=mock_subtensor, netuid=1)

# Patch _push_to_validator so we don't need real network
push_calls = []
state._push_to_validator = lambda r: (push_calls.append(r), True)[1]

# First result
ok = state.update({"val_bpb": 1.5, "agent_id": "alice", "status": "completed"})
assert ok and len(push_calls) == 1
print(f"  First update: pushed to validator (correct)")

# Worse result — should NOT push
ok = state.update({"val_bpb": 2.0, "agent_id": "alice", "status": "completed"})
assert not ok and len(push_calls) == 1
print(f"  Worse update: not pushed (correct)")

# Better result — should push
ok = state.update({"val_bpb": 1.1, "agent_id": "alice", "status": "completed"})
assert ok and len(push_calls) == 2
print(f"  Better update: pushed to validator (correct)")

best = state.get_best()
assert best["val_bpb"] == 1.1
print(f"  Current best: val_bpb={best['val_bpb']} (correct)")
print()

# --- 5. Coordinator integration ---
print("=" * 60)
print("5. Coordinator: Bittensor methods exist")
print("=" * 60)

from coordinator import Coordinator

coord = Coordinator.__new__(Coordinator)
coord.api_key = None
coord.agent_id = "test-agent"
coord.experiment_count = 0
coord.vram_gb = None
coord.vram_tier = None

assert hasattr(coord, "register_bittensor_identity")
assert hasattr(coord, "report_reward")
print("  register_bittensor_identity: exists")
print("  report_reward: exists")
print()

print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
