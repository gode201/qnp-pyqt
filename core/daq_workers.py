import time
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


from core.Default import UNIT_CONVERSION_FACTOR, GALVO_SETTLING_TIME, PIEZO_SETTLING_TIMEOUT

try:
    import nidaqmx
    import nidaqmx.system
    import nidaqmx.constants
    _NIDAQMX_AVAILABLE = True
except ModuleNotFoundError:
    _NIDAQMX_AVAILABLE = False

class PLScanWorker(QObject):

    """
    Galvo 제어(AO)와 APD 읽기(CI)를 동기화하여 2D/3D 이미지를 생성하는 완전 독립 Worker. Galvo의 단발적 컨트롤에 대한 worker는 하단에 별도로 존재
    UI 객체(GUI)에 대한 참조를 일절 가지지 않는다.
    """
    # -------------------------------------------------------------------------
    # Signals (메인 GUI 스레드로 결과를 전달하는 유일한 통로)
    # -------------------------------------------------------------------------
    sig_scan_started = pyqtSignal()
    sig_scan_progress = pyqtSignal(np.ndarray, tuple) # grid, x_min, x_max, y_min, y_max
    sig_message = pyqtSignal(str, str) # level("info"/"error"), message
    sig_scan_finished = pyqtSignal(bool, str) # success, filepath
    sig_status_update = pyqtSignal(str, float) # mode, remaining_time

    def __init__(self):
        super().__init__()
        self._is_scanning = False
        

    def um_to_v(self, um): return um / self.unit_conv
    def v_to_um(self, v):  return v * self.unit_conv

    @pyqtSlot(dict)
    def start_scan(self, params):
        """AppController에서 전달받은 파라미터 딕셔너리로 스캔 시작"""
        if not _NIDAQMX_AVAILABLE:
            self.sig_message.emit("error", "nidaqmx not installed — DAQ hardware disabled.")
            self.sig_scan_finished.emit(False, "")
            return

        if self._is_scanning:
            return

        self._is_scanning = True
        self.sig_scan_started.emit()

        mode = params.get('mode', 'Triangle')
        
        try:
            if mode == 'Triangle':
                self._perform_mapping_triangle(params)
            elif mode == 'Discrete':
                # TODO: 기존 perform_mapping 로직을 이 패턴으로 이관할 것
                pass
            else:
                self.sig_message.emit("error", f"Mode {mode} not fully implemented yet.")
        except Exception as e:
            self.sig_message.emit("error", f"Scan Error: {e}")
        finally:
            self._is_scanning = False
            self.sig_scan_finished.emit(True, "Auto-saved-path.txt") # 저장 로직 연동 필요

    @pyqtSlot()
    def stop_scan(self):
        self._is_scanning = False

    def _perform_mapping_triangle(self, p):
        """하드웨어 타이밍(SampleClock 동기화) 기반 Triangle 스캔"""
        # UI 파라미터 언패킹 (self.gui.get() 대신 딕셔너리 사용)
        x_min_v, x_max_v = self.um_to_v(p['x_min']), self.um_to_v(p['x_max'])
        y_min_v, y_max_v = self.um_to_v(p['y_min']), self.um_to_v(p['y_max'])
        x_steps, y_steps = p['x_steps'], p['y_steps']
        
        pixel_dwell = p.get('exposure_time', 0.001)
        ao_sample_rate = p.get('ao_sample_rate', 50000)

        # 데이터 컨테이너 초기화
        pl_data_grid = np.full((y_steps, x_steps), np.nan)
        y_voltages = np.linspace(y_min_v, y_max_v, y_steps)

        samples_per_pixel = max(int(pixel_dwell * ao_sample_rate), 2)
        samples_per_row = samples_per_pixel * x_steps
        n_settle = samples_per_pixel
        total_samples = samples_per_row + n_settle
        
        scan_start_time = time.time()
        completed_rows = 0

        with nidaqmx.Task() as ao_task, nidaqmx.Task() as ci_task:
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)
            ci_task.ci_channels.add_ci_count_edges_chan("Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING)
            ci_task.ci_channels[0].ci_count_edges_term = "/Dev2/PFI0"

            for j in range(y_steps):
                if not self._is_scanning:
                    break

                y_v = y_voltages[j]

                # Triangle 파형 생성 (짝수행 좌→우, 홀수행 우→좌)
                if j % 2 == 0:
                    settle_x = np.full(n_settle, x_min_v)
                    scan_x   = np.linspace(x_min_v, x_max_v, samples_per_row)
                else:
                    settle_x = np.full(n_settle, x_max_v)
                    scan_x   = np.linspace(x_max_v, x_min_v, samples_per_row)
                
                x_waveform = np.concatenate([settle_x, scan_x])
                y_waveform = np.full(total_samples, y_v)

                # 하드웨어 타이밍 동기화 (기존 로직 유지)
                ao_task.timing.cfg_samp_clk_timing(rate=ao_sample_rate, samps_per_chan=total_samples)
                ao_task.write(np.array([x_waveform, y_waveform]), auto_start=False)
                ci_task.timing.cfg_samp_clk_timing(rate=ao_sample_rate, source="/Dev2/ao/SampleClock", samps_per_chan=total_samples)

                ci_task.start()
                ao_task.start()

                # Settle 데이터 읽기 (Transient 흡수)
                settle_data = np.array(ci_task.read(number_of_samples_per_channel=n_settle, timeout=10.0))
                prev_cum = settle_data[-1]

                pixel_counts = np.zeros(x_steps)
                last_plot_time = 0.0
                
                for px in range(x_steps):
                    if not self._is_scanning:
                        break
                    
                    partial = np.array(ci_task.read(number_of_samples_per_channel=samples_per_pixel, timeout=10.0))
                    photons = np.diff(np.concatenate([[prev_cum], partial]))
                    pixel_count = float(photons.sum()) / pixel_dwell
                    prev_cum = partial[-1]

                    i = px if j % 2 == 0 else x_steps - 1 - px
                    pixel_counts[i] = pixel_count
                    pl_data_grid[j, i] = pixel_count

                    # UI 업데이트 시그널 발송 (100ms Throttle)
                    now = time.time()
                    if now - last_plot_time >= 0.1:
                        extent_tuple = (p['x_min'], p['x_max'], p['y_min'], p['y_max'])
                        self.sig_scan_progress.emit(pl_data_grid.copy(), extent_tuple)
                        last_plot_time = now

                ao_task.stop()
                ci_task.stop()

                # 한 Row 종료 시 상태바 예상 시간 계산 시그널 발송
                completed_rows += 1
                elapsed = time.time() - scan_start_time
                remaining_sec = (elapsed / completed_rows) * (y_steps - j)
                self.sig_status_update.emit("scan_remaining", remaining_sec)
                
                # 라벨 정보 갱신
                curr_y_um = self.v_to_um(y_v)
                self.sig_message.emit("info", f"Row y={curr_y_um:.2f}μm avg={np.nanmean(pixel_counts):.2e}")

        # Galvo Zero 복귀 등 하드웨어 정리 로직은 별도 슬롯이나 Controller에서 처리 권장

class ContinuousAPDWorker(QObject):
    """
    실시간 APD 카운트를 무한 폴링하는 Worker.
    UI 스레드 개입 없이 nidaqmx 카운터를 독립적으로 읽는다.
    """
    sig_counts_updated = pyqtSignal(list)  # [[elapsed_s, cps], ...]
    sig_message = pyqtSignal(str, str)     # level("info"/"error"), message
    sig_stopped = pyqtSignal()             # 워커가 안전하게 종료되었음을 알림

    def __init__(self):
        super().__init__()
        self._is_running = False
        self.apd_counts = []
        self.start_time = 0

    @pyqtSlot(float, int)
    def start_counting(self, exposure_time=0.1, plot_limit=50):
        """
        exposure_time: 데이터 갱신 주기 (s)
        plot_limit: 그래프에 유지할 최대 데이터 포인트 개수 (0이면 무제한)
        """
        if not _NIDAQMX_AVAILABLE:
            self.sig_message.emit("error", "nidaqmx is not available. APD Counting disabled.")
            return

        self._is_running = True
        self.apd_counts.clear()
        self.start_time = time.time()
        
        try:
            import nidaqmx
            import nidaqmx.constants
            
            with nidaqmx.Task() as count_task:
                count_task.ci_channels.add_ci_count_edges_chan("Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING)
                count_task.ci_channels[0].ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()

                last_count = count_task.read()

                while self._is_running:
                    t_start = time.perf_counter()
                    
                    # 반응성을 극대화하기 위한 Sleep 쪼개기
                    # exposure_time (예: 0.1초)을 한 번에 sleep하면 중지 버튼을 눌러도 즉시 반응하지 않음.
                    # 따라서 0.01초 단위로 쪼개어 중단 플래그(_is_running)를 검사함.
                    t_end = t_start + exposure_time
                    while time.perf_counter() < t_end:
                        if not self._is_running:
                            break
                        time.sleep(0.01)
                        
                    if not self._is_running:
                        break

                    # 카운트 읽기 및 CPS 계산
                    current_raw = count_task.read()
                    elapsed = time.perf_counter() - t_start
                    
                    cps = (current_raw - last_count) / elapsed if elapsed > 0 else 0.0
                    last_count = current_raw
                    
                    elapsed_total = time.time() - self.start_time
                    self.apd_counts.append([elapsed_total, cps])
                    
                    # 메모리 누수 방지 및 그래프 제한
                    if plot_limit > 0 and len(self.apd_counts) > plot_limit:
                        self.apd_counts = self.apd_counts[-plot_limit:]
                    
                    # UI로 데이터 던지기
                    self.sig_counts_updated.emit(self.apd_counts)
                    self.sig_message.emit("info", f"{cps:.2e}") # 상태바/라벨용 텍스트

        except Exception as e:
            self.sig_message.emit("error", f"APD Polling Error: {str(e)}")
        finally:
            self._is_running = False
            self.sig_stopped.emit()

    @pyqtSlot()
    def stop_counting(self):
        """루프 플래그를 해제하여 안전하게 스레드를 종료시킨다."""
        self._is_running = False

class GalvoWorker(QObject):
    """
    단발성 Galvo X, Y 위치 이동을 처리하는 전용 Worker. PL scanner는 스캔 루프가 무겁기 때문에 별도의 worker로 분리 상단에 존재.
    메인 스레드를 블로킹하지 않기 위해 독립된 QThread에서 실행된다.
    """
    sig_message = pyqtSignal(str, str) # level, message
    sig_moved = pyqtSignal(float, float) # x_um, y_um

    def __init__(self):
        super().__init__()

    @pyqtSlot(float, float)
    def move_to(self, x_um, y_um):
        if not _NIDAQMX_AVAILABLE:
            self.sig_message.emit("error", "nidaqmx is not available. Galvo move disabled.")
            return

        try:
            import nidaqmx
            
            # Default.py에서 임포트한 상수를 사용
            x_v = x_um / UNIT_CONVERSION_FACTOR
            y_v = y_um / UNIT_CONVERSION_FACTOR
            
            with nidaqmx.Task() as task:
                task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10.0, max_val=10.0)
                task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10.0, max_val=10.0)
                # 다중 채널이므로 리스트 형태로 한 번에 write
                task.write([x_v, y_v], auto_start=True)
                
            self.sig_moved.emit(x_um, y_um)
            self.sig_message.emit("info", f"[Moved] X={x_um:.2f}μm, Y={y_um:.2f}μm")
            
        except Exception as e:
            self.sig_message.emit("error", f"Galvo Move Error: {e}")