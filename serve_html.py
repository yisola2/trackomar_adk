#!/usr/bin/env python3
"""Simple HTTP server to serve micro.html and proxy API calls"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request
import urllib.error

class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve HTML file"""
        if self.path in ("/", "/micro.html"):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            try:
                with open("micro.html", "rb") as f:
                    self.wfile.write(f.read())
            except FileNotFoundError:
                self.wfile.write(b"<h1>micro.html not found</h1>")
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        """Handle CORS preflight - don't forward to ADK"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        """Proxy POST requests to ADK api_server"""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        adk_url = f"http://localhost:8000{self.path}"

        try:
            req = urllib.request.Request(
                adk_url,
                data=body,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=180) as response:
                response_data = response.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(response_data)

        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(e.read())
            except:
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        print(f"[{self.client_address[0]}] {format % args}")

if __name__ == "__main__":
    server = HTTPServer(("localhost", 3000), ProxyHandler)
    print("✅ Proxy running → http://localhost:3000")
    print("⚠️  Lance ADK avec : adk api_server track_omar --allow_origins http://localhost:3000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n❌ Server stopped")
        server.server_close()
