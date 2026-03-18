"""
Saturn Cloud GPU runner — submits train_lite.py as a remote job.

Requires:
  - SATURN_TOKEN env var (create at Saturn Cloud > User Profile > Access Keys)
  - A git repo URL where this code is pushed (Saturn Cloud pulls from git)

Usage:
    from saturn_runner import SaturnRunner
    runner = SaturnRunner(token="...", instance_size="T4-XLarge")
    result_text = runner.run_training(time_budget=30)
"""

import os
import time
import requests

# Saturn Cloud API base URL
SATURN_API_BASE = os.environ.get(
    "SATURN_API_BASE", "https://app.community.saturnenterprise.io"
)

# Available GPU instance sizes on Saturn Cloud
# Map friendly names to Saturn Cloud instance size strings
GPU_INSTANCES = {
    "t4":    {"size": "T4-XLarge",   "gpu": "T4",   "price_hr": 0.15},
    "a10g":  {"size": "A10G-XLarge", "gpu": "A10G", "price_hr": 1.50},
    "v100":  {"size": "V100-XLarge", "gpu": "V100", "price_hr": 1.10},
    "h100":  {"size": "H100-XLarge", "gpu": "H100", "price_hr": 2.95},
    "h200":  {"size": "H200-XLarge", "gpu": "H200", "price_hr": 2.95},
}

DEFAULT_GPU = "t4"

# Docker image with PyTorch + CUDA pre-installed
DEFAULT_IMAGE = "saturncloud/saturn-pytorch:2024.01.01"


class SaturnRunner:
    """Submit and monitor training jobs on Saturn Cloud GPUs."""

    def __init__(self, token: str = "", gpu: str = DEFAULT_GPU, git_repo_url: str = "",
                 git_branch: str = "master", working_dir: str = ""):
        self.token = token or os.environ.get("SATURN_TOKEN", "")
        if not self.token:
            raise ValueError(
                "Saturn Cloud token required. Set SATURN_TOKEN env var or pass token=."
                "\nCreate one at: Saturn Cloud > User Profile > Access Keys > New Token"
            )
        self.gpu = gpu.lower()
        if self.gpu not in GPU_INSTANCES:
            raise ValueError(
                f"Unknown GPU '{gpu}'. Available: {', '.join(GPU_INSTANCES.keys())}"
            )
        self.instance_info = GPU_INSTANCES[self.gpu]
        self.git_repo_url = git_repo_url or os.environ.get("SATURN_GIT_REPO", "")
        self.git_branch = git_branch
        self.working_dir = working_dir
        self.base_url = SATURN_API_BASE
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
        })

    def _api(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        resp = self._session.request(method, url, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def list_resources(self) -> list:
        """List existing Saturn Cloud resources (jobs, workspaces, etc.)."""
        resp = self._api("GET", "/api/active/resources")
        return resp.json()

    def create_job(self, time_budget: int, extra_env: dict = None) -> dict:
        """Create a Saturn Cloud job resource for training."""
        env_vars = {
            "AUTORESEARCH_TIME_BUDGET": str(time_budget),
        }
        if extra_env:
            env_vars.update(extra_env)

        job_spec = {
            "name": f"autoresearch-train-{int(time.time())}",
            "instance_size": self.instance_info["size"],
            "image": DEFAULT_IMAGE,
            "command": "pip install torch requests && python train_lite.py",
            "environment_variables": env_vars,
        }

        # Attach git repo if provided
        if self.git_repo_url:
            job_spec["git_repositories"] = [{
                "url": self.git_repo_url,
                "reference": self.git_branch,
                "path": "/home/jovyan/project",
            }]
            job_spec["working_directory"] = "/home/jovyan/project"
            if self.working_dir:
                job_spec["working_directory"] = self.working_dir

        resp = self._api("POST", "/api/jobs", json=job_spec)
        return resp.json()

    def start_job(self, job_id: str) -> dict:
        """Start a created job."""
        resp = self._api("POST", f"/api/jobs/{job_id}/start")
        return resp.json()

    def get_job_status(self, job_id: str) -> dict:
        """Get current status of a job."""
        resp = self._api("GET", f"/api/jobs/{job_id}")
        return resp.json()

    def get_job_logs(self, job_id: str) -> str:
        """Get stdout/stderr logs from a job."""
        resp = self._api("GET", f"/api/jobs/{job_id}/logs")
        return resp.text

    def delete_job(self, job_id: str):
        """Delete a job resource (cleanup)."""
        self._api("DELETE", f"/api/jobs/{job_id}")

    def run_training(self, time_budget: int, poll_interval: int = 10,
                     max_wait: int = 0) -> str:
        """
        End-to-end: create job, start it, poll until done, return logs.

        Args:
            time_budget: Training time budget in seconds.
            poll_interval: Seconds between status polls.
            max_wait: Max seconds to wait (0 = time_budget + 5 minutes).

        Returns:
            Job stdout as a string (same format as local train_lite.py output).
        """
        if max_wait <= 0:
            max_wait = time_budget + 300  # 5 min buffer for startup + eval

        print(f"[saturn] Creating job on {self.instance_info['gpu']} "
              f"(${self.instance_info['price_hr']:.2f}/hr)...")

        job = self.create_job(time_budget)
        job_id = job["id"]
        print(f"[saturn] Job created: {job_id}")

        print(f"[saturn] Starting job...")
        self.start_job(job_id)

        # Poll for completion
        t0 = time.time()
        last_status = ""
        while time.time() - t0 < max_wait:
            status_data = self.get_job_status(job_id)
            status = status_data.get("status", "unknown")

            if status != last_status:
                print(f"[saturn] Job status: {status}")
                last_status = status

            if status in ("completed", "done", "stopped"):
                break
            elif status in ("error", "failed"):
                logs = self.get_job_logs(job_id)
                self.delete_job(job_id)
                raise RuntimeError(f"Saturn Cloud job failed:\n{logs[-1000:]}")

            time.sleep(poll_interval)
        else:
            self.delete_job(job_id)
            raise TimeoutError(
                f"Saturn Cloud job did not complete within {max_wait}s"
            )

        # Fetch logs (contains train_lite.py output)
        logs = self.get_job_logs(job_id)
        print(f"[saturn] Job completed. Cleaning up...")
        self.delete_job(job_id)

        return logs


def print_available_gpus():
    """Print available GPU options."""
    print("Available Saturn Cloud GPUs:")
    print(f"  {'Name':<8} {'GPU':<6} {'Price':>8}")
    print(f"  {'-'*8} {'-'*6} {'-'*8}")
    for name, info in GPU_INSTANCES.items():
        print(f"  {name:<8} {info['gpu']:<6} ${info['price_hr']:>6.2f}/hr")


if __name__ == "__main__":
    print_available_gpus()
