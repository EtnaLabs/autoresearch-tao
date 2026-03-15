"""
Lightweight data preparation for autoresearch demo (laptop-friendly).
Downloads tinyshakespeare (~1MB) and builds a character-level tokenizer.

Usage:
    python prepare_lite.py          # full prep (download + tokenizer)

Data and tokenizer are stored in ~/.cache/autoresearch-lite/.
"""

import os
import sys
import json
import math
import time
import argparse

import requests
import torch

# ---------------------------------------------------------------------------
# Constants (fixed, do not modify)
# ---------------------------------------------------------------------------

MAX_SEQ_LEN = 256        # context length (short for laptop demo)
TIME_BUDGET = int(os.environ.get("AUTORESEARCH_TIME_BUDGET", 30))
EVAL_TOKENS = 8 * 256    # number of tokens for val eval (small for speed)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "autoresearch-lite")
DATA_DIR = os.path.join(CACHE_DIR, "data")
TOKENIZER_DIR = os.path.join(CACHE_DIR, "tokenizer")
DATA_URL = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"

SPECIAL_TOKENS = ["<|bos|>", "<|pad|>", "<|reserved_2|>", "<|reserved_3|>"]

# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def get_device():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    elif torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")

DEVICE = get_device()

# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def download_data():
    """Download tinyshakespeare if not already cached."""
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, "tinyshakespeare.txt")
    if os.path.exists(filepath):
        print(f"Data: already downloaded at {filepath}")
        return filepath
    print("Data: downloading tinyshakespeare...")
    resp = requests.get(DATA_URL, timeout=30)
    resp.raise_for_status()
    with open(filepath, "w") as f:
        f.write(resp.text)
    print(f"Data: saved to {filepath} ({len(resp.text):,} chars)")
    return filepath


def load_text():
    """Load the full tinyshakespeare text."""
    filepath = os.path.join(DATA_DIR, "tinyshakespeare.txt")
    with open(filepath) as f:
        return f.read()

# ---------------------------------------------------------------------------
# Tokenizer (character-level)
# ---------------------------------------------------------------------------

def train_tokenizer():
    """Build a character-level tokenizer from the dataset."""
    tokenizer_path = os.path.join(TOKENIZER_DIR, "tokenizer.json")
    token_bytes_path = os.path.join(TOKENIZER_DIR, "token_bytes.pt")

    if os.path.exists(tokenizer_path) and os.path.exists(token_bytes_path):
        print(f"Tokenizer: already built at {TOKENIZER_DIR}")
        return

    os.makedirs(TOKENIZER_DIR, exist_ok=True)
    text = load_text()

    # Build char vocabulary
    chars = sorted(set(text))
    n_special = len(SPECIAL_TOKENS)

    # Special tokens get IDs 0..3, characters get 4..4+len(chars)-1
    char_to_id = {ch: i + n_special for i, ch in enumerate(chars)}
    id_to_char = {i + n_special: ch for i, ch in enumerate(chars)}
    vocab_size = len(chars) + n_special

    mapping = {
        "char_to_id": char_to_id,
        "id_to_char": {str(k): v for k, v in id_to_char.items()},
        "special_tokens": {name: i for i, name in enumerate(SPECIAL_TOKENS)},
        "vocab_size": vocab_size,
    }
    with open(tokenizer_path, "w") as f:
        json.dump(mapping, f)

    # Token bytes: number of UTF-8 bytes per token (0 for specials)
    token_bytes = torch.zeros(vocab_size, dtype=torch.int32)
    for tid, ch in id_to_char.items():
        token_bytes[tid] = len(ch.encode("utf-8"))
    torch.save(token_bytes, token_bytes_path)

    print(f"Tokenizer: built (vocab_size={vocab_size}, {len(chars)} chars + {n_special} special)")

    # Sanity check
    test = "Hello world!"
    ids = [char_to_id[c] for c in test]
    decoded = "".join(id_to_char[i] for i in ids)
    assert decoded == test, f"Roundtrip failed: {test!r} -> {decoded!r}"
    print("Tokenizer: sanity check passed")

# ---------------------------------------------------------------------------
# Runtime utilities (imported by train_lite.py)
# ---------------------------------------------------------------------------

