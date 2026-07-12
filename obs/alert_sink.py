"""Minimal Alertmanager webhook sink: logs every notification so delivery is provable.

Alertmanager POSTs its standard JSON here; we print one clear line per alert (with a UTC
timestamp) to stdout. `docker logs` on this container is the evidence that an alert actually
arrived — not that a config "looks right".
"""

import datetime
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        ts = datetime.datetime.now(datetime.UTC).isoformat()
        try:
            payload = json.loads(raw)
            for a in payload.get("alerts", []):
                labels = a.get("labels", {})
                summary = a.get("annotations", {}).get("summary", "")
                print(
                    f"[{ts}] ALERT status={a.get('status')} "
                    f"name={labels.get('alertname')} severity={labels.get('severity')} "
                    f":: {summary}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 - log anything, even malformed
            print(f"[{ts}] RAW ({exc}): {raw}", flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args) -> None:  # silence default access logging
        pass


if __name__ == "__main__":
    print("alert-sink listening on :8080", flush=True)
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
