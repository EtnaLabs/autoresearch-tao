"""
Message protocol for autoresearch experiments.

Defines the data contract between miners and the validator.
In production, these would be Bittensor Synapses (bt.Synapse subclasses).
For the demo, they're plain dataclasses sent as JSON over HTTP.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import time


@dataclass
class ExperimentResult:
    """A completed experiment result from a miner."""

    # Miner identity
    agent_id: str = ""

    # Core metrics
    val_bpb: float = 0.0
    memory_gb: float = 0.0

    # Training metrics
    training_seconds: float = 0.0
    total_tokens_M: float = 0.0
    num_steps: int = 0
    num_params_M: float = 0.0
    mfu_percent: float = 0.0
    depth: int = 0

    # Experiment metadata
    status: str = ""           # "completed", "failed"
    description: str = ""
    experiment_key: str = ""
    train_py_hash: str = ""    # SHA256 of train.py for dedup
    timestamp: float = 0.0     # Unix epoch when result was produced

    # Validator response
    accepted: bool = False
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentResult":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})
