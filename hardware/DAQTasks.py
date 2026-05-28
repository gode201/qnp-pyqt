# DAQTasks.py
import numpy as np
try:
    import nidaqmx
    import nidaqmx.system
    import nidaqmx.constants
    _NIDAQMX_AVAILABLE = True
except ModuleNotFoundError:
    _NIDAQMX_AVAILABLE = False
    print("[DAQTasks] nidaqmx not installed — DAQ hardware disabled.")
import threading
import time
import os
import ctypes
import tkinter as tk
from Default import GALVO_X_DEFAULT, GALVO_Y_DEFAULT, SAMPLING_INTERVAL, UNIT_CONVERSION_FACTOR, AUTO_SAVE_PATH, PHOTON_COUNT_SAVE_PATH, GALVO_SETTLING_TIME, AVERAGING_COUNT, DRIFT_CORRECTION_INTERVAL, DRIFT_SEARCH_OFFSET, AF_Z_MIN, AF_Z_MAX, AF_COARSE_STEP, AF_FINE_RANGE, AF_FINE_STEP, Z_TRACK_CYCLE, Z_TRACK_STEP, PIEZO_SETTLING_TIMEOUT, TRACK_AO_RATE, TRACK_SETTLE_MS, TRACK_DWELL_MS
from datetime import datetime
from z_autofocus import find_focus_target

def hw_4pt_track(center_x_v, center_y_v, offset_v,
                 ao_rate, settle_ms, dwell_ms,
                 daq_ao_x="Dev2/ao0", daq_ao_y="Dev2/ao1",
                 daq_counter="Dev2/ctr0", daq_pfi="/Dev2/PFI0"):
    """
    하드웨어 타이밍 4점 파형 추적 (v5.3.5).

    동작
    ----
    4개 probe point의 파형을 미리 생성하여 AO에 한 번에 출력.
    CI(카운터)는 AO SampleClock에 동기화 → 구간별 광자수 하드웨어로 집계.
    Python은 파형 완료 후 결과를 1회 read.

    파형 구조 (1점당)
    -----------------
    |← N_settle →|←── N_dwell ──→|
     ramp(이전→현재)   hold(현재값)

    Parameters
    ----------
    center_x_v, center_y_v : float  현재 중심 위치 (V)
    offset_v               : float  탐색 반경 (V)
    ao_rate                : int    AO 클럭 주파수 (S/s)
    settle_ms              : float  안정화 구간 (ms)
    dwell_ms               : float  측정 구간 (ms)

    Returns
    -------
    best_x_v, best_y_v : float  최대 CPS 위치 (V)
    best_cps           : float  최대 위치의 CPS
    """
    N_settle = max(2, int(ao_rate * settle_ms / 1000))
    N_dwell  = max(2, int(ao_rate * dwell_ms / 1000))
    N_pt     = N_settle + N_dwell
    N_total  = 4 * N_pt

    probe_pts = [
        (center_x_v - offset_v, center_y_v - offset_v),
        (center_x_v + offset_v, center_y_v - offset_v),
        (center_x_v - offset_v, center_y_v + offset_v),
        (center_x_v + offset_v, center_y_v + offset_v),
    ]

    # 파형 생성: 이전점 → 현재점 ramp + dwell hold
    x_wave = np.empty(N_total)
    y_wave = np.empty(N_total)
    prev_x, prev_y = center_x_v, center_y_v
    for i, (px, py) in enumerate(probe_pts):
        s = i * N_pt
        x_wave[s:s+N_settle] = np.linspace(prev_x, px, N_settle)
        y_wave[s:s+N_settle] = np.linspace(prev_y, py, N_settle)
        x_wave[s+N_settle:s+N_pt] = px
        y_wave[s+N_settle:s+N_pt] = py
        prev_x, prev_y = px, py

    # 마지막에 center로 복귀 ramp 추가 (다음 사이클 대비)
    N_return = N_settle
    x_ret = np.linspace(prev_x, center_x_v, N_return)
    y_ret = np.linspace(prev_y, center_y_v, N_return)
    x_wave = np.concatenate([x_wave, x_ret])
    y_wave = np.concatenate([y_wave, y_ret])
    N_full = len(x_wave)

    dev_name = daq_ao_x.split("/")[0]  # "Dev2"

    with nidaqmx.Task() as ao_task, nidaqmx.Task() as ci_task:
        ao_task.ao_channels.add_ao_voltage_chan(daq_ao_x, min_val=-10, max_val=10)
        ao_task.ao_channels.add_ao_voltage_chan(daq_ao_y, min_val=-10, max_val=10)
        ao_task.timing.cfg_samp_clk_timing(
            rate=ao_rate,
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=N_full)

        ch = ci_task.ci_channels.add_ci_count_edges_chan(
            counter=daq_counter,
            edge=nidaqmx.constants.Edge.RISING)
        ch.ci_count_edges_term = daq_pfi
        ci_task.timing.cfg_samp_clk_timing(
            rate=ao_rate,
            source=f"/{dev_name}/ao/SampleClock",  # AO 클럭과 동기화
            active_edge=nidaqmx.constants.Edge.RISING,
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=N_full)

        ao_task.write(np.array([x_wave, y_wave]), auto_start=False)

        ci_task.start()   # CI 먼저 시작 (클럭 대기 상태)
        ao_task.start()   # AO 시작 → 클럭 발생 → CI 동기 시작
        ao_task.wait_until_done(timeout=N_full / ao_rate * 3 + 2.0)

        raw = np.array(ci_task.read(
            number_of_samples_per_channel=N_full,
            timeout=2.0), dtype=np.int64)

    # 누적 카운트 → 구간별 카운트 (diff)
    counts = np.diff(raw, prepend=raw[0])
    counts[counts < -1e8] += 2**32   # 롤오버 보정

    # 각 point의 dwell 구간 합산
    best_sig, best_x, best_y = -1, center_x_v, center_y_v
    dwell_s = N_dwell / ao_rate
    for i, (px, py) in enumerate(probe_pts):
        s = i * N_pt + N_settle
        sig = int(counts[s:s+N_dwell].sum())
        if sig > best_sig:
            best_sig, best_x, best_y = sig, px, py

    best_cps = best_sig / dwell_s if dwell_s > 0 else 0.0
    return best_x, best_y, best_cps


