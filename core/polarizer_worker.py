import time
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

try:
    from pylablib.devices import Thorlabs
    _THORLABS_AVAILABLE = True
except ImportError:
    _THORLABS_AVAILABLE = False

class PolarizerWorker(QObject):
    """
    Thorlabs KDC101 (Kinesis) 편광기 제어를 전담하는 비동기 워커.
    이동이 완료되면 sig_moved 시그널을 방출하여 Controller의 다음 시퀀스를 트리거한다.
    """
    sig_message = pyqtSignal(str, str)  # level, message
    sig_moved = pyqtSignal(float)       # 목표 각도 도달 완료 알림
    sig_homed = pyqtSignal()            # 홈(Home) 복귀 완료 알림

    def __init__(self, serial_number="27273690"):
        super().__init__()
        # TODO: 시리얼 넘버는 추후 Default.py로 빼서 전역으로 관리할 것
        self.serial_number = serial_number
        self.motor = None
        self._is_connected = False
        self._simulation_mode = False

        # PRM1Z8 물리 각도 변환 스케일 (counts / deg, counts / (deg/s), counts / (deg/s^2))
        self.scale = (1919.6418578623391, 42941.66, 14.66)

    @pyqtSlot()
    def initialize(self):
        """QThread 시작 직후 호출되어 장비와 연결을 맺는다."""
        if not _THORLABS_AVAILABLE:
            self.sig_message.emit("error", "pylablib not installed. Polarizer Offline.")
            self._simulation_mode = True
            return

        try:
            self.motor = Thorlabs.KinesisMotor(self.serial_number, scale=self.scale)
            self._is_connected = True
            self.sig_message.emit("info", f"Polarizer Connected (S/N: {self.serial_number})")
        except Exception as e:
            self.sig_message.emit("error", f"Polarizer Connection Failed: {e}")
            self._simulation_mode = True

    @pyqtSlot()
    def home_device(self):
        """
        홈(0도) 위치로 강제 초기화.
        Homing은 물리적으로 최대 1분까지 걸릴 수 있는 매우 긴 블로킹 작업이므로,
        initialize()에서 분리하여 UI 버튼을 통해 별도로 실행하도록 설계.
        """
        if self._simulation_mode or not self._is_connected:
            self.sig_message.emit("info", "[Offline] Polarizer Homing simulated...")
            time.sleep(1.0)
            self.sig_homed.emit()
            return

        try:
            self.sig_message.emit("info", "Polarizer Homing... (May take a minute)")
            # sync=True로 대기하더라도 Worker 스레드이므로 GUI는 멈추지 않음
            self.motor.home(sync=True, timeout=60.0) 
            self.sig_message.emit("info", "Polarizer Homing Complete.")
            self.sig_homed.emit()
        except Exception as e:
            self.sig_message.emit("error", f"Polarizer Homing Error: {e}")

    @pyqtSlot(float)
    def move_to(self, angle_deg):
        """특정 각도로 회전 후 완료 시그널 방출."""
        if self._simulation_mode or not self._is_connected:
            self.sig_message.emit("info", f"[Offline] Polarizer moved to {angle_deg} deg")
            time.sleep(0.5) # 모터 이동 시간 모의(Mocking)
            self.sig_moved.emit(angle_deg)
            return

        try:
            self.motor.move_to(angle_deg)
            # 모터가 목표 각도에 물리적으로 도달할 때까지 스레드 대기
            self.motor.wait_move(timeout=10.0) 
            
            self.sig_message.emit("info", f"Polarizer moved to {angle_deg} deg")
            self.sig_moved.emit(angle_deg) # 🟢 컨트롤러로 이동 완료 핑(Ping) 전송
        except Exception as e:
            self.sig_message.emit("error", f"Polarizer Move Error: {e}")

    @pyqtSlot()
    def close_connection(self):
        """프로그램 종료 시 장비 포트 안전 해제."""
        if self.motor and self._is_connected:
            try:
                self.motor.close()
                self._is_connected = False
                self.sig_message.emit("info", "Polarizer connection closed.")
            except Exception as e:
                self.sig_message.emit("error", f"Polarizer Close Error: {e}")