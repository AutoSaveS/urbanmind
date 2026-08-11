"""HTTP endpoint consumed by the Grasshopper component.

POST /evaluate with a JSON body of intervention parameters returns the four-domain
fields, uncertainty layers, and summary indicators for the loaded case. Every
request executes the full rollout / KRCG / uncertainty / render chain and is
captured by the runtime benchmark logger.

Run:  python -m urbanmind.gh_bridge.server --port 8787
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class EvaluateHandler(BaseHTTPRequestHandler):
    evaluate_fn = None  # injected by serve()

    def do_POST(self):
        if self.path != "/evaluate":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        params = json.loads(self.rfile.read(length) or b"{}")
        result = type(self).evaluate_fn(params)
        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep benchmark timing clean


def serve(evaluate_fn, port: int = 8787):
    EvaluateHandler.evaluate_fn = staticmethod(evaluate_fn)
    server = HTTPServer(("127.0.0.1", port), EvaluateHandler)
    print(f"UrbanMind gh_bridge listening on 127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    def _demo_evaluate(params: dict) -> dict:
        # Placeholder wiring; real deployments inject the trained model here.
        return {"status": "ok", "params_received": params}

    serve(_demo_evaluate, args.port)