class DAQTasks:
    def __init__(self, gui):
        self.gui = gui
        self.apd_counts = []
        self.scanning, self.counting, self.af_running = False, False, False
        self.pl_data_grid = None
        self.pl_data_list = []
        self.pl_data_3d = None
        self.start_time = None
        self.apd_plot_limit = 50
        self.save_folder = PHOTON_COUNT_SAVE_PATH
        # threading.Lock — Critical #5
        # _state_lock: scanning/counting/af_running 플래그 전환 원자성 보장
        # _data_lock : pl_data_grid / pl_data_list 교체 시 GUI 스레드 충돌 방지
        self._state_lock = threading.Lock()
        self._data_lock  = threading.Lock()
        # Z Scan 파라미터 (XZ/YZ/3D)
        self.z_scan_min = None
        self.z_scan_max = None
        self.z_steps = None
        # DAQ 장치 연결 여부 확인
        if not _NIDAQMX_AVAILABLE:
            self.daq_available = False
        else:
            try:
                dev_names = [d.name for d in nidaqmx.system.System.local().devices]
                self.daq_available = "Dev2" in dev_names
            except Exception:
                self.daq_available = False
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — hardware functions disabled.")

    def um_to_v(self, distance_um):
        return distance_um / UNIT_CONVERSION_FACTOR
    def v_to_um(self, distance_v):
        return distance_v * UNIT_CONVERSION_FACTOR

    def set_scan_parameters(self):
        try:
            self.x_min = self.um_to_v(float(self.gui.x_min_var.get()))
            self.x_max = self.um_to_v(float(self.gui.x_max_var.get()))
            self.y_min = self.um_to_v(float(self.gui.y_min_var.get()))
            self.y_max = self.um_to_v(float(self.gui.y_max_var.get()))
            self.x_steps = int(self.gui.x_steps_var.get())
            self.y_steps = int(self.gui.y_steps_var.get())
            self.expo_time = float(self.gui.exposure_time_var.get())
            return True
        except ValueError as e:
            print(f"Error: Invalid input value - {e}")
            return False

    def move_galvo(self, x_voltage=None, y_voltage=None):
        if not self.daq_available:
            return
        if x_voltage is None:
            x_voltage = self.um_to_v(float(self.gui.galvo_x_var.get()))
        if y_voltage is None:
            y_voltage = self.um_to_v(float(self.gui.galvo_y_var.get()))
        with nidaqmx.Task() as ao_task:
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0")
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1")
            ao_task.write([x_voltage, y_voltage], auto_start=True)

    def set_zero_position(self):
        self.move_galvo(self.um_to_v(GALVO_X_DEFAULT), self.um_to_v(GALVO_Y_DEFAULT))

    def move_up(self):
        step = float(self.gui.gv_y_step_var.get())
        y_um = float(self.gui.galvo_y_var.get()) - step
        self.gui.galvo_y_var.set(str(round(y_um, 5)))
        if not self.counting: self.move_galvo(y_voltage=self.um_to_v(y_um))

    def move_down(self):
        step = float(self.gui.gv_y_step_var.get())
        y_um = float(self.gui.galvo_y_var.get()) + step
        self.gui.galvo_y_var.set(str(round(y_um, 5)))
        if not self.counting: self.move_galvo(y_voltage=self.um_to_v(y_um))

    def move_left(self):
        step = float(self.gui.gv_x_step_var.get())
        x_um = float(self.gui.galvo_x_var.get()) - step
        self.gui.galvo_x_var.set(str(round(x_um, 5)))
        if not self.counting: self.move_galvo(x_voltage=self.um_to_v(x_um))

    def move_right(self):
        step = float(self.gui.gv_x_step_var.get())
        x_um = float(self.gui.galvo_x_var.get()) + step
        self.gui.galvo_x_var.set(str(round(x_um, 5)))
        if not self.counting: self.move_galvo(x_voltage=self.um_to_v(x_um))

    def start_apd_count(self, update_callback):
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — count skipped.")
            return
        # Orbital Tracking이 실행 중이면 먼저 종료 (AO/CI 채널 충돌 방지)
        if getattr(self.gui, 'orbital_tracking_enabled', False):
            self.gui.toggle_orbital_tracking()
        with self._state_lock:
            if self.counting:
                return  # 이미 실행 중 — 중복 시작 방지
            self.apd_counts = []
            self.counting = True
            self.start_time = time.time()
        threading.Thread(target=self.update_apd_count, args=(update_callback,), daemon=True).start()

    def stop_apd_count(self):
        with self._state_lock:
            self.counting = False
            self.start_time = None
        self.save_counts_to_file()

    def update_apd_count(self, update_callback):
        count_task = nidaqmx.Task()
        ao_task = nidaqmx.Task()

        try:
            count_task.ci_channels.add_ci_count_edges_chan(counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING)
            count_task.ci_channels[0].ci_count_edges_term = "/Dev2/PFI0"
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)

            count_task.start()
            start_time = time.time()
            last_count = count_task.read()

            scan_offset_um = 0.02
            last_gui_x, last_gui_y = float(self.gui.galvo_x_var.get()), float(self.gui.galvo_y_var.get())
            curr_x_v, curr_y_v = self.um_to_v(last_gui_x), self.um_to_v(last_gui_y)

            last_manual_move_time = time.time() - 6.0
            prev_photon_count = 0
            z_track_counter = 0

            while self.counting:
                # [2] 메인 데이터 측정 — 10ms 폴링으로 방향키 즉시 반응
                try:
                    expo_time = float(self.gui.exposure_time_var.get())
                except Exception:
                    expo_time = SAMPLING_INTERVAL
                if expo_time <= 0:
                    expo_time = SAMPLING_INTERVAL

                last_count = count_task.read()
                t_start = time.perf_counter()
                t_end = t_start + expo_time
                while time.perf_counter() < t_end:
                    # [1] GUI를 통한 조작 감지 — expo_time 중에도 즉시 반응
                    _nx = float(self.gui.galvo_x_var.get())
                    _ny = float(self.gui.galvo_y_var.get())
                    if abs(_nx - last_gui_x) > 1e-5 or abs(_ny - last_gui_y) > 1e-5:
                        curr_x_v, curr_y_v = self.um_to_v(_nx), self.um_to_v(_ny)
                        ao_task.write([curr_x_v, curr_y_v], auto_start=True)
                        last_gui_x, last_gui_y = _nx, _ny
                        last_manual_move_time = time.time()
                    if not self.counting:
                        break
                    time.sleep(0.01)
                current_raw = count_task.read()
                elapsed = time.perf_counter() - t_start

                cp_photon_count = (current_raw - last_count) / elapsed

                # [3] 외부 조작 감지
                if prev_photon_count > 0:
                    change_rate = abs(cp_photon_count - prev_photon_count) / prev_photon_count
                    if change_rate > 0.3:
                        last_manual_move_time = time.time()
                prev_photon_count = cp_photon_count

                # 그래프 및 GUI 업데이트
                self.apd_counts.append([time.time() - start_time, cp_photon_count])
                plot_data = self.apd_counts if self.apd_plot_limit == 0 else self.apd_counts[-self.apd_plot_limit:]
                self.gui.root.after(0, lambda d=plot_data, c=cp_photon_count: (
                    self.gui.info_label.config(text="%.2e" % c),
                    update_callback(d)
                ))

                # [4] 자동 추적 (v5.3.5 — 하드웨어 타이밍 4점 파형)
                if self.gui.auto_tracking_enabled:
                    try:
                        track_ao_rate  = max(20000, int(float(self.gui.track_ao_rate_var.get())))
                        track_settle   = max(0.1,   float(self.gui.track_settle_ms_var.get()))
                        track_dwell    = max(1.0,   float(self.gui.track_dwell_ms_var.get()))
                        offset_um      = float(self.gui.track_offset_var.get())
                    except Exception:
                        track_ao_rate, track_settle, track_dwell, offset_um = \
                            TRACK_AO_RATE, TRACK_SETTLE_MS, TRACK_DWELL_MS, 0.02

                    offset_v = self.um_to_v(offset_um)

                    # 기존 task 임시 중단 → HW 타이밍 scan → 재개
                    count_task.stop()
                    ao_task.stop()
                    try:
                        bx, by, best_cps = hw_4pt_track(
                            curr_x_v, curr_y_v, offset_v,
                            track_ao_rate, track_settle, track_dwell)
                    except Exception as _te:
                        print(f"[Track HW 오류] {_te} — 소프트웨어 방식으로 대체")
                        bx, by, best_cps = curr_x_v, curr_y_v, 0.0
                    finally:
                        # tasks 재시작
                        ao_task.write([bx, by], auto_start=True)
                        count_task.start()

                    curr_x_v, curr_y_v = bx, by

                    # 보정 후 좌표 GUI 업데이트
                    last_gui_x, last_gui_y = round(self.v_to_um(bx), 6), round(self.v_to_um(by), 6)
                    self.gui.root.after(0, lambda x=last_gui_x, y=last_gui_y:
                        (self.gui.galvo_x_var.set(str(x)), self.gui.galvo_y_var.set(str(y))))

                    # 플롯 업데이트
                    self.apd_counts.append([time.time() - start_time, best_cps])
                    self.gui.root.after(0, lambda d=self.apd_counts[-self.apd_plot_limit:], c=best_cps:
                        update_callback(d))

                    # XY 트래킹 로그 기록
                    _log_path = getattr(self.gui, '_track_log_path', None)
                    if _log_path:
                        _elapsed = time.perf_counter() - self.gui._track_log_start_t
                        _ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
                        try:
                            with open(_log_path, "a", encoding="utf-8") as _f:
                                _f.write(f"{_ts},{_elapsed:.3f},{last_gui_x:.6f},{last_gui_y:.6f},{best_cps:.1f}\n")
                        except OSError:
                            pass

                    last_count = count_task.read()

                    # [5] Z Tracking (매 N사이클마다)
                    z_track_counter += 1
                    if (self.gui.z_tracking_enabled
                            and self.gui.piezo.is_connected()
                            and z_track_counter >= self.gui.z_track_cycle):
                        z_track_counter = 0
                        try:
                            z_step = float(self.gui.z_track_step_var.get())
                        except Exception:
                            z_step = Z_TRACK_STEP

                        current_z = self.gui.piezo.get_position()
                        z_points = [current_z + z_step * d for d in [-2, -1, 0, 1, 2]]

                        max_z_sig, best_z = -1, current_z
                        for zp in z_points:
                            if not self.counting:
                                break
                            self.gui.piezo.move_to(zp)
                            self.gui.piezo.wait_on_target(timeout=2.0)

                            c_pre = count_task.read()
                            t_start = time.perf_counter()
                            time.sleep(current_interval)
                            z_sig = count_task.read() - c_pre
                            elapsed_z = time.perf_counter() - t_start

                            z_sig_per_sec = z_sig / elapsed_z
                            self.apd_counts.append([time.time() - start_time, z_sig_per_sec])
                            self.gui.root.after(0, lambda d=self.apd_counts[-self.apd_plot_limit:], c=z_sig_per_sec:
                                update_callback(d))

                            if z_sig > max_z_sig:
                                max_z_sig, best_z = z_sig, zp

                        self.gui.piezo.move_to(best_z)
                        self.gui.piezo.wait_on_target(timeout=2.0)
                        last_count = count_task.read()

                    time.sleep(0.1)

        except Exception as e:
            print(f"Error: {e}")
        finally:
            self.counting = False
            count_task.close()
            ao_task.close()
            self.gui.root.after(0, lambda: self.gui.state_management("default"))

    def save_counts_to_file(self):
        if not self.apd_counts:
            print("No data to save.")
            return

        os.makedirs(self.save_folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(self.save_folder, f"photon_counts_{timestamp}.txt")
        with open(file_path, "w") as f:
            f.write("(Time)\t(Counts)\n")
            for time_value, count in self.apd_counts:
                f.write(f"{time_value:.1f}\t{count:.2e}\n")
        print(f"Data saved: {file_path}")
        self.gui.info_label.config(text=f"Data saved: {file_path}")
    

# ------------------------------------------- PL SCAN 관련  -----------------------------------------------

    def start_scan(self):
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — scan skipped.")
            return
        # Orbital Tracking 종료 (채널 충돌 방지)
        if getattr(self.gui, 'orbital_tracking_enabled', False):
            self.gui.toggle_orbital_tracking()
        with self._state_lock:
            if self.scanning:
                return  # 중복 시작 방지 — Critical #6
            self.scanning = True
        def scan_thread():
            try:
                if self.set_scan_parameters():
                    self._scan_params_backup = {"x_min": self.x_min, "x_max": self.x_max, "y_min": self.y_min, "y_max": self.y_max, "x_steps": self.x_steps, "y_steps": self.y_steps}
                    with self._data_lock:
                        self.pl_data_grid, self.pl_data_list = None, []
                    self.perform_mapping(resume=False)
            finally:
                with self._state_lock:
                    self.scanning = False
                self.gui.scan_button.config(text="Scan Start")
                self.gui.count_button.config(state=tk.NORMAL)
        threading.Thread(target=scan_thread, daemon=True).start()

    def resume_scan(self):
        with self._state_lock:
            self.scanning = True
        def scan_thread():
            try:
                p = self._scan_params_backup
                self.x_min, self.x_max, self.y_min, self.y_max = p["x_min"], p["x_max"], p["y_min"], p["y_max"]
                self.x_steps, self.y_steps = p["x_steps"], p["y_steps"]
                self.perform_mapping(resume=True)
            finally:
                self.scanning = False
                self.gui.scan_button.config(text="Scan Start")
                self.gui.count_button.config(state=tk.NORMAL)
        threading.Thread(target=scan_thread, daemon=True).start()

    def stop_scan(self):
        with self._state_lock:
            self.scanning = False
        time.sleep(0.3)
        self.set_zero_position()

    #---------- 수정 ----------
        
    def measure_drift_offset(self, ao_task, count_task, ref_x_v, ref_y_v, settling, expo_time):
        """기준점 주변 4점을 탐색하여 drift offset(전압 단위)을 반환"""
        offset_v = self.um_to_v(DRIFT_SEARCH_OFFSET)
        search_pts = [
            (ref_x_v - offset_v, ref_y_v),
            (ref_x_v + offset_v, ref_y_v),
            (ref_x_v, ref_y_v - offset_v),
            (ref_x_v, ref_y_v + offset_v),
            (ref_x_v, ref_y_v),  # 중심점도 포함
        ]

        max_count, best_x, best_y = -1, ref_x_v, ref_y_v
        for sx, sy in search_pts:
            ao_task.write([sx, sy], auto_start=True)
            time.sleep(settling)
            c_before = count_task.read()
            t_start = time.perf_counter()
            time.sleep(expo_time)
            c_after = count_task.read()
            elapsed = time.perf_counter() - t_start
            cps = (c_after - c_before) / elapsed
            if cps > max_count:
                max_count, best_x, best_y = cps, sx, sy

        offset_x_v = best_x - ref_x_v
        offset_y_v = best_y - ref_y_v
        return offset_x_v, offset_y_v

    def perform_mapping(self, resume=False):
        # 1. 파라미터 및 초기화
        x_voltages = np.linspace(self.x_min, self.x_max, self.x_steps)
        y_voltages = np.linspace(self.y_min, self.y_max, self.y_steps)

        if not resume:
            self.pl_data_grid = np.full((self.y_steps, self.x_steps), np.nan)
            self.pl_data_list = [[xv * UNIT_CONVERSION_FACTOR, yv * UNIT_CONVERSION_FACTOR, np.nan] for yv in y_voltages for xv in x_voltages]

        # Drift 보정 초기화
        drift_enabled = self.gui.drift_correction_enabled.get()
        drift_offset_x_v, drift_offset_y_v = 0.0, 0.0
        if drift_enabled:
            try:
                drift_interval = max(1, int(self.gui.drift_interval_var.get()))
            except ValueError:
                drift_interval = DRIFT_CORRECTION_INTERVAL
            drift_ref_x_v = self.um_to_v(float(self.gui.drift_ref_x_var.get()))
            drift_ref_y_v = self.um_to_v(float(self.gui.drift_ref_y_var.get()))
        last_corrected_row = -1

        self.gui.update_boundaries(self.v_to_um(self.x_min), self.v_to_um(self.x_max), self.x_steps, self.v_to_um(self.y_min), self.v_to_um(self.y_max), self.y_steps)

        # Snake scan 인덱스 생성: 짝수행 좌→우, 홀수행 우→좌
        if resume:
            nan_set = set(map(tuple, np.argwhere(np.isnan(self.pl_data_grid))))
            all_snake = []
            for j in range(self.y_steps):
                if j % 2 == 0:
                    all_snake.extend([(j, i) for i in range(self.x_steps)])
                else:
                    all_snake.extend([(j, i) for i in range(self.x_steps - 1, -1, -1)])
            indices_list = [idx for idx in all_snake if idx in nan_set]
        else:
            indices_list = []
            for j in range(self.y_steps):
                if j % 2 == 0:
                    indices_list.extend([(j, i) for i in range(self.x_steps)])
                else:
                    indices_list.extend([(j, i) for i in range(self.x_steps - 1, -1, -1)])
        total_to_scan = len(indices_list)
        _last_plot_time = 0.0   # discrete scan plot 업데이트 throttle (150 ms)

        # 2. 메인 측정 루프 (전체를 try...finally로 감싸기)
        try:
            with nidaqmx.Task() as ao_task, nidaqmx.Task() as count_task:
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)
                count_task.ci_channels.add_ci_count_edges_chan(counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING).ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()
                
                for idx, (j, i) in enumerate(indices_list):
                    if not self.scanning: break

                    actual_expo = float(self.gui.exposure_time_var.get())
                    try:
                        settling = float(self.gui.settling_time_var.get())
                    except ValueError:
                        settling = GALVO_SETTLING_TIME
                    try:
                        avg_n = max(1, int(self.gui.averaging_count_var.get()))
                    except ValueError:
                        avg_n = AVERAGING_COUNT
                    remaining_count = total_to_scan - idx
                    remaining_sec = remaining_count * (actual_expo * avg_n + settling + 0.05)

                    self.gui.root.after(0, lambda t=remaining_sec:
                        self.gui.update_status_right("scan_remaining", t))

                    # Drift 보정: N행마다 기준점 재측정
                    if drift_enabled and j != last_corrected_row and j > 0 and j % drift_interval == 0:
                        last_corrected_row = j
                        drift_offset_x_v, drift_offset_y_v = self.measure_drift_offset(
                            ao_task, count_task, drift_ref_x_v + drift_offset_x_v, drift_ref_y_v + drift_offset_y_v, settling, actual_expo)
                        self.gui.root.after(0, lambda dx=self.v_to_um(drift_offset_x_v), dy=self.v_to_um(drift_offset_y_v):
                            self.gui.info_label.config(text=f"Drift corrected: dx={dx:.3f}μm, dy={dy:.3f}μm"))

                    # Galvo 이동 (drift offset 반영) → settling 대기 → N회 측정 평균
                    curr_x_um, curr_y_um = x_voltages[i] * UNIT_CONVERSION_FACTOR, y_voltages[j] * UNIT_CONVERSION_FACTOR
                    ao_task.write([x_voltages[i] + drift_offset_x_v, y_voltages[j] + drift_offset_y_v], auto_start=True)
                    time.sleep(settling)  # Galvo 안정화 대기

                    measurements = []
                    for _ in range(avg_n):
                        c_before = count_task.read()
                        t_start = time.perf_counter()
                        time.sleep(actual_expo)
                        c_after = count_task.read()
                        elapsed = time.perf_counter() - t_start
                        measurements.append((c_after - c_before) / elapsed)
                    photon_count = np.mean(measurements)

                    # 데이터 저장 및 GUI 업데이트
                    self.pl_data_grid[j, i] = photon_count
                    self.pl_data_list[j * self.x_steps + i][2] = photon_count
                    
                    # 텍스트 + 플롯 업데이트 (플롯은 150ms throttle — Triangle scan과 동일)
                    _now = time.time()
                    if _now - _last_plot_time >= 0.15:
                        _last_plot_time = _now
                        self.gui.root.after(0, lambda c=photon_count, x=curr_x_um, y=curr_y_um: (
                            self.gui.info_label.config(text=f"({x:.2f} μm, {y:.2f} μm)\n{c:.2e}")
                        ))
                        self.gui.root.after(0, self.gui.update_pl_plot, self.pl_data_grid,
                                           self.v_to_um(self.x_min), self.v_to_um(self.x_max),
                                           self.v_to_um(self.y_min), self.v_to_um(self.y_max))
                    else:
                        self.gui.root.after(0, lambda c=photon_count, x=curr_x_um, y=curr_y_um:
                            self.gui.info_label.config(text=f"({x:.2f} μm, {y:.2f} μm)\n{c:.2e}")
                        )
        
        except Exception as e:
            print(f"Error during mapping: {e}")
            
        finally:
            # 3. 종료 처리 (스캔 중단/완료 시 항상 실행)
            self.set_zero_position()
            if self.scanning: 
                self.gui.save_pl_data_as_txt(AUTO_SAVE_PATH, f"PL_Scan_data_{datetime.now().strftime('%y%m%d_%H%M%S')}.txt")
            self.scanning = False

            self.gui.root.after(0, lambda: [
                self.gui.state_management("default"),
                self.gui.update_galvo_indicator(),  # 좌표와 크기 갱신
                # 현재 데이터를 유지한 채 플롯을 다시 그려 인디케이터 가시성 확보
                self.gui.update_pl_plot(self.pl_data_grid)
            ])