class Tokenizer:
    """Character-level tokenizer with same interface as the full version."""

    def __init__(self, char_to_id, id_to_char, vocab_size, bos_id):
        self.char_to_id = char_to_id
        self.id_to_char = id_to_char
        self._vocab_size = vocab_size
        self.bos_token_id = bos_id

    @classmethod
    def from_directory(cls, tokenizer_dir=TOKENIZER_DIR):
        with open(os.path.join(tokenizer_dir, "tokenizer.json")) as f:
            data = json.load(f)
        char_to_id = data["char_to_id"]
        id_to_char = {int(k): v for k, v in data["id_to_char"].items()}
        bos_id = data["special_tokens"]["<|bos|>"]
        return cls(char_to_id, id_to_char, data["vocab_size"], bos_id)

    def get_vocab_size(self):
        return self._vocab_size

    def get_bos_token_id(self):
        return self.bos_token_id

    def encode(self, text, prepend=None, num_threads=8):
        if isinstance(text, str):
            ids = [self.char_to_id[c] for c in text if c in self.char_to_id]
            if prepend is not None:
                pid = prepend if isinstance(prepend, int) else self.bos_token_id
                ids.insert(0, pid)
            return ids
        elif isinstance(text, list):
            result = []
            for t in text:
                ids = [self.char_to_id[c] for c in t if c in self.char_to_id]
                if prepend is not None:
                    pid = prepend if isinstance(prepend, int) else self.bos_token_id
                    ids.insert(0, pid)
                result.append(ids)
            return result
        raise ValueError(f"Invalid input type: {type(text)}")

    def decode(self, ids):
        return "".join(self.id_to_char.get(i, "") for i in ids)


def get_token_bytes(device="cpu"):
    path = os.path.join(TOKENIZER_DIR, "token_bytes.pt")
    with open(path, "rb") as f:
        return torch.load(f, map_location=device, weights_only=True)


def make_dataloader(tokenizer, B, T, split, buffer_size=1000):
    """
    Simple dataloader: pre-tokenize the full text, yield consecutive chunks.
    Train = first 90%, Val = last 10%.
    """
    text = load_text()
    bos = tokenizer.get_bos_token_id()
    all_ids = tokenizer.encode(text)

    split_point = int(len(all_ids) * 0.9)
    if split == "train":
        ids = all_ids[:split_point]
    else:
        ids = all_ids[split_point:]

    data = torch.tensor(ids, dtype=torch.long)
    row_len = T + 1  # need T+1 tokens per row to get T inputs + T targets
    device = DEVICE
    epoch = 1

    while True:
        # Shuffle start offset each epoch for training
        offset = 0
        while offset + B * row_len <= len(data):
            chunk = data[offset:offset + B * row_len].view(B, row_len).to(device)
            inputs = chunk[:, :-1]
            targets = chunk[:, 1:]
            yield inputs, targets, epoch
            offset += B * row_len
        epoch += 1


# ---------------------------------------------------------------------------
# Evaluation (same interface as full version)
# ---------------------------------------------------------------------------

@torch.no_grad()
def evaluate_bpb(model, tokenizer, batch_size):
    """
    Bits per byte (BPB): same metric as the full version.
    """
    device = DEVICE
    token_bytes = get_token_bytes(device=device)
    val_loader = make_dataloader(tokenizer, batch_size, MAX_SEQ_LEN, "val")
    steps = max(1, EVAL_TOKENS // (batch_size * MAX_SEQ_LEN))
    total_nats = 0.0
    total_bytes = 0
    for i in range(steps):
        x, y, _ = next(val_loader)
        loss_flat = model(x, y, reduction='none').reshape(-1)
        y_flat = y.reshape(-1)
        nbytes = token_bytes[y_flat]
        mask = nbytes > 0
        total_nats += (loss_flat * mask).sum().item()
        total_bytes += nbytes.sum().item()
    if total_bytes == 0:
        return float('inf')
    return total_nats / (math.log(2) * total_bytes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Cache directory: {CACHE_DIR}")
    print(f"Device: {DEVICE}")
    print()

    download_data()
    print()

    train_tokenizer()
    print()
    print("Done! Ready to train with: uv run train_lite.py")
