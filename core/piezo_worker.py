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

    def __init__(self, port='3'): 
            # 'COM3'가 아니라 '3'처럼 숫자 문자열만 넘겨야 Backend의 xDev_init과 호환됨.
            super().__init__()
            self.port = port
            self.controller = None
            self.poll_timer = None
            self._is_connected = False

    @pyqtSlot()
    def initialize(self):
        """
        QThread가 시작된 직후 호출되어야 한다.
        타이머(QTimer)는 반드시 해당 스레드 컨텍스트 내부에서 생성되어야 하기 때문.
        """
        if not _PIEZO_AVAILABLE:
            self.sig_message.emit("error", "hardware.PiezoController를 찾을 수 없음.")
            return

        try:
            # 1. 파라미터 없이 인스턴스화
            self.controller = PiezoController()
            
            # 2. connect 메서드를 명시적으로 호출하고 반환값(True/False) 검증
            if not self.controller.connect(port=self.port):
                self.sig_message.emit("error", f"Piezo connection failed on COM{self.port}")
                return
            
            self._is_connected = True
            self.sig_message.emit("info", f"Piezo connected on COM{self.port}")

            # 폴링 타이머 가동 (100ms)
            self.poll_timer = QTimer()
            self.poll_timer.timeout.connect(self._poll_position)
            self.poll_timer.start(100)
            
        except Exception as e:
            self.sig_message.emit("error", f"Piezo Init Error: {e}")


    @pyqtSlot(float)
    def move_to(self, z_um):
        """UI에서 이동 명령을 내릴 때 호출된다. Race Condition을 완벽히 차단한다."""
        if not self._is_connected or self.controller is None:
            self.sig_message.emit("error", "Piezo is not initialized.")
            return

            # 1. 방어: 통신 충돌을 막기 위해 100ms 폴링 타이머를 즉각 일시정지
        if self.poll_timer and self.poll_timer.isActive():
            self.poll_timer.stop()

        try:
            # 2. 이동 명령 송신 (네 백엔드 메서드 이름에 맞춰 수정할 것)
            self.controller.move_to(z_um) 
            
            # 3. Settling Time 대기 (50~100ms)
            # 메인 스레드가 아니므로 time.sleep()을 써도 UI가 멈추지 않음.
            time.sleep(0.1) 
            
            self.sig_message.emit("info", f"[Moved] Piezo Z -> {z_um}μm")
            
            # 4. 강제 업데이트 (이동 직후의 위치를 즉시 읽음)
            self._poll_position()
            
        except Exception as e:
            self.sig_message.emit("error", f"Piezo Move Error: {e}")
        finally:
            # 5. 복구: 버스 라인이 안전해졌으므로 타이머 재가동
            if self.poll_timer:
                self.poll_timer.start(100)

    def _poll_position(self):
        """타이머에 의해 주기적으로 호출되어 실제 물리적 위치를 조회한다."""
        if not self._is_connected or self.controller is None:
            return
        
        try:
            # 백엔드 위치 조회 메서드 호출
            current_z = self.controller.get_position() 
            if current_z is not None:
                self.sig_position_updated.emit(float(current_z))
        except Exception as e:
            # 시리얼 읽기 실패 시 에러만 띄우고 스레드를 죽이진 않음
            self.sig_message.emit("error", f"Piezo Polling Error: {e}")

    @pyqtSlot()
    def close_connection(self):
        """프로그램 종료 시 타이머와 포트를 안전하게 닫는다."""
        if self.poll_timer:
            self.poll_timer.stop()
        if self.controller and self._is_connected:
            self.controller.disconnect() 
            self._is_connected = False