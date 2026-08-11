"""Runtime benchmark with verifiable per-run logs (manuscript Section 5.4).

Every edit-to-output interval is logged with a wall-clock timestamp, including the
discarded warm-up runs, failures, and timeouts, together with the hardware, caching,
and data-loading conditions. The released JSONL logs let the <30 s interactive claim
be verified independently.
"""

import json
import platform
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path


def hardware_snapshot() -> dict:
    info = {
        "machine": platform.machine(),
        "processor": platform.processor(),
        "system": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
    }
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        pass
    return info


@dataclass
class RuntimeBenchmark:
    case_name: str
    log_path: Path
    warmup_runs: int = 5
    timeout_s: float = 60.0
    _runs: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.log_path = Path(self.log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._append({"event": "session_start", "case": self.case_name,
                      "hardware": hardware_snapshot(), "warmup_runs": self.warmup_runs})

    def _append(self, record: dict) -> None:
        record["ts"] = time.time()
        with open(self.log_path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def run(self, edit_fn, run_index: int) -> dict:
        """Time one parameter edit end-to-end; edit_fn() must block until outputs return."""
        is_warmup = run_index < self.warmup_runs
        start = time.perf_counter()
        record = {"event": "run", "case": self.case_name, "run_index": run_index,
                  "warmup": is_warmup}
        try:
            edit_fn()
            elapsed = time.perf_counter() - start
            record.update(status="ok", elapsed_s=elapsed,
                          timeout=elapsed > self.timeout_s)
        except Exception as exc:  # failures are evidence, not noise
            record.update(status="failure", elapsed_s=time.perf_counter() - start,
                          error=repr(exc))
        self._append(record)
        if not is_warmup:
            self._runs.append(record)
        return record

    def summary(self) -> dict:
        ok = [r["elapsed_s"] for r in self._runs if r["status"] == "ok" and not r["timeout"]]
        result = {
            "case": self.case_name,
            "n_measured": len(self._runs),
            "n_ok": len(ok),
            "n_failures": sum(r["status"] == "failure" for r in self._runs),
            "n_timeouts": sum(r.get("timeout", False) for r in self._runs),
        }
        if ok:
            result.update(
                mean_s=statistics.fmean(ok),
                stdev_s=statistics.stdev(ok) if len(ok) > 1 else 0.0,
                p95_s=sorted(ok)[max(0, int(0.95 * len(ok)) - 1)],
            )
        self._append({"event": "summary", **result})
        return result
