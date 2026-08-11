"""Demo backend: serves the trained synthetic reference model over the real
gh_bridge/runtime code paths. Run: python demo/serve_demo.py  (port 8787)

Endpoints:
  GET  /            -> viewer page
  POST /evaluate    -> real model inference; logged to runs/demo_session.jsonl
  GET  /logs        -> tail of the JSONL log (what the video shows scrolling)
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, ".")

import torch

from urbanmind.model.world_model import GraphWorldModel
from urbanmind.model.uncertainty import decompose_uncertainty
from urbanmind.runtime.benchmark import RuntimeBenchmark

CKPT = torch.load("demo/synthetic_model.pt", weights_only=False)
MODEL = GraphWorldModel(obs_dim=8)
MODEL.load_state_dict(CKPT["state_dict"])
MODEL.eval()
OBS, EDGES, SIZE = CKPT["obs"], CKPT["edge_index"], CKPT["size"]

LOG = Path("runs/demo_session.jsonl")
BENCH = RuntimeBenchmark("synthetic_reference_demo", log_path=LOG, warmup_runs=0)
RUN_INDEX = [0]


def evaluate(params: dict) -> dict:
    canopy = float(params.get("canopy_delta", 0.0))
    albedo = float(params.get("albedo_delta", 0.0))
    intervention = torch.tensor([canopy, albedo, 0.0, 0.0]).expand(OBS.shape[0], -1)

    start = time.perf_counter()
    result = {}

    def run():
        with torch.no_grad():
            # Small deep ensemble via dropout-free forward passes with jittered obs.
            member_means, member_sigmas = [], []
            for k in range(3):
                noisy = OBS + 0.01 * k * torch.randn_like(OBS)
                m, s = MODEL.rollout(noisy, EDGES, intervention, horizon=1)
                member_means.append(m[0])
                member_sigmas.append(s[0])
            unc = decompose_uncertainty(torch.stack(member_means), torch.stack(member_sigmas))
        result["mean"] = unc["mean"]
        result["total_sigma"] = unc["total_sigma"]

    BENCH.run(run, RUN_INDEX[0])
    RUN_INDEX[0] += 1
    elapsed_ms = (time.perf_counter() - start) * 1000

    mean = result["mean"].reshape(SIZE, SIZE, 4)
    sigma = result["total_sigma"].reshape(SIZE, SIZE, 4)
    return {
        "elapsed_ms": round(elapsed_ms, 1),
        "size": SIZE,
        "domains": ["thermal", "air_quality", "building_energy", "vegetation"],
        "fields": [mean[:, :, d].tolist() for d in range(4)],
        "uncertainty": [sigma[:, :, d].tolist() for d in range(4)],
        "params": {"canopy_delta": canopy, "albedo_delta": albedo},
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str = "application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(Path("demo/viewer.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/logs":
            lines = LOG.read_text().strip().split("\n")[-8:] if LOG.exists() else []
            self._send(json.dumps(lines).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/evaluate":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        params = json.loads(self.rfile.read(length) or b"{}")
        print(f"[evaluate] canopy={params.get('canopy_delta')} albedo={params.get('albedo_delta')}")
        self._send(json.dumps(evaluate(params)).encode())

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print("UrbanMind synthetic reference demo on http://127.0.0.1:8787")
    HTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
