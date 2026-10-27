from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .application import DemoApplication, DemoBusyError
from .config import Settings
from .domain import SCENARIOS

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
STATIC_FILES = {
    "/": WEB_ROOT / "dist" / "index.html",
    "/index.html": WEB_ROOT / "dist" / "index.html",
    "/assets": WEB_ROOT / "dist" / "assets",
}


class DemoRequestHandler(BaseHTTPRequestHandler):
    server_version = "BankingHooksDemo/1.0"

    @property
    def application(self) -> DemoApplication:
        return self.server.application  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, self.application.health())
            return
        if path == "/api/scenarios":
            self._json(200, [scenario.public() for scenario in SCENARIOS.values()])
            return
        if path == "/api/state":
            self._json(200, self.application.snapshot())
            return
        self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        try:
            if path == "/api/run":
                scenario_id = body.get("scenario_id")
                if not isinstance(scenario_id, str):
                    raise ValueError("scenario_id is required.")
                self._json(202, self.application.start_scenario(
                    scenario_id,
                    hooks_enabled=body.get("hooks_enabled", True),
                ))
                return
            if path == "/api/approval":
                decision = body.get("decision")
                if not isinstance(decision, str):
                    raise ValueError("decision is required.")
                self._json(200, self.application.resolve_approval(decision))
                return
            if path == "/api/reset":
                self._json(200, self.application.reset(hooks_enabled=body.get("hooks_enabled")))
                return
            self._json(404, {"error": "Endpoint not found."})
        except DemoBusyError as exc:
            self._json(409, {"error": str(exc), "state": self.application.snapshot()})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length.") from exc
        if length < 0 or length > 16_384:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path: str) -> None:
        if path.startswith("/assets/"):
            target = (WEB_ROOT / "dist" / path.lstrip("/")).resolve()
            base = (WEB_ROOT / "dist" / "assets").resolve()
            if base not in target.parents:
                self._json(404, {"error": "File not found."})
                return
        else:
            target = STATIC_FILES.get(path)
            if target is None:
                self._json(404, {"error": "File not found."})
                return
        if not target.is_file():
            self._json(
                503,
                {"error": "Frontend build not found. Run `pnpm --dir web build` first."},
            )
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type == "text/html":
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[banking-demo] {self.address_string()} {format % args}")


class DemoHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        application: DemoApplication,
    ) -> None:
        self.application = application
        super().__init__(address, DemoRequestHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the banking Agent Hooks demo API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    application = DemoApplication(Settings.load())
    health = application.health()
    if not health["runtime_ready"]:
        parser.error(
            "Missing live runtime dependencies: "
            + ", ".join(health["missing_modules"])
            + ". Install this project's Python dependencies before starting the server."
        )
    server = DemoHTTPServer((args.host, args.port), application)
    print(
        f"Banking Agent Hooks API listening on http://{args.host}:{args.port} "
        "(Foundry model and Agent Hooks enforcement enabled)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping banking demo API.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
