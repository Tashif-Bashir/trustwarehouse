"""Vercel serverless function — wraps dashboard/data.py and returns JSON."""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import date, timedelta
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dashboard.data import load_all_data


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        d0 = (params.get('d0') or [None])[0]
        d1 = (params.get('d1') or [None])[0]
        if not d0 or not d1:
            d1 = (date.today() - timedelta(1)).strftime('%Y-%m-%d')
            d0 = (date.today() - timedelta(7)).strftime('%Y-%m-%d')
        try:
            data = load_all_data(d0, d1)
            body = json.dumps(data, default=str).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
        except Exception as ex:
            body = json.dumps({'error': str(ex)}).encode('utf-8')
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        pass
