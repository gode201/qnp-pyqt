import threading, struct

class ObisClient:
    def __init__(self, host, port=9000, timeout=1.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._sock = None
        self._lock = threading.Lock()      # (a) 직렬화
        self._buf = b''                    # (d) 수신 버퍼
        self.logger = logging.getLogger(__name__)

    def _ensure_conn(self):
        if self._sock is not None:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.connect((self.host, self.port))
        self._sock = s
        self._buf = b''

    def _close(self):
        if self._sock:
            try: self._sock.close()
            except: pass
        self._sock = None
        self._buf = b''

    def _send(self, payload: dict) -> dict:
        data = json.dumps(payload).encode('utf-8')
        frame = struct.pack('>I', len(data)) + data   # (b) length-prefix framing

        with self._lock:                              # (a) 한 번에 한 요청만
            for attempt in (1, 2):                    # (c) 1회 자동 재연결
                try:
                    self._ensure_conn()
                    self._sock.sendall(frame)

                    # 응답: 4바이트 길이 → 본문
                    hdr = self._recv_exact(4)
                    n = struct.unpack('>I', hdr)[0]
                    body = self._recv_exact(n)
                    try:
                        return json.loads(body.decode('utf-8'))
                    except ValueError as ve:
                        self.logger.error(f"JSON Parse Error: {ve}")
                        return {'status': 'error', 'message': 'Invalid response format from server'}

                except (socket.timeout, ConnectionError, OSError) as e:
                    self._close()
                    if attempt == 2:
                        return {'status': 'error', 'message': str(e)}

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("peer closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out
