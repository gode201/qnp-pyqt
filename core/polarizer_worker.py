import time
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer

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
    sig_initialized = pyqtSignal(bool)

    def __init__(self, serial_number="27273690"):
        super().__init__()
        self.serial_number = serial_number
        self.motor = None
        self._is_connected = False
        self._simulation_mode = True # 기본값을 안전하게 모의 모드로 설정
        self.scale = (1919.6418578623391, 42941.66, 14.66) # PRM1Z8 물리 각도 변환 스케일 (counts / deg, counts / (deg/s), counts / (deg/s^2))
        self.poll_timer = None

    @pyqtSlot()
    def initialize(self):
        """시작 시 하드웨어 연결을 시도하지 않고 타이머만 준비 (GUI Freezing 방지)"""
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll_status)
        self.sig_message.emit("info", "Polarizer Worker Initialized (Offline)")

    @pyqtSlot()
    def connect_device(self):
        """UI에서 Connect 버튼을 눌렀을 때 명시적으로 통신을 시작"""
        if not _THORLABS_AVAILABLE:
            self.sig_message.emit("error", "pylablib not installed. Sim Mode Only.")
            self._simulation_mode = True
            self.sig_initialized.emit(True) # True를 뱉어야 UI가 활성화되어 Dry Run 테스트 가능
            return

        try:
            self.motor = Thorlabs.KinesisMotor(self.serial_number, scale=self.scale)
            self._is_connected = True
            self._simulation_mode = False
            self.sig_message.emit("info", f"Polarizer Connected (S/N: {self.serial_number})")
            self.sig_initialized.emit(True)
            self.poll_timer.start(2000) # 2초마다 생존 확인용 폴링 시작
        except Exception as e:
            self.sig_message.emit("error", f"Polarizer Connection Failed: {e}")
            self._simulation_mode = True
            self.sig_initialized.emit(True) 

    @pyqtSlot()
    def disconnect_device(self):
        if self.poll_timer:
            self.poll_timer.stop()
        if self.motor and self._is_connected:
            try:
                self.motor.close()
            except Exception:
                pass
        self._is_connected = False
        self.motor = None
        self.sig_message.emit("info", "Polarizer Disconnected.")
        self.sig_initialized.emit(False)

    def _poll_status(self):
        """장비가 중간에 꺼졌는지 확인하는 로직"""
        if not self._is_connected or not self.motor:
            return
        try:
            # 상태 조회를 시도하여 예외가 발생하면 물리적 단절로 간주
            self.motor.get_position()
        except Exception as e:
            self.sig_message.emit("error", f"Polarizer Connection Lost: {e}")
            self.disconnect_device()

    @pyqtSlot(float)
    def move_to(self, target_deg):
        """최단 거리 연산을 적용한 지능형 이동 명령"""
        if self._simulation_mode or not self._is_connected:
            self.sig_message.emit("info", f"[Offline] Polarizer moved to {target_deg} deg")
            time.sleep(0.5)
            self.sig_moved.emit(target_deg)
            return

        try:
            current_pos = self.motor.get_position()
            
            # 180도 기준 최단 거리(Shortest Path) 계산 모듈
            diff = (target_deg - current_pos) % 360
            if diff > 180:
                diff -= 360
            
            # 이미 목표 위치면 이동 생략
            if abs(diff) > 0.01:
                self.motor.move_by(diff) # 절대 좌표가 아닌 '상대 각도'만큼 이동하여 역회전 방지
                self.motor.wait_for_stop(timeout=10.0) 
            
            self.sig_message.emit("info", f"Polarizer moved to {target_deg} deg")
            self.sig_moved.emit(target_deg)
        except Exception as e:
            self.sig_message.emit("error", f"Polarizer Move Error: {e}")

    @pyqtSlot()
    def home_device(self):
        """
        느린 하드웨어 원점 캘리브레이션. 
        단순히 0도로 이동하는 건 move_to(0)가 처리하므로, 
        이 메서드는 장비의 영점이 물리적으로 완전히 틀어졌을 때만 수동으로 호출하는 용도다.
        """
        if self._simulation_mode or not self._is_connected:
            self.sig_message.emit("info", "[Offline] Hardware Homing bypassed.")
            time.sleep(1.0)
            self.sig_homed.emit()
            return

        try:
            self.sig_message.emit("info", "Hardware Homing... (May take a minute)")
            self.motor.home(sync=True, timeout=60.0) 
            self.sig_message.emit("info", "Hardware Homing Complete.")
            self.sig_homed.emit()
        except Exception as e:
            self.sig_message.emit("error", f"Hardware Homing Error: {e}")

    @pyqtSlot()
    def close_connection(self):
        self.disconnect_device()