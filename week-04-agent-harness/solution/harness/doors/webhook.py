"""Door 2, triggered by an event: an email arrives as an HTTP POST, a harness handles it."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..observe import final, run
from .remote import triage_task


def make_server(make_harness, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    """port 0: any free port (see server.server_address). Call serve_forever() in a thread."""

    class EmailWebhook(BaseHTTPRequestHandler):
        def do_POST(self):
            email = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            h = make_harness("webhook")
            events = run(h, triage_task(email), quiet=True)
            body = json.dumps({"answer": final(events), "held": [x.tool for x in h.held]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), EmailWebhook)
