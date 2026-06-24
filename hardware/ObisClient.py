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
        frame = struct.pack('>I', len(data)) + data   

        with self._lock:                              
            for attempt in (1, 2):                    
                try:
                    self._ensure_conn()
                    self._sock.sendall(frame)

                    hdr = self._recv_exact(4)
                    n = struct.unpack('>I', hdr)[0]
                    body = self._recv_exact(n)
                    
                    try:
                        return json.loads(body.decode('utf-8'))
                    except ValueError as ve:
                        self.logger.error(f"JSON Parse Error: {ve}")
                        return {'status': 'error', 'code': 'BAD_JSON', 'message': 'Invalid response format'}

                except socket.timeout:
                    self.logger.error(f"ObisClient Timeout: {self.host}:{self.port}")
                    return {'status': 'error', 'code': 'NET_TIMEOUT', 'message': 'Timeout'}
                except ConnectionRefusedError:
                    self.logger.error("ObisClient Connection Refused")
                    return {'status': 'error', 'code': 'NET_REFUSED', 'message': 'Connection Refused'}
                except (ConnectionError, OSError) as e:
                    self.logger.error(f"ObisClient Network Error: {e}")
                    return {'status': 'error', 'code': 'NET_ERROR',
                            'message': f'{type(e).__name__}: {e}'}
                except json.JSONDecodeError as e:
                    self.logger.error(f"ObisClient JSON decode failed: {e}")
                    return {'status': 'error', 'code': 'BAD_RESPONSE',
                            'message': f'Malformed server response: {e}'}
                except Exception as e:
                    self.logger.error(f"ObisClient Unexpected: {e}")
                    return {'status': 'error', 'code': 'CLIENT_ERROR', 'message': str(e)}


    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("peer closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out
