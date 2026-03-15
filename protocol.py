"""
Message protocol for autoresearch experiments.

Defines the Synapse subclass used for miner-validator communication
over the Bittensor network.
"""

import time
from typing import Optional

import bittensor as bt


class ExperimentResult(bt.Synapse):
    """A completed experiment result from a miner.

    The validator sends this (mostly empty) to the miner's axon.
    The miner fills in the fields and returns it.
    """

    # --- Request fields (sent by validator) ---
    time_budget: int = 30  # seconds the miner should train for

    # --- Response fields (filled by miner) ---
    agent_id: str = ""
    reward_wallet: str = ""    # SS58 address where this miner wants rewards sent
    val_bpb: float = 0.0
    memory_gb: float = 0.0
    training_seconds: float = 0.0
    total_tokens_M: float = 0.0
    num_steps: int = 0
    num_params_M: float = 0.0
    mfu_percent: float = 0.0
    depth: int = 0
    status: str = ""           # "completed", "failed"
    description: str = ""
    experiment_key: str = ""
    train_py_hash: str = ""    # SHA256 of train.py for dedup
    result_timestamp: float = 0.0  # Unix epoch when result was produced

    # --- Validator-side fields (set after scoring) ---
    accepted: bool = False
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "reward_wallet": self.reward_wallet,
            "val_bpb": self.val_bpb,
            "memory_gb": self.memory_gb,
            "training_seconds": self.training_seconds,
            "total_tokens_M": self.total_tokens_M,
            "num_steps": self.num_steps,
            "num_params_M": self.num_params_M,
            "mfu_percent": self.mfu_percent,
            "depth": self.depth,
            "status": self.status,
            "description": self.description,
            "experiment_key": self.experiment_key,
            "train_py_hash": self.train_py_hash,
            "timestamp": self.result_timestamp,
            "accepted": self.accepted,
            "score": self.score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentResult":
        mapping = {
            "agent_id": "agent_id",
            "reward_wallet": "reward_wallet",
            "val_bpb": "val_bpb",
            "memory_gb": "memory_gb",
            "training_seconds": "training_seconds",
            "total_tokens_M": "total_tokens_M",
            "num_steps": "num_steps",
            "num_params_M": "num_params_M",
            "mfu_percent": "mfu_percent",
            "depth": "depth",
            "status": "status",
            "description": "description",
            "experiment_key": "experiment_key",
            "train_py_hash": "train_py_hash",
            "timestamp": "result_timestamp",
            "accepted": "accepted",
            "score": "score",
        }
        kwargs = {}
        for dict_key, field_name in mapping.items():
            if dict_key in d:
                kwargs[field_name] = d[dict_key]
        return cls(**kwargs)
