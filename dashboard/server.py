"""HTTP server for the analytics dashboard."""
import json, threading, time, webbrowser
from datetime import date, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .data import load_all_data, _cache, _cache_lock
from calendar_analysis.availability import (
    fetch_events, build_grid, region_from_postcode, region_from_city, all_regions,
)

_avail_cache: dict = {}
_avail_cache_lock = threading.Lock()
_AVAIL_TTL = 300  # 5 minutes

PORT  = 8765
_HTML = (Path(__file__).parent.parent / 'public' / 'index.html').read_text(encoding='utf-8')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/':
            body = _HTML.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == '/api/data':
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
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as ex:
                body = json.dumps({'error': str(ex)}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        elif parsed.path == '/api/refresh':
            with _cache_lock:
                _cache.clear()
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == '/api/availability/regions':
            body = json.dumps({"regions": all_regions()}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == '/api/availability':
            params = parse_qs(parsed.query)
            region = (params.get('region') or [None])[0]
            days = int((params.get('days') or ['10'])[0])
            location = (params.get('location') or [None])[0]

            # resolve region from postcode/city if provided
            if location and not region:
                region = region_from_postcode(location) or region_from_city(location)

            cache_key = f"avail:{region}:{days}"
            with _avail_cache_lock:
                cached = _avail_cache.get(cache_key)
                if cached and time.time() - cached['ts'] < _AVAIL_TTL:
                    body = cached['body']
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

            try:
                events = fetch_events(days=days + 2)
                grid = build_grid(events, region=region, days=days)
                body = json.dumps(grid, default=str).encode('utf-8')
                with _avail_cache_lock:
                    _avail_cache[cache_key] = {'body': body, 'ts': time.time()}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as ex:
                body = json.dumps({'error': str(ex)}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        elif parsed.path == '/api/availability/refresh':
            with _avail_cache_lock:
                _avail_cache.clear()
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, _fmt, *args):
        print(f'  [{args[1]}] {args[0]}')


def main():
    url = f'http://localhost:{PORT}'
    server = ThreadingHTTPServer(('localhost', PORT), Handler)
    print(f'\n  Dashboard → {url}')
    print('  Ctrl+C to stop\n')
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n  Stopped.')


if __name__ == '__main__':
    main()
