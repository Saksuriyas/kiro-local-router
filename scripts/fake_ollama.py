"""Minimal fake Ollama server so the wiring can be tested without a model.

    python scripts/fake_ollama.py [port]
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

MODEL = "fake-model"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": MODEL}]})
        else:
            self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/api/chat":
            return self._send(404, {})
        system = body["messages"][0]["content"].lower()
        user = body["messages"][1]["content"]
        if "reviewer" in system:
            out = "VERDICT: NEEDS_WORK\n\n## Clarity\n- (mock) add a quick-start section"
        elif "translator" in system:
            out = "<think>hidden</think>[translated] " + user.strip().splitlines()[0]
        elif "diff" in system:
            out = "feat(sample): add health endpoint\n\n- (mock) generated commit message"
        else:
            out = "```markdown\n# Mock document\n\n(mock) generated from %d chars of input\n```" % len(user)
        self._send(200, {"message": {"role": "assistant", "content": out}})


def start(port: int = 0) -> tuple[HTTPServer, int]:
    srv = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 11435
    srv, port = start(p)
    print(f"fake ollama on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    threading.Event().wait()
