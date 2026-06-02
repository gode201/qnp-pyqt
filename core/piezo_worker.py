import time
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer

# 기존 하드웨어 통신 코드를 재활용한다
try:
    from hardware.PiezoController import PiezoController
    _PIEZO_AVAILABLE = True
except ImportError:
    _PIEZO_AVAILABLE = False

class PiezoWorker(QObject):
    """
    Piezo 스테이지의 Z축 시리얼 통신(RS232)을 전담하는 Worker.
    실시간 위치 폴링(QTimer)과 단발성 이동(Move) 명령 간의 버스 충돌을 방어한다.
    """
    sig_position_updated = pyqtSignal(float)
    sig_message = pyqtSignal(str, str) # level, message

    def __init__(self): 
        super().__init__()
        self.controller = None
        self.poll_timer = None
        self._is_connected = False

    @pyqtSlot()
    def initialize(self):
        """QThread 시작 직후 호출. 객체와 타이머만 미리 만들어두고 연결은 대기한다."""

        if not _PIEZO_AVAILABLE:
            self.sig_message.emit("error", "hardware.PiezoController를 찾을 수 없음.")
            return

        self.controller = PiezoController()
        
        # 폴링 타이머만 먼저 생성 (아직 start 안 함)
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_position)

    @pyqtSlot(str)
    def connect_device(self, port):
        """UI에서 Connect 버튼을 눌렀을 때 호출됨."""
        if not self.controller or self._is_connected:
            return
            
        try:
            if self.controller.connect(port=port):
                self._is_connected = True
                self.poll_timer.start(100) # 연결 성공 시에만 폴링 가동
                self.sig_message.emit("info", f"Piezo connected on COM{port}")
            else:
                self.sig_message.emit("error", f"Piezo connection failed on COM{port}")
        except Exception as e:
            self.sig_message.emit("error", f"Piezo Connect Error: {e}")

    @pyqtSlot()
    def disconnect_device(self):
        """UI에서 Disconnect 버튼을 누르거나 프로그램 종료 시 호출됨."""
        if self.poll_timer:
            self.poll_timer.stop()
        if self.controller and self._is_connected:
            self.controller.disconnect() 
            self._is_connected = False
            self.sig_message.emit("info", "Piezo disconnected.")
            
    @pyqtSlot(float)
    def move_to(self, z_um):
        if not self._is_connected or self.controller is None:
            self.sig_message.emit("error", "Piezo is not connected.")
            return

        if self.poll_timer and self.poll_timer.isActive():
            self.poll_timer.stop()

        try:
            self.controller.move_to(z_um) 
            time.sleep(0.1) 
            self.sig_message.emit("info", f"[Moved] Piezo Z -> {z_um}μm")
            self._poll_position()
        except Exception as e:
            self.sig_message.emit("error", f"Piezo Move Error: {e}")
        finally:
            if self.poll_timer and self._is_connected:
                self.poll_timer.start(100)

    def _poll_position(self):
        if not self._is_connected or self.controller is None:
            return
        try:
            current_z = self.controller.get_position() 
            if current_z is not None:
                self.sig_position_updated.emit(float(current_z))
        except Exception as e:
            self.sig_message.emit("error", f"Piezo Polling Error: {e}")

    @pyqtSlot()
    def close_connection(self):
        """프로그램 종료 시 타이머와 포트를 안전하게 닫는다."""
        if self.poll_timer:
            self.poll_timer.stop()
        if self.controller and self._is_connected:
            self.controller.disconnect() 
            self._is_connected = False