from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

if __package__ is None or __package__ == "":
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from backend.chord_analysis import analyze_midi
from backend.midi_parser import MidiParseError, parse_midi_bytes


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class MidiAnalyzerHandler(BaseHTTPRequestHandler):
    server_version = "MidiChordAnalyzer/0.1"

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json({"ok": True, "service": "midi-chord-analyzer"})
            return
        self._send_json(
            {
                "ok": True,
                "message": "POST a MIDI file as application/octet-stream to /api/analyze.",
            }
        )

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length"}, status=HTTPStatus.BAD_REQUEST)
            return

        if content_length <= 0:
            self._send_json({"error": "No MIDI bytes were uploaded."}, status=HTTPStatus.BAD_REQUEST)
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._send_json({"error": "MIDI file is too large for this MVP."}, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        file_name = unquote(self.headers.get("X-File-Name", "upload.mid"))
        midi_bytes = self.rfile.read(content_length)

        try:
            midi = parse_midi_bytes(midi_bytes)
            result = analyze_midi(midi, file_name=file_name)
        except MidiParseError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_json({"error": f"Unexpected analysis error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._send_json(result)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, body: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-File-Name")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the MIDI chord analyzer API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), MidiAnalyzerHandler)
    print(f"Listening on http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
