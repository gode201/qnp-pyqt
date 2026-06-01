import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

try:
    from hardware.PicoHarpController import PicoHarpController
    _PH_AVAILABLE = True
except ImportError:
    _PH_AVAILABLE = False

class PicoHarpWorker(QObject):
    """
    PicoHarp 300 제어를 전담하는 Worker.
    백엔드(PicoHarpController) 내부의 자체 측정 스레드에서 발생하는 
    콜백(Callback)을 PyQt 시그널로 변환하여 메인 GUI 스레드로 안전하게 전달한다.
    """
    sig_message = pyqtSignal(str, str)
    
    # 시간축(Time bins) 배열과 카운트(Counts) 배열 방출
    sig_histogram_updated = pyqtSignal(np.ndarray, np.ndarray)
    # Sync rate, Count rate 갱신
    sig_count_rate_updated = pyqtSignal(int, int)
    # 측정 완료 시그널 (모드 문자열)
    sig_measurement_finished = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.controller = None
        self._is_connected = False
        self._is_measuring = False

    @pyqtSlot()
    def initialize(self):
        """QThread가 시작된 후 하드웨어 포트를 열고 콜백을 연결한다."""
        if not _PH_AVAILABLE:
            self.sig_message.emit("error", "hardware.PicoHarpController 모듈이 없음.")
            return

        try:
            self.controller = PicoHarpController()
            
            # 연결 시도 (반환값이 "OK"로 시작하는지 확인)
            conn_result = self.controller.connect()
            if not conn_result.startswith("OK"):
                self.sig_message.emit("error", f"PicoHarp 연결 실패: {conn_result}")
                return
            
            self._is_connected = True
            self.sig_message.emit("info", f"PicoHarp 300 연결됨: {conn_result}")

            # 🔴 [핵심 배선] 백엔드의 콜백(Callback)을 Worker의 내부 메서드로 묶는다.
            # 백엔드 스레드가 이 콜백을 부르면, 내부에서 pyqtSignal.emit을 호출하여 
            # 스레드 간 안전한(Thread-safe) 데이터 전달을 수행함.
            self.controller.on_histogram_update = self._on_hist_update_callback
            self.controller.on_measurement_done = self._on_meas_done_callback
            self.controller.on_count_rate = self._on_count_rate_callback
            
        except Exception as e:
            self.sig_message.emit("error", f"PicoHarp Init Error: {e}")

    # --- 콜백 핸들러 (Backend Thread Context) ---
    def _on_hist_update_callback(self, histogram: np.ndarray, elapsed_ms: float):
        """백엔드 측정 스레드에서 주기적으로 호출됨."""
        if self.controller:
            # X축(시간) 배열을 백엔드에서 가져와 Y축(카운트)과 함께 묶어서 방출
            time_axis = self.controller.get_time_axis_ns(len(histogram))
            self.sig_histogram_updated.emit(time_axis, histogram)

    def _on_meas_done_callback(self, mode: str):
        self._is_measuring = False
        self.sig_measurement_finished.emit(mode)
        self.sig_message.emit("info", f"PicoHarp 측정 완료 ({mode})")

    def _on_count_rate_callback(self, sync: int, chan: int):
        self.sig_count_rate_updated.emit(sync, chan)

    # --- 제어 슬롯 (Main Thread Context -> Worker) ---
    @pyqtSlot(dict)
    def start_measurement(self, params):
        """Histogram 모드 측정을 시작한다."""
        if not self._is_connected or self.controller is None:
            self.sig_message.emit("error", "PicoHarp가 연결되지 않음.")
            return
            
        if self.controller.is_measuring:
            self.sig_message.emit("error", "이미 측정 중입니다.")
            return

        try:
            acqtime_ms = params.get('acqtime_ms', 1000)
            binning = params.get('binning', 0)
            offset_ps = params.get('offset_ps', 0)
            stop_overflow = params.get('stop_overflow', False)
            
            # 백엔드 내부 스레드 가동 (PH_StartMeas)
            self.controller.start_histogram(acqtime_ms, binning, offset_ps, stop_overflow)
            
            self._is_measuring = True
            self.sig_message.emit("info", f"PicoHarp 히스토그램 측정 시작 ({acqtime_ms} ms)")
            
        except Exception as e:
            self._is_measuring = False
            self.sig_message.emit("error", f"PicoHarp Start Error: {e}")

    @pyqtSlot()
    def stop_measurement(self):
        """측정을 강제 중단한다."""
        if not self.controller or not self.controller.is_measuring:
            return
            
        try:
            self.controller.stop_measurement()
        except Exception as e:
            self.sig_message.emit("error", f"PicoHarp Stop Error: {e}")
        finally:
            self._is_measuring = False

    @pyqtSlot()
    def close_connection(self):
        """프로그램 종료 시 포트 안전 해제"""
        self.stop_measurement()
        if self.controller and self._is_connected:
            self.controller.disconnect()
            self._is_connected = False