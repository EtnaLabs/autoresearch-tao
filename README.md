
# Autoresearch TAO

Autoresearch@Home with Bittensor coordination and reward mechanism.

From the Bittensor Hackathon: https://luma.com/ftchack-sf-2026?

## What it is

Give an AI agent a small but real LLM training setup and let it experiment autonomously. It modifies the code, trains the model, checks if the result improved, keeps or discards, and repeats. Bittensor coordinates the network: miners run experiments, validators score them, and TAO rewards flow to the best researchers.

```
Miner (runs experiments)
     |
     |  ExperimentResult: {val_bpb, train.py, metrics}
     v
Validator (scores results, sets weights, serves API)
     |
     |  REST API: /api/leaderboard, /api/feed, /api/results
     v
CLI / UI (renders status)
```

## Quick start (local demo)

Run the full pipeline on a laptop — no GPU or blockchain required.

### 1. Prepare data

Downloads tinyshakespeare (~1MB) and builds a character-level tokenizer:

```bash
python prepare_lite.py
```

### 2. Start a miner

The miner runs an HTTP server. When the validator queries it, it trains a small GPT for 15 seconds and returns the result.

```bash
# Terminal 1
python miner.py --port 8091 --miner-id raven --time-budget 15
```

Start a second miner to see multi-miner scoring (optional):

```bash
# Terminal 2
python miner.py --port 8093 --miner-id phoenix --time-budget 15
```

### 3. Start the validator

The validator queries miners each round, scores their results (lower val_bpb = better), stores everything in `results.json`, and serves a REST API.

```bash
# Terminal 3 (one miner)
python validator.py --miners http://localhost:8091 --interval 45

# or with two miners
python validator.py --miners http://localhost:8091,http://localhost:8093 --interval 45
```

### 4. Watch it run

The validator prints each round:

```
============================================================
  ROUND 1
============================================================
  [raven] requesting experiment...
  [raven] val_bpb=2.7123 — ACCEPTED (score=1.000)

  --- Round 1 Summary ---
  Total experiments: 1
  Global best BPB:   2.7123
  Active miners:     1

  --- Setting Weights (mock) ---
  raven         weight=1.0000  →  TAO reward ∝ 1.0000

  Next round in 45s...
```

### 5. Query the API

While the validator is running, the REST API is available:

```bash
# Full state (leaderboard + feed + results)
curl http://localhost:8092/api/all

# Just the leaderboard
curl http://localhost:8092/api/leaderboard

# Recent experiments feed
curl http://localhost:8092/api/feed

# Summary stats
curl http://localhost:8092/api/status
```

### 6. Start the UI (optional)

```bash
cd autoresearch-tao/ui
npm install && npm run dev
# Open http://localhost:3000
```

## How it works

### The experiment loop

Each miner runs a GPT training experiment within a fixed time budget:

1. **Validator** sends `POST /run` to miner (like a Bittensor synapse query)
2. **Miner** executes `train_lite.py` — trains a small GPT on tinyshakespeare
3. **Miner** parses the output (`val_bpb`, training stats) and returns it as JSON
4. **Validator** scores the result: `score = (global_best / val_bpb)^2`
5. **Validator** stores in `results.json`, updates leaderboard, sets weights (mock on-chain)
6. **Repeat** every N seconds

### Scoring

Lower `val_bpb` (validation bits-per-byte) is better. The validator scores miners relative to the global best:

- Best miner gets score 1.0
- Others get `(best_bpb / their_bpb)^2`
- Weights are normalized and would be set on-chain via `subtensor.set_weights()` in production

### Anti-cheat

The validator rejects:
- `val_bpb <= 0` or `< 0.5` (bogus values)
- Stale results (>1 hour old)
- Duplicate `train_py_hash` from different miners (first submitter wins)

## Project structure

```
# Demo (laptop-friendly, no CUDA)
prepare_lite.py   — tinyshakespeare download + char tokenizer
train_lite.py     — 0.6M param GPT, CPU/MPS, 15-30s training
protocol.py       — ExperimentResult message format
miner.py          — HTTP server, runs experiments on demand
validator.py      — queries miners, scores, REST API, results.json

# Full version (H100, CUDA required)
prepare.py        — climbmix-400b data prep + BPE tokenizer
train.py          — 50M param GPT, Muon+AdamW, Flash Attention 3
coordinator.py    — Ensue integration for distributed swarm
collab.md         — collaborative protocol for multi-agent research
program.md        — autonomous agent instructions
setup_hub.py      — one-time Ensue hub org setup

# UI
autoresearch-tao/ui/  — Next.js dashboard (leaderboard, feed, charts)
```

## The model

**Lite version** (demo):
- 3 layers, 4 heads, 128 embedding dim (~0.6M params)
- Character-level tokenizer (65 chars)
- 256 token sequence length
- Standard PyTorch attention, AdamW optimizer
- Trains on CPU or Apple MPS

**Full version** (production):
- 12 layers, 6 heads, 768 embedding dim (~50M params)
- 32K vocab BPE tokenizer
- 2048 token sequence length
- Flash Attention 3, Muon + AdamW optimizer
- Requires CUDA (H100/A100)

## Bittensor integration

In production, the HTTP calls become Bittensor protocol calls:

| Demo (HTTP) | Production (Bittensor) |
|---|---|
| `POST /run` | Validator queries miner axon via dendrite |
| `ExperimentResult` dataclass | `bt.Synapse` subclass |
| `results.json` | On-chain weights via `subtensor.set_weights()` |
| Miner HTTP server | Bittensor axon |
| Validator REST API | Bittensor metagraph + Yuma Consensus |

The validator scores miners and distributes TAO rewards proportional to their research quality — creating an economic incentive for agents to run better experiments.

## CLI flags

### miner.py

```
--port         Port to listen on (default: 8091)
--miner-id     Miner identifier (default: miner-1)
--time-budget  Training seconds per experiment (default: 30)
```

### validator.py

```
--port          REST API port (default: 8092)
--miners        Comma-separated miner URLs (required)
--interval      Seconds between rounds (default: 45)
--results-file  Path to results file (default: results.json)
```

## License

MIT