# ------------------------------------------- Continuous Scan (Triangle) -----------------------------------------------

    def start_scan_triangle(self):
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — scan skipped.")
            return
        with self._state_lock:
            if self.scanning: return
            self.scanning = True
        def scan_thread():
            try:
                if self.set_scan_parameters():
                    self.pl_data_grid, self.pl_data_list = None, []
                    self.perform_mapping_triangle()
            finally:
                self.scanning = False
                self.gui.scan_button.config(text="Scan Start")
                self.gui.count_button.config(state=tk.NORMAL)
        threading.Thread(target=scan_thread, daemon=True).start()

    def perform_mapping_triangle(self):
        x_voltages = np.linspace(self.x_min, self.x_max, self.x_steps)
        y_voltages = np.linspace(self.y_min, self.y_max, self.y_steps)

        self.pl_data_grid = np.full((self.y_steps, self.x_steps), np.nan)
        self.pl_data_list = [[xv * UNIT_CONVERSION_FACTOR, yv * UNIT_CONVERSION_FACTOR, np.nan]
                             for yv in y_voltages for xv in x_voltages]
        self.gui.update_boundaries(self.v_to_um(self.x_min), self.v_to_um(self.x_max),
                                   self.x_steps, self.v_to_um(self.y_min),
                                   self.v_to_um(self.y_max), self.y_steps)

        pixel_dwell = float(self.gui.exposure_time_var.get())
        try:
            ao_sample_rate = max(20000, int(float(self.gui.ao_sample_rate_var.get())))
        except Exception:
            ao_sample_rate = 50000
        samples_per_pixel = max(int(pixel_dwell * ao_sample_rate), 2)  # 최소 pixel당 2 sample
        samples_per_row = samples_per_pixel * self.x_steps
        row_timeout = pixel_dwell * self.x_steps * 2 + 5.0
        # Settle pixel: ci_task.start() → ao_task.start() 사이의 Python overhead 동안
        # CI 카운터가 미리 누적한 광자를 흡수하기 위한 더미 픽셀.
        # overhead ~수 ms에서 단파장 고계수 샘플(~2만 cps)이면 수십~수백 count가 첫 픽셀에
        # 귀속되어 홀수행 우측(또는 짝수행 좌측) 픽셀이 밝아지는 artifact 발생.
        # galvo는 scan 시작 위치에 정지시켜 두므로 공간적 왜곡은 없다.
        n_settle = samples_per_pixel  # 1픽셀 분량
        total_samples = samples_per_row + n_settle

        scan_start_time = time.time()   # 예상 시간 계산용
        completed_rows = 0

        try:
            with nidaqmx.Task() as ao_task, nidaqmx.Task() as ci_task:
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)
                ci_task.ci_channels.add_ci_count_edges_chan(
                    counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING
                ).ci_count_edges_term = "/Dev2/PFI0"

                for j in range(self.y_steps):
                    if not self.scanning:
                        break

                    y_v = y_voltages[j]

                    # Triangle 파형 생성: 짝수행 좌→우, 홀수행 우→좌
                    # settle 구간(n_settle samples): galvo를 scan 시작 위치에 정지시켜
                    # ci_task.start() 직후 누적된 transient 카운트를 흡수한다.
                    if j % 2 == 0:
                        settle_x = np.full(n_settle, self.x_min)
                        scan_x   = np.linspace(self.x_min, self.x_max, samples_per_row)
                    else:
                        settle_x = np.full(n_settle, self.x_max)
                        scan_x   = np.linspace(self.x_max, self.x_min, samples_per_row)
                    x_waveform = np.concatenate([settle_x, scan_x])
                    y_waveform = np.full(total_samples, y_v)

                    # AO: 하드웨어 클록으로 galvo 파형 출력
                    ao_task.timing.cfg_samp_clk_timing(
                        rate=ao_sample_rate,
                        sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                        samps_per_chan=total_samples
                    )
                    ao_task.write(np.array([x_waveform, y_waveform]), auto_start=False)

                    # CI: AO SampleClock에 동기화 → galvo 위치와 광자 수집 타이밍 일치
                    ci_task.timing.cfg_samp_clk_timing(
                        rate=ao_sample_rate,
                        source="/Dev2/ao/SampleClock",
                        sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                        samps_per_chan=total_samples
                    )

                    # 남은 시간 계산: 실제 경과 시간 기반 rolling average
                    if completed_rows > 0:
                        elapsed = time.time() - scan_start_time
                        avg_row_sec = elapsed / completed_rows
                        remaining_sec = avg_row_sec * (self.y_steps - j)
                    else:
                        remaining_sec = pixel_dwell * self.x_steps * (self.y_steps - j)
                    self.gui.root.after(0, lambda t=remaining_sec:
                        self.gui.update_status_right("scan_remaining", t))

                    # CI 먼저 시작(AO 클록 대기 상태) → AO 시작 → 두 태스크 하드웨어 동기
                    ci_task.start()
                    ao_task.start()

                    # settle 픽셀 읽기: transient 카운트 흡수 후 prev_cum 기준값 설정
                    settle_data = np.array(ci_task.read(
                        number_of_samples_per_channel=n_settle,
                        timeout=pixel_dwell * 3 + 1.0
                    ))
                    prev_cum = settle_data[-1]

                    # 픽셀별 samples_per_pixel 씩 읽어 데이터 수집
                    # → stop 감지 시 즉시 중단 (galvo는 마지막 전압 유지, 안전에 문제 없음)
                    pixel_counts = np.zeros(self.x_steps)
                    aborted = False
                    last_plot_time = 0.0   # 100ms throttle: GUI 렌더링 빈도 제한
                    for px in range(self.x_steps):
                        if not self.scanning:
                            aborted = True
                            break
                        partial = np.array(ci_task.read(
                            number_of_samples_per_channel=samples_per_pixel,
                            timeout=pixel_dwell * 3 + 1.0
                        ))
                        photons = np.diff(np.concatenate([[prev_cum], partial]))
                        pixel_count = float(photons.sum()) / pixel_dwell
                        prev_cum = partial[-1]

                        # 짝수행 좌→우, 홀수행 우→좌
                        i = px if j % 2 == 0 else self.x_steps - 1 - px
                        pixel_counts[i] = pixel_count
                        self.pl_data_grid[j, i] = pixel_count
                        self.pl_data_list[j * self.x_steps + i][2] = pixel_count

                        # 100ms마다 한 번만 plot 업데이트 → 실시간 진행 표시 + 끊김 방지
                        now = time.time()
                        if now - last_plot_time >= 0.1:
                            self.gui.root.after(0, self.gui.update_pl_plot, self.pl_data_grid,
                                               self.v_to_um(self.x_min), self.v_to_um(self.x_max),
                                               self.v_to_um(self.y_min), self.v_to_um(self.y_max))
                            last_plot_time = now

                    ao_task.stop()
                    ci_task.stop()

                    if aborted:
                        break

                    # 행 완료 시 최종 1회 업데이트 (마지막 픽셀이 throttle에 걸릴 경우 보장)
                    self.gui.root.after(0, self.gui.update_pl_plot, self.pl_data_grid,
                                       self.v_to_um(self.x_min), self.v_to_um(self.x_max),
                                       self.v_to_um(self.y_min), self.v_to_um(self.y_max))

                    completed_rows += 1
                    curr_y_um = y_v * UNIT_CONVERSION_FACTOR
                    self.gui.root.after(0, lambda c=np.nanmean(pixel_counts), y=curr_y_um:
                        self.gui.info_label.config(text=f"Row y={y:.2f}μm avg={c:.2e}"))

        except Exception as e:
            print(f"Error during triangle scan: {e}")

        finally:
            self.set_zero_position()
            if self.scanning:
                self.gui.save_pl_data_as_txt(AUTO_SAVE_PATH,
                    f"PL_Triangle_{datetime.now().strftime('%y%m%d_%H%M%S')}.txt")
            self.scanning = False
            self.gui.root.after(0, lambda: [
                self.gui.state_management("default"),
                self.gui.update_galvo_indicator(),
                self.gui.update_pl_plot(self.pl_data_grid)
            ])

