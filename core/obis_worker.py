from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer
import time

try:
    # 하드웨어 폴더에 배치한 클라이언트를 임포트
    from hardware.ObisClient import ObisClient
    _OBIS_AVAILABLE = True
except ImportError:
    _OBIS_AVAILABLE = False

class ObisWorker(QObject):
    """
    OBIS 멀티 레이저 디바이스 서버와의 비동기 통신을 전담하는 Worker.
    2초 주기의 상태 폴링(Polling)과 단발성 제어 명령(Move/State)을 큐잉 처리한다.
    """
    sig_message = pyqtSignal(str, str) # level, message
    sig_status_updated = pyqtSignal(dict) # 532nm, 633nm 상태 데이터를 메인으로 전달
    sig_connection_changed = pyqtSignal(bool) # 물리적 연결 상태 변경 알림

    def __init__(self):
        super().__init__()
        self.client = None
        self.poll_timer = None
        self._is_connected = False

    @pyqtSlot()
    def initialize(self):
        """QThread 시작 직후 호출되어 스레드 종속적인 QTimer를 안전하게 생성한다."""
        if not _OBIS_AVAILABLE:
            self.sig_message.emit("error", "hardware.ObisClient 모듈을 찾을 수 없음.")
            return
            
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_status)

    @pyqtSlot(str, int)
    def connect_server(self, host, port=9000):
        if not _OBIS_AVAILABLE: return

        self.client = ObisClient(host=host, port=port, timeout=1.0)
        if self.client.ping():
            self._is_connected = True
            self.sig_message.emit("info", f"OBIS Server Connected ({host}:{port})")
            self.poll_timer.start(2000)
            self.sig_connection_changed.emit(True) # 연결 확정
        else:
            self.client = None
            self._is_connected = False
            self.sig_message.emit("error", f"OBIS Server Ping Failed ({host}:{port})")
            self.sig_connection_changed.emit(False) # 연결 실패

    @pyqtSlot()
    def disconnect_server(self):
        self._is_connected = False
        if self.poll_timer: self.poll_timer.stop()
        self.client = None
        self.sig_message.emit("info", "OBIS Server Disconnected.")
        self.sig_connection_changed.emit(False) # 해제 확정

    @pyqtSlot(str, float)
    def set_power(self, target, power_mw):
        if not self._is_connected or not self.client:
            self.sig_message.emit("error", f"[{target}] Not connected to server.")
            return
            
        res = self.client.set_power(target, power_mw)
        
        if res.get('status') == 'ok':
            self.sig_message.emit("info", f"[{target}] Power set to {power_mw} mW")
            self._poll_status() # 파워 변경 직후 UI 즉각 반영을 위해 강제 1회 폴링
        else:
            self.sig_message.emit("error", f"[{target}] Power set error: {res.get('message')}")

    @pyqtSlot(str, bool)
    def set_state(self, target, state):
        if not self._is_connected or not self.client:
            return
            
        res = self.client.set_state(target, state)
        state_str = "ON" if state else "OFF"
        
        if res.get('status') == 'ok':
            self.sig_message.emit("info", f"[{target}] Emission {state_str}")
            self._poll_status() # 상태 변경 직후 즉각 반영
        else:
            self.sig_message.emit("error", f"[{target}] Emission error: {res.get('message')}")

    def _poll_status(self):
        """타이머에 의해 2초마다 백그라운드에서 실행되며 전체 레이저 상태를 긁어온다."""
        if not self._is_connected or not self.client:
            return
            
        # ObisClient에 get_status_all()이 구현되어 있다고 가정함. 
        # 만약 클라이언트에 없다면 'laser_532', 'laser_633'을 각각 get_status() 호출하게 수정해.
        try:
            res = self.client.get_status_all()
        except AttributeError:
            # get_status_all이 없을 경우를 대비한 Fallback 로직
            res_532 = self.client.get_status('laser_532')
            res_633 = self.client.get_status('laser_633')
            
            if res_532.get('status') == 'ok' and res_633.get('status') == 'ok':
                res = {
                    'status': 'ok',
                    'data': {
                        'laser_532': res_532.get('data', {}).get('laser_532', {}),
                        'laser_633': res_633.get('data', {}).get('laser_633', {})
                    }
                }
            else:
                res = {'status': 'error', 'message': 'Individual polling failed'}

        if res.get('status') == 'ok':
            # 메인 스레드의 UI 업데이트를 위해 시그널 방출
            self.sig_status_updated.emit(res.get('data', {}))
        else:
            # 폴링 중 에러가 나도 타이머(Timer)는 죽이지 않는다. 일시적인 네트워크 지연일 수 있음.
            self.sig_message.emit("error", f"OBIS Polling Error: {res.get('message')}")