"""Loopback-only, capability URLs for range-based native audio playback.

Only files explicitly registered by the authorized session API can be served.
No filesystem paths or directory listing are exposed to HTTP clients.
"""
import atexit
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_lock = threading.RLock()
_files = {}
_server = None


def media_type(path):
    with path.open('rb') as f:
        head = f.read(32)
    if head[:4] == b'RIFF': return 'audio/wav'
    if head[4:8] == b'ftyp': return 'video/mp4'
    if head[:4] == b'fLaC': return 'audio/flac'
    if head[:4] == b'OggS': return 'audio/ogg'
    if head[:4] == b'\x1aE\xdf\xa3': return 'video/webm'
    return 'audio/mpeg'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_HEAD(self): self._serve(False)
    def do_GET(self): self._serve(True)

    def _serve(self, body):
        with _lock:
            entry = _files.get(self.path)
        if not entry:
            self.send_error(404); return
        path, fingerprint = entry
        try:
            if path.is_symlink() or not path.is_file():
                self.send_error(404); return
            st = path.stat()
            if (st.st_dev, st.st_ino) != fingerprint:
                self.send_error(404); return
            size = st.st_size
            start, end = 0, size - 1
            request_range = self.headers.get('Range')
            if request_range:
                try:
                    unit, value = request_range.split('=', 1)
                    first, last = value.split('-', 1)
                    if unit != 'bytes' or ',' in value: raise ValueError()
                    if first:
                        start = int(first); end = min(int(last), size-1) if last else size-1
                    else:
                        suffix = int(last)
                        if suffix <= 0: raise ValueError()
                        start = max(0, size-suffix)
                    if start < 0 or start > end or start >= size: raise ValueError()
                except ValueError:
                    self.send_response(416); self.send_header('Content-Range', f'bytes */{size}')
                    self.send_header('Content-Length', '0'); self.end_headers(); return
            self.send_response(206 if request_range else 200)
            self.send_header('Content-Type', media_type(path))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(max(0, end-start+1)))
            if request_range: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if body:
                with path.open('rb') as f:
                    f.seek(start); remaining = end-start+1
                    while remaining > 0:
                        data = f.read(min(65536, remaining))
                        if not data: break
                        self.wfile.write(data); remaining -= len(data)
        except (OSError, BrokenPipeError, ConnectionResetError):
            return


def register(path: Path):
    global _server
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('录音已被清理或文件不可用')
    path = path.resolve()
    with _lock:
        if _server is None:
            _server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            threading.Thread(target=_server.serve_forever, daemon=True).start()
            atexit.register(_server.shutdown)
        st = path.stat()
        for token, entry in _files.items():
            if entry == (path, (st.st_dev, st.st_ino)):
                return f'http://127.0.0.1:{_server.server_port}{token}'
        token = '/' + secrets.token_urlsafe(32)
        if len(_files) >= 128: _files.pop(next(iter(_files)))
        _files[token] = (path, (st.st_dev, st.st_ino))
        return f'http://127.0.0.1:{_server.server_port}{token}'