# ------------------------------------------- Continuous Scan (Sine) -----------------------------------------------

    def start_scan_sine(self):
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — scan skipped.")
            return
        with self._state_lock:
            if self.scanning: return
            self.scanning = True
        def scan_thread():
            try:
                if self.set_scan_parameters():
                    self.pl_data_grid, self.pl_data_list = None, []
                    self.perform_mapping_sine()
            finally:
                self.scanning = False
                self.gui.scan_button.config(text="Scan Start")
                self.gui.count_button.config(state=tk.NORMAL)
        threading.Thread(target=scan_thread, daemon=True).start()

    def desinusoid(self, raw_pixel_counts, x_steps):
        """
        Sine 파형에서 측정한 비균일 pixel 데이터를 균일 공간 grid로 재매핑.
        raw_pixel_counts: 등시간 bin으로 측정된 count 배열 (len = x_steps)
        반환: 균일 공간 간격으로 보간된 count 배열 (len = x_steps)
        """
        n = len(raw_pixel_counts)
        # 등시간 bin 중심의 시간 위치 (0~1 정규화)
        t_centers = (np.arange(n) + 0.5) / n
        # Sine 파형에서 각 bin 중심의 실제 공간 위치 (0~1 정규화)
        x_positions = 0.5 * (1 - np.cos(np.pi * t_centers))

        # 균일 공간 grid (0~1 정규화)
        x_uniform = np.linspace(0, 1, x_steps)
        # 보간
        corrected = np.interp(x_uniform, x_positions, raw_pixel_counts)
        return corrected

    def perform_mapping_sine(self):
        x_voltages = np.linspace(self.x_min, self.x_max, self.x_steps)
        y_voltages = np.linspace(self.y_min, self.y_max, self.y_steps)

        self.pl_data_grid = np.full((self.y_steps, self.x_steps), np.nan)
        self.pl_data_list = [[xv * UNIT_CONVERSION_FACTOR, yv * UNIT_CONVERSION_FACTOR, np.nan]
                             for yv in y_voltages for xv in x_voltages]
        self.gui.update_boundaries(self.v_to_um(self.x_min), self.v_to_um(self.x_max),
                                   self.x_steps, self.v_to_um(self.y_min),
                                   self.v_to_um(self.y_max), self.y_steps)

        pixel_dwell = float(self.gui.exposure_time_var.get())
        try:
            ao_sample_rate = max(20000, int(float(self.gui.ao_sample_rate_var.get())))
        except Exception:
            ao_sample_rate = 50000
        samples_per_row = int(pixel_dwell * self.x_steps * ao_sample_rate)
        samples_per_row = max(samples_per_row, self.x_steps * 2)

        x_center = (self.x_min + self.x_max) / 2
        x_amplitude = (self.x_max - self.x_min) / 2

        # Windows 고해상도 타이머 활성화 (time.sleep 해상도 ~1ms, 기본값 ~15ms)
        ctypes.windll.winmm.timeBeginPeriod(1)

        try:
            with nidaqmx.Task() as ao_task, nidaqmx.Task() as count_task:
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)
                count_task.ci_channels.add_ci_count_edges_chan(
                    counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING
                ).ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()

                for j in range(self.y_steps):
                    if not self.scanning:
                        break

                    y_v = y_voltages[j]
                    t_norm = np.linspace(0, 1, samples_per_row)

                    # Sine 파형 생성: x(t) = center + A * sin(π*t - π/2)
                    # 짝수행: x_min → x_max (forward half)
                    # 홀수행: x_max → x_min (backward half)
                    if j % 2 == 0:
                        x_waveform = x_center - x_amplitude * np.cos(np.pi * t_norm)
                    else:
                        x_waveform = x_center + x_amplitude * np.cos(np.pi * t_norm)
                    y_waveform = np.full(samples_per_row, y_v)

                    ao_task.timing.cfg_samp_clk_timing(
                        rate=ao_sample_rate,
                        sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                        samps_per_chan=samples_per_row
                    )
                    ao_task.write(np.array([x_waveform, y_waveform]), auto_start=False)

                    remaining_rows = self.y_steps - j
                    remaining_sec = remaining_rows * pixel_dwell * self.x_steps
                    self.gui.root.after(0, lambda t=remaining_sec:
                        self.gui.update_status_right("scan_remaining", t))

                    # AO 시작 + pixel별 counter 읽기 (등시간 bin)
                    c_prev = count_task.read()
                    ao_task.start()

                    raw_pixel_counts = np.zeros(self.x_steps)
                    last_plot_time = 0.0   # 100ms throttle: GUI 렌더링 빈도 제한
                    for px in range(self.x_steps):
                        t_start = time.perf_counter()
                        time.sleep(pixel_dwell)
                        c_now = count_task.read()
                        elapsed = time.perf_counter() - t_start
                        raw_pixel_counts[px] = (c_now - c_prev) / elapsed
                        c_prev = c_now

                        # 실시간 픽셀 표시 (desinusoid 전 원시 위치, 행 완료 후 보정됨)
                        i_raw = px if j % 2 == 0 else self.x_steps - 1 - px
                        self.pl_data_grid[j, i_raw] = raw_pixel_counts[px]
                        # 100ms마다 한 번만 plot 업데이트 → 실시간 진행 표시 + 끊김 방지
                        now = time.time()
                        if now - last_plot_time >= 0.1:
                            self.gui.root.after(0, self.gui.update_pl_plot, self.pl_data_grid,
                                               self.v_to_um(self.x_min), self.v_to_um(self.x_max),
                                               self.v_to_um(self.y_min), self.v_to_um(self.y_max))
                            last_plot_time = now

                        if px % 10 == 0:
                            rem = (self.y_steps - j - 1) * pixel_dwell * self.x_steps \
                                + (self.x_steps - px) * pixel_dwell
                            self.gui.root.after(0, lambda t=rem:
                                self.gui.update_status_right("scan_remaining", t))

                    ao_task.wait_until_done(timeout=10)
                    ao_task.stop()

                    # 홀수행 데이터 역순 정렬
                    if j % 2 == 1:
                        raw_pixel_counts = raw_pixel_counts[::-1]

                    # Desinusoiding: 등시간 bin → 균일 공간 grid로 보간
                    pixel_counts = self.desinusoid(raw_pixel_counts, self.x_steps)

                    # Bidirectional pixel shift 보정: 홀수행을 N 픽셀만큼 시프트
                    if j % 2 == 1:
                        try:
                            shift = int(self.gui.bidir_shift_var.get())
                        except (ValueError, AttributeError):
                            shift = 0
                        if shift != 0:
                            pixel_counts = np.roll(pixel_counts, shift)
                            if shift > 0:
                                pixel_counts[:shift] = pixel_counts[shift]
                            else:
                                pixel_counts[shift:] = pixel_counts[shift - 1]

                    # 데이터 저장 및 GUI 업데이트
                    self.pl_data_grid[j, :] = pixel_counts
                    for i in range(self.x_steps):
                        self.pl_data_list[j * self.x_steps + i][2] = pixel_counts[i]

                    curr_y_um = y_v * UNIT_CONVERSION_FACTOR
                    self.gui.root.after(0, lambda c=np.mean(pixel_counts), y=curr_y_um:
                        self.gui.info_label.config(text=f"Row y={y:.2f}μm avg={c:.2e}"))
                    self.gui.root.after(0, self.gui.update_pl_plot, self.pl_data_grid,
                                       self.v_to_um(self.x_min), self.v_to_um(self.x_max),
                                       self.v_to_um(self.y_min), self.v_to_um(self.y_max))

        except Exception as e:
            print(f"Error during sine scan: {e}")

        finally:
            ctypes.windll.winmm.timeEndPeriod(1)  # 타이머 해상도 복원
            self.set_zero_position()
            if self.scanning:
                self.gui.save_pl_data_as_txt(AUTO_SAVE_PATH,
                    f"PL_Sine_{datetime.now().strftime('%y%m%d_%H%M%S')}.txt")
            self.scanning = False
            self.gui.root.after(0, lambda: [
                self.gui.state_management("default"),
                self.gui.update_galvo_indicator(),
                self.gui.update_pl_plot(self.pl_data_grid)
            ])

