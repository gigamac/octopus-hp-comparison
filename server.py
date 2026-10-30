#!/usr/bin/env python3
"""
Octopus Tariff Comparator Local Server
Provides a zero-dependency local HTTP server on port 8050 that:
1. Serves the interactive visual dashboard (tariff_comparison_report.html)
2. Exposes /api/status to report the last recorded smart meter date
3. Exposes /api/update to allow 1-click in-browser data updates from Octopus Kraken API
"""

import sys
import os
import json
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from typing import Optional

# Ensure directory is on python path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

HTML_FILE = os.path.join(SCRIPT_DIR, "tariff_comparison_report.html")
DEFAULT_PORT = 8050


class DashboardHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "" or path == "/index.html":
            self._serve_html()
        elif path == "/api/status":
            self._handle_status()
        elif path == "/api/update":
            self._handle_update()
        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "/api/update":
            self._handle_update()
        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Not Found")

    def _serve_html(self):
        if not os.path.exists(HTML_FILE):
            # Generate it if missing
            try:
                from compare import run_comparison_pipeline
                run_comparison_pipeline(generate_html=True, quiet=True)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error generating dashboard: {e}".encode("utf-8"))
                return

        try:
            with open(HTML_FILE, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error reading report: {e}".encode("utf-8"))

    def _handle_status(self):
        last_date = None
        # Try to inspect data from HTML or cache
        try:
            if os.path.exists(HTML_FILE):
                with open(HTML_FILE, "r", encoding="utf-8") as f:
                    text = f.read(200000)
                import re
                m = re.search(r'"date":\s*"(\d{4}-\d{2}-\d{2})"', text)
                matches = re.findall(r'"date":\s*"(\d{4}-\d{2}-\d{2})"', text)
                if matches:
                    last_date = matches[-1]
        except Exception:
            pass

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        days_behind = 0
        if last_date:
            try:
                d_last = datetime.strptime(last_date, "%Y-%m-%d")
                d_today = datetime.strptime(today, "%Y-%m-%d")
                days_behind = max(0, (d_today - d_last).days)
            except Exception:
                pass

        resp = {
            "status": "ok",
            "last_recorded_date": last_date or today,
            "today": today,
            "days_behind": days_behind,
            "needs_update": days_behind > 2,
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode("utf-8"))

    def _handle_update(self):
        print("\n⚡ [API Update] Received request to fetch latest data from Octopus...")
        try:
            from compare import run_comparison_pipeline
            # Run pipeline to fetch incremental data from last date to now
            result = run_comparison_pipeline(
                generate_html=True,
                refresh=False,
                quiet=False
            )
            resp = {
                "status": "ok",
                "message": "Data successfully updated from Octopus Kraken API",
                "last_recorded_date": result.get("last_date"),
                "total_days": result.get("total_days"),
                "daily_records": result.get("daily_records"),
            }
            body = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            print(f"✅ [API Update] Completed! New latest date is {result.get('last_date')}")
        except Exception as e:
            print(f"❌ [API Update] Failed: {e}", file=sys.stderr)
            resp = {
                "status": "error",
                "message": str(e)
            }
            body = json.dumps(resp).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        # Concise logging
        if "/api/status" in args[0]:
            return
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]}\n")


def start_server(port: int = DEFAULT_PORT, auto_open: bool = True):
    server_address = ("", port)
    try:
        httpd = HTTPServer(server_address, DashboardHandler)
    except OSError:
        # Port already in use, try port+1
        port += 1
        server_address = ("", port)
        httpd = HTTPServer(server_address, DashboardHandler)

    url = f"http://localhost:{port}"
    print("=" * 70)
    print(" 🚀 OCTOPUS ENERGY TARIFF DASHBOARD SERVER RUNNING")
    print("=" * 70)
    print(f" 🌐 Web Dashboard:  {url}")
    print(" ⚡ 1-Click Update: Enabled directly from your browser!")
    print(" 🛑 To stop server:  Press Ctrl + C")
    print("=" * 70)

    if auto_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Server stopped.")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else DEFAULT_PORT
    start_server(port=port)
