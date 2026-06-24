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

    # Z-Scan 및 Auto-Focus 결과 반환 시그널
    sig_zscan_finished = pyqtSignal(list)   # [[z, cps], ...]
    sig_autofocus_finished = pyqtSignal(dict) # result_dict

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
        if self.poll_timer and self._is_connected:
            self.controller.disconnect() 
            self._is_connected = False

    # -------------------------------------------------------------------------
    # Z-Scan / Auto-Focus (PiezoWorker 내부 통합)
    # -------------------------------------------------------------------------
    @pyqtSlot(dict)
    def start_zscan(self, params):
        """단순 1D Z Scan을 실행한다."""
        if not self._is_connected or self.controller is None:
            self.sig_message.emit("error", "Piezo is not connected for Z-Scan.")
            return

        # 1. Z축 이동 폴링 일시 중단
        if self.poll_timer and self.poll_timer.isActive():
            self.poll_timer.stop()

        try:
            import nidaqmx
            import nidaqmx.constants
            from core.z_autofocus import z_scan

            z_min = params.get('z_min', 0.0)
            z_max = params.get('z_max', 10.0)
            steps = params.get('steps', 50)
            dwell = params.get('dwell', 0.1)

            import numpy as np
            z_positions = np.linspace(z_min, z_max, steps)

            self.sig_message.emit("info", "Starting Z-Scan...")

            # 2. 로컬 카운터 태스크 생성 (APD Worker는 컨트롤러가 이미 껐음을 전제함)
            with nidaqmx.Task() as count_task:
                count_task.ci_channels.add_ci_count_edges_chan("Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING)
                count_task.ci_channels[0].ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()

                # 3. 스캔 실행
                data = z_scan(self.controller, count_task, z_positions, dwell)
                
            self.sig_zscan_finished.emit(data)
            self.sig_message.emit("info", "Z-Scan Completed.")

        except Exception as e:
            self.sig_message.emit("error", f"Z-Scan Error: {e}")
        finally:
            # 4. 폴링 재개
            if self.poll_timer and self._is_connected:
                self.poll_timer.start(100)

    @pyqtSlot(dict)
    def start_autofocus(self, params):
        """2-Pass Auto-Focus를 실행한다."""
        if not self._is_connected or self.controller is None:
            self.sig_message.emit("error", "Piezo is not connected for Auto-Focus.")
            return

        if self.poll_timer and self.poll_timer.isActive():
            self.poll_timer.stop()

        try:
            import nidaqmx
            import nidaqmx.constants
            from core.z_autofocus import run_autofocus

            self.sig_message.emit("info", f"Starting Auto-Focus ({params.get('focus_mode', 'plateau_center')})...")

            with nidaqmx.Task() as count_task:
                count_task.ci_channels.add_ci_count_edges_chan("Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING)
                count_task.ci_channels[0].ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()

                result = run_autofocus(
                    piezo=self.controller,
                    count_task=count_task,
                    dwell=params.get('dwell', 0.15),
                    coarse_step=params.get('coarse_step', 0.1),
                    coarse_range=params.get('coarse_range', None),
                    fine_step=params.get('fine_step', 0.02),
                    fine_range=params.get('fine_range', 1.0),
                    focus_mode=params.get('focus_mode', 'plateau_center'),
                    verbose=True
                )
                
            if result:
                self.sig_autofocus_finished.emit(result)
                self.sig_message.emit("info", f"Auto-Focus Completed. Z={result['actual_z']:.3f}")
            else:
                self.sig_message.emit("error", "Auto-Focus failed or returned None.")

        except Exception as e:
            self.sig_message.emit("error", f"Auto-Focus Error: {e}")
        finally:
            if self.poll_timer and self._is_connected:
                self.poll_timer.start(100)