# ------------------------------------------- Auto-Focus -----------------------------------------------

    def start_auto_focus(self):
        """Auto-Focus를 백그라운드 스레드에서 실행"""
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — auto-focus skipped.")
            return
        self.af_running = True
        threading.Thread(target=self._perform_auto_focus, daemon=True).start()

    def stop_auto_focus(self):
        self.af_running = False

    def _z_scan_line(self, z_positions, count_task, expo_time):
        """Z 위치 배열을 순회하며 각 위치에서 APD count를 측정.
        Returns: list of (z_um, photon_count_per_sec)
        """
        piezo = self.gui.piezo
        data = []
        for i, z in enumerate(z_positions):
            if not self.af_running:
                break
            piezo.move_to(z)
            piezo.wait_on_target(timeout=3.0)

            # APD 측정 (perf_counter로 실측 시간 정규화)
            c_before = count_task.read()
            t_start = time.perf_counter()
            time.sleep(expo_time)
            c_after = count_task.read()
            elapsed = time.perf_counter() - t_start
            cps = (c_after - c_before) / elapsed

            data.append((z, cps))

            # GUI 업데이트: info_label + 진행률
            total = len(z_positions)
            self.gui.root.after(0, lambda z_=z, c=cps, idx=i, tot=total:
                self.gui.info_label.config(
                    text=f"Auto-Focus [{idx+1}/{tot}] Z={z_:.1f}μm  PL={c:.2e}"))
        return data
    def _perform_auto_focus(self):
        """2-Pass Auto-Focus: Coarse → Fine (z_autofocus.py 연동)"""
        piezo = self.gui.piezo

        if not piezo.is_connected():
            self.gui.root.after(0, lambda:
                self.gui.info_label.config(text="Auto-Focus: Piezo not connected"))
            self.af_running = False
            return

        # 1. 파라미터 읽기 (GUI에 추가한 모드 변수들 포함)
        try:
            z_min = float(self.gui.af_z_min_var.get())
            z_max = float(self.gui.af_z_max_var.get())
            coarse_step = float(self.gui.af_coarse_step_var.get())
            fine_range = float(self.gui.af_fine_range_var.get())
            fine_step = float(self.gui.af_fine_step_var.get())
            expo_time = float(self.gui.exposure_time_var.get())

            # z_autofocus용 신규 파라미터
            focus_mode = self.gui.af_mode_var.get()
            threshold_pct = float(self.gui.af_threshold_pct_var.get())
            edge_pct = float(self.gui.af_edge_pct_var.get())
            slope_side = self.gui.af_slope_side_var.get()
            edge_method = self.gui.af_edge_method_var.get()
        except ValueError:
            self.gui.root.after(0, lambda:
                self.gui.info_label.config(text="Auto-Focus: Invalid parameters"))
            self.af_running = False
            return

        original_z = piezo.get_position()

        try:
            with nidaqmx.Task() as count_task:
                count_task.ci_channels.add_ci_count_edges_chan(
                    counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING
                ).ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()

                # === Pass 1: Coarse Scan ===
                coarse_z = np.arange(z_min, z_max + coarse_step / 2, coarse_step)
                pos_min, pos_max = piezo.get_travel_range()
                coarse_z = coarse_z[(coarse_z >= pos_min) & (coarse_z <= pos_max)]

                self.gui.root.after(0, lambda:
                    self.gui.info_label.config(text=f"Auto-Focus: Coarse scan ({len(coarse_z)} points)..."))

                coarse_data = self._z_scan_line(coarse_z, count_task, expo_time)
                if not self.af_running or not coarse_data: return

                best_z_coarse = max(coarse_data, key=lambda x: x[1])[0]
                self.gui.root.after(0, lambda d=list(coarse_data), bz=best_z_coarse:
                    self.gui.update_af_plot(d, bz, "Coarse"))

                # === Pass 2: Fine Scan ===
                # 모드에 따라 비대칭 탐색 범위 적용 (z_autofocus 로직 반영)
                if focus_mode in ("max_slope", "rising_edge"):
                    fine_min = max(pos_min, best_z_coarse - fine_range * 2.0)
                    fine_max = min(pos_max, best_z_coarse + fine_range * 0.5)
                else:
                    fine_min = max(pos_min, best_z_coarse - fine_range)
                    fine_max = min(pos_max, best_z_coarse + fine_range)

                fine_z = np.arange(fine_min, fine_max + fine_step / 2, fine_step)

                self.gui.root.after(0, lambda:
                    self.gui.info_label.config(text=f"Auto-Focus: Fine scan ({len(fine_z)} points)..."))

                fine_data = self._z_scan_line(fine_z, count_task, expo_time)
                if not self.af_running or not fine_data: return

                # === Pass 3: z_autofocus.py 분석 로직 개입 ===
                result = find_focus_target(
                    fine_data,
                    focus_mode=focus_mode,
                    threshold_pct=threshold_pct,
                    edge_pct=edge_pct,
                    rising_edge_method=edge_method,
                    side=slope_side
                )

                best_z_final = result["center_z"]
                best_cps = result["max_cps"]

                piezo.move_to(best_z_final)
                piezo.wait_on_target(timeout=3.0)
                actual = piezo.get_position()

                self.gui.root.after(0, lambda fd=list(fine_data), bz=best_z_final, bc=best_cps, az=actual:
                    [self.gui.update_af_plot(fd, bz, f"Fine ({focus_mode})"),
                     self.gui.piezo_z_var.set(f"{az:.3f}"),
                     self.gui.info_label.config(
                        text=f"AF Done: Z={az:.3f}μm, PL={bc:.2e}")])

        except Exception as e:
            print(f"Auto-Focus error: {e}")
            try: piezo.move_to(original_z)
            except: pass
            self.gui.root.after(0, lambda err=str(e):
                self.gui.info_label.config(text=f"Auto-Focus error: {err}"))

        finally:
            self.af_running = False
            self.gui.root.after(0, lambda: self.gui.state_management("default"))
    # def _perform_auto_focus(self):
    #     """2-Pass Auto-Focus: Coarse → Fine"""
    #     piezo = self.gui.piezo

    #     if not piezo.is_connected():
    #         self.gui.root.after(0, lambda:
    #             self.gui.info_label.config(text="Auto-Focus: Piezo not connected"))
    #         self.af_running = False
    #         return

    #     # 파라미터 읽기
    #     try:
    #         z_min = float(self.gui.af_z_min_var.get())
    #         z_max = float(self.gui.af_z_max_var.get())
    #         coarse_step = float(self.gui.af_coarse_step_var.get())
    #         fine_range = float(self.gui.af_fine_range_var.get())
    #         fine_step = float(self.gui.af_fine_step_var.get())
    #         expo_time = float(self.gui.exposure_time_var.get())
    #     except ValueError:
    #         self.gui.root.after(0, lambda:
    #             self.gui.info_label.config(text="Auto-Focus: Invalid parameters"))
    #         self.af_running = False
    #         return

    #     # 현재 Z 위치 기억 (실패 시 복귀용)
    #     original_z = piezo.get_position()

    #     try:
    #         with nidaqmx.Task() as count_task:
    #             count_task.ci_channels.add_ci_count_edges_chan(
    #                 counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING
    #             ).ci_count_edges_term = "/Dev2/PFI0"
    #             count_task.start()

    #             # === Pass 1: Coarse Scan ===
    #             coarse_z = np.arange(z_min, z_max + coarse_step / 2, coarse_step)
    #             pos_min, pos_max = piezo.get_travel_range()
    #             coarse_z = coarse_z[(coarse_z >= pos_min) & (coarse_z <= pos_max)]

    #             self.gui.root.after(0, lambda:
    #                 self.gui.info_label.config(text=f"Auto-Focus: Coarse scan ({len(coarse_z)} points)..."))

    #             coarse_data = self._z_scan_line(coarse_z, count_task, expo_time)

    #             if not self.af_running or not coarse_data:
    #                 return

    #             # Coarse 최대값 찾기
    #             best_z_coarse = max(coarse_data, key=lambda x: x[1])[0]

    #             # GUI에 coarse 결과 표시
    #             self.gui.root.after(0, lambda d=list(coarse_data), bz=best_z_coarse:
    #                 self.gui.update_af_plot(d, bz, "Coarse"))

    #             # === Pass 2: Fine Scan ===
    #             fine_min = max(pos_min, best_z_coarse - fine_range)
    #             fine_max = min(pos_max, best_z_coarse + fine_range)
    #             fine_z = np.arange(fine_min, fine_max + fine_step / 2, fine_step)

    #             self.gui.root.after(0, lambda:
    #                 self.gui.info_label.config(text=f"Auto-Focus: Fine scan ({len(fine_z)} points)..."))

    #             fine_data = self._z_scan_line(fine_z, count_task, expo_time)

    #             if not self.af_running or not fine_data:
    #                 return

    #             # Fine 최대값 → 최종 위치로 이동
    #             best_z_final = max(fine_data, key=lambda x: x[1])[0]
    #             best_cps = max(fine_data, key=lambda x: x[1])[1]

    #             piezo.move_to(best_z_final)
    #             piezo.wait_on_target(timeout=3.0)
    #             actual = piezo.get_position()

    #             # GUI에 최종 결과 표시
    #             self.gui.root.after(0, lambda fd=list(fine_data), bz=best_z_final, bc=best_cps, az=actual:
    #                 [self.gui.update_af_plot(fd, bz, "Fine"),
    #                  self.gui.piezo_z_var.set(f"{az:.3f}"),
    #                  self.gui.info_label.config(
    #                     text=f"Auto-Focus complete: Z={az:.3f}μm, PL={bc:.2e}")])

    #     except Exception as e:
    #         print(f"Auto-Focus error: {e}")
    #         try:
    #             piezo.move_to(original_z)
    #         except Exception:
    #             pass
    #         self.gui.root.after(0, lambda err=str(e):
    #             self.gui.info_label.config(text=f"Auto-Focus error: {err}"))

    #     finally:
    #         self.af_running = False
    #         self.gui.root.after(0, lambda:
    #             self.gui.state_management("default"))

# ------------------------------------------- Phase 3: XZ/YZ Cross-Section + 3D Stack -----------------------------------------------

    def _set_z_scan_parameters(self):
        """Z 스캔 파라미터 (z_scan_min, z_scan_max, z_steps)를 GUI에서 읽어 설정."""
        try:
            self.z_scan_min = float(self.gui.z_scan_min_var.get())
            self.z_scan_max = float(self.gui.z_scan_max_var.get())
            self.z_steps = int(self.gui.z_steps_var.get())
            return True
        except ValueError as e:
            print(f"Error: Invalid Z scan parameter - {e}")
            return False

    def start_scan_xz(self):
        """XZ cross-section 스캔 시작 (Y 고정, X + Z 스캔)"""
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — scan skipped.")
            return
        with self._state_lock:
            if self.scanning: return
            self.scanning = True
        def scan_thread():
            try:
                if self.set_scan_parameters() and self._set_z_scan_parameters():
                    self.pl_data_grid, self.pl_data_list = None, []
                    self._perform_mapping_cross_section('x')
            finally:
                self.scanning = False
                self.gui.root.after(0, lambda: [
                    self.gui.scan_button.config(text="Scan Start"),
                    self.gui.count_button.config(state=tk.NORMAL)
                ])
        threading.Thread(target=scan_thread, daemon=True).start()

    def start_scan_yz(self):
        """YZ cross-section 스캔 시작 (X 고정, Y + Z 스캔)"""
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — scan skipped.")
            return
        with self._state_lock:
            if self.scanning: return
            self.scanning = True
        def scan_thread():
            try:
                if self.set_scan_parameters() and self._set_z_scan_parameters():
                    self.pl_data_grid, self.pl_data_list = None, []
                    self._perform_mapping_cross_section('y')
            finally:
                self.scanning = False
                self.gui.root.after(0, lambda: [
                    self.gui.scan_button.config(text="Scan Start"),
                    self.gui.count_button.config(state=tk.NORMAL)
                ])
        threading.Thread(target=scan_thread, daemon=True).start()

    def start_scan_3d(self):
        """3D Stack 스캔 시작 (각 Z 평면에서 XY 스캔)"""
        if not self.daq_available:
            print("[DAQTasks] DAQ not available — scan skipped.")
            return
        with self._state_lock:
            if self.scanning: return
            self.scanning = True
        def scan_thread():
            try:
                if self.set_scan_parameters() and self._set_z_scan_parameters():
                    self.pl_data_grid, self.pl_data_list = None, []
                    self.pl_data_3d = None
                    self._perform_mapping_3d()
            finally:
                self.scanning = False
                self.gui.root.after(0, lambda: [
                    self.gui.scan_button.config(text="Scan Start"),
                    self.gui.count_button.config(state=tk.NORMAL)
                ])
        threading.Thread(target=scan_thread, daemon=True).start()

    def _perform_mapping_cross_section(self, axis):
        """
        XZ(axis='x') 또는 YZ(axis='y') cross-section 스캔.
        외부 루프: Z (피에조), 내부 루프: 측면축 (갈보 Discrete).
        결과: pl_data_grid (z_steps × lateral_steps)
        """
        piezo = self.gui.piezo
        if not piezo.is_connected():
            self.gui.root.after(0, lambda:
                self.gui.info_label.config(text=f"{axis.upper()}Z Scan: Piezo not connected"))
            return

        z_positions = np.linspace(self.z_scan_min, self.z_scan_max, self.z_steps)
        if axis == 'x':
            lateral_voltages = np.linspace(self.x_min, self.x_max, self.x_steps)
            lateral_steps = self.x_steps
            lateral_um_min = self.v_to_um(self.x_min)
            lateral_um_max = self.v_to_um(self.x_max)
            fixed_v = self.um_to_v(float(self.gui.galvo_y_var.get()))
        else:
            lateral_voltages = np.linspace(self.y_min, self.y_max, self.y_steps)
            lateral_steps = self.y_steps
            lateral_um_min = self.v_to_um(self.y_min)
            lateral_um_max = self.v_to_um(self.y_max)
            fixed_v = self.um_to_v(float(self.gui.galvo_x_var.get()))

        self.pl_data_grid = np.full((self.z_steps, lateral_steps), np.nan)
        expo = self.expo_time

        try:
            with nidaqmx.Task() as ao_task, nidaqmx.Task() as count_task:
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)
                count_task.ci_channels.add_ci_count_edges_chan(
                    counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING
                ).ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()

                for zi, z in enumerate(z_positions):
                    if not self.scanning:
                        break
                    piezo.move_to(z)
                    piezo.wait_on_target(timeout=PIEZO_SETTLING_TIMEOUT)

                    for li in range(lateral_steps):
                        if not self.scanning:
                            break
                        if axis == 'x':
                            ao_task.write([lateral_voltages[li], fixed_v], auto_start=True)
                        else:
                            ao_task.write([fixed_v, lateral_voltages[li]], auto_start=True)
                        time.sleep(GALVO_SETTLING_TIME)

                        c_before = count_task.read()
                        t_start = time.perf_counter()
                        time.sleep(expo)
                        c_after = count_task.read()
                        elapsed = time.perf_counter() - t_start
                        self.pl_data_grid[zi, li] = (c_after - c_before) / elapsed

                    # 행 완료 후 GUI 업데이트
                    grid_copy = self.pl_data_grid.copy()
                    remaining = (self.z_steps - zi - 1) * lateral_steps * (expo + GALVO_SETTLING_TIME)
                    self.gui.root.after(0, lambda g=grid_copy, ax=axis,
                                        lmin=lateral_um_min, lmax=lateral_um_max,
                                        zmin=self.z_scan_min, zmax=self.z_scan_max,
                                        z_=z, zi_=zi:
                        [self.gui.update_cross_section_plot(g, ax, lmin, lmax, zmin, zmax),
                         self.gui.info_label.config(text=f"{ax.upper()}Z scan  Z={z_:.1f}μm  [{zi_+1}/{self.z_steps}]")])
                    self.gui.root.after(0, lambda t=remaining:
                        self.gui.update_status_right("scan_remaining", t))

        except Exception as e:
            print(f"Cross-section scan error: {e}")

        finally:
            self.set_zero_position()
            # 자동 저장: 2D 그리드를 txt로 저장
            if self.scanning:
                save_path = os.path.join(AUTO_SAVE_PATH,
                    f"PL_{axis.upper()}Z_{datetime.now().strftime('%y%m%d_%H%M%S')}.txt")
                try:
                    header = (f"axis={axis}, lateral_min={lateral_um_min:.3f}um, "
                              f"lateral_max={lateral_um_max:.3f}um, lateral_steps={lateral_steps}, "
                              f"z_min={self.z_scan_min:.3f}um, z_max={self.z_scan_max:.3f}um, "
                              f"z_steps={self.z_steps}")
                    np.savetxt(save_path, self.pl_data_grid, header=header)
                except Exception:
                    pass
            self.scanning = False
            grid_final = self.pl_data_grid
            self.gui.root.after(0, lambda g=grid_final, ax=axis,
                                lmin=lateral_um_min, lmax=lateral_um_max,
                                zmin=self.z_scan_min, zmax=self.z_scan_max: [
                self.gui.state_management("default"),
                self.gui.update_cross_section_plot(g, ax, lmin, lmax, zmin, zmax)
            ])

    def _perform_mapping_3d(self):
        """
        3D Stack 스캔: 각 Z 평면에서 XY Discrete 스캔.
        결과: pl_data_3d (z_steps × y_steps × x_steps)
        """
        piezo = self.gui.piezo
        if not piezo.is_connected():
            self.gui.root.after(0, lambda:
                self.gui.info_label.config(text="3D Stack: Piezo not connected"))
            return

        z_positions = np.linspace(self.z_scan_min, self.z_scan_max, self.z_steps)
        x_voltages = np.linspace(self.x_min, self.x_max, self.x_steps)
        y_voltages = np.linspace(self.y_min, self.y_max, self.y_steps)
        expo = self.expo_time

        self.pl_data_3d = np.full((self.z_steps, self.y_steps, self.x_steps), np.nan)

        try:
            with nidaqmx.Task() as ao_task, nidaqmx.Task() as count_task:
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
                ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)
                count_task.ci_channels.add_ci_count_edges_chan(
                    counter="Dev2/ctr0", edge=nidaqmx.constants.Edge.RISING
                ).ci_count_edges_term = "/Dev2/PFI0"
                count_task.start()

                for zi, z in enumerate(z_positions):
                    if not self.scanning:
                        break
                    piezo.move_to(z)
                    piezo.wait_on_target(timeout=PIEZO_SETTLING_TIMEOUT)

                    slice_grid = np.full((self.y_steps, self.x_steps), np.nan)

                    for j, y_v in enumerate(y_voltages):
                        if not self.scanning:
                            break
                        for i, x_v in enumerate(x_voltages):
                            if not self.scanning:
                                break
                            ao_task.write([x_v, y_v], auto_start=True)
                            time.sleep(GALVO_SETTLING_TIME)

                            c_before = count_task.read()
                            t_start = time.perf_counter()
                            time.sleep(expo)
                            c_after = count_task.read()
                            elapsed = time.perf_counter() - t_start
                            slice_grid[j, i] = (c_after - c_before) / elapsed

                    self.pl_data_3d[zi] = slice_grid
                    self.pl_data_grid = slice_grid.copy()

                    remaining_pixels = ((self.z_steps - zi - 1) * self.y_steps * self.x_steps
                                        * (expo + GALVO_SETTLING_TIME))
                    self.gui.root.after(0, lambda zi_=zi, g=slice_grid.copy(), z_=z:
                        self.gui.update_3d_current_slice(zi_, g, z_))
                    self.gui.root.after(0, lambda t=remaining_pixels:
                        self.gui.update_status_right("scan_remaining", t))

        except Exception as e:
            print(f"3D stack scan error: {e}")

        finally:
            self.set_zero_position()
            # 자동 저장: npz
            if self.scanning and self.pl_data_3d is not None:
                save_path = os.path.join(AUTO_SAVE_PATH,
                    f"PL_3D_{datetime.now().strftime('%y%m%d_%H%M%S')}.npz")
                try:
                    np.savez(save_path, data=self.pl_data_3d,
                             x_min=self.v_to_um(self.x_min), x_max=self.v_to_um(self.x_max),
                             y_min=self.v_to_um(self.y_min), y_max=self.v_to_um(self.y_max),
                             z_min=self.z_scan_min, z_max=self.z_scan_max)
                except Exception:
                    pass
            self.scanning = False
            self.gui.root.after(0, lambda: self.gui.state_management("default"))