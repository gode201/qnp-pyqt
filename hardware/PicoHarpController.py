"""
PicoHarp 300 Python wrapper (phlib64.dll / ctypes)
- Histogram 모드: 실시간 히스토그램 취득
- T2 모드: time-tagged photon stream 취득 (.pt2 저장)
- 하드웨어 미연결 시 ph_available=False로 graceful fallback
"""

import ctypes
import os
import threading
import time
import numpy as np
from ptu_writer import write_ptu
from Default import (
    PICOHARP_DLL_PATH, PICOHARP_DEVICE_IDX,
    PH_HIST_ACQTIME_MS, PH_HIST_BINNING, PH_HIST_OFFSET_PS, PH_HIST_STOP_OVERFLOW,
    PH_SYNC_CFD_LEVEL_MV, PH_SYNC_CFD_ZERO_MV,
    PH_CHAN_CFD_LEVEL_MV, PH_CHAN_CFD_ZERO_MV, PH_SYNC_DIV,
    PH_T2_ACQTIME_S, PH_T2_SAVE_DIR,
)

# ── PHLib 상수 ────────────────────────────────────────────────────────────────
MODE_HIST   = 0
MODE_T2     = 2
HISTCHAN    = 65536       # 히스토그램 채널 수
TTREADMAX   = 131072      # FIFO 최대 읽기 레코드 수
FLAG_OVERFLOW = 0x0040
FLAG_FIFOFULL = 0x0003

# ── T2 레코드 파싱 ─────────────────────────────────────────────────────────────
T2WRAPAROUND = 210698240   # T2 타이머 wraparound 값
T2TIMEUNIT   = 4e-12       # 4 ps per tick


class PicoHarpController:
    """PicoHarp 300 제어 클래스.

    Attributes
    ----------
    ph_available : bool
        DLL 로드 및 장치 열기 성공 여부.
        False면 모든 메서드는 빈 값을 반환하고 예외를 발생시키지 않는다.
    """

    def __init__(self):
        self.ph_available = False
        self._dev = PICOHARP_DEVICE_IDX
        self._lib = None
        self._mode = MODE_HIST
        self._serial = ctypes.create_string_buffer(8)

        # 상태
        self.sync_rate   = 0
        self.count_rate  = 0
        self.resolution  = 0.0        # ps
        self.elapsed_ms  = 0.0
        self.histogram   = np.zeros(HISTCHAN, dtype=np.uint32)
        self._hist_buf   = (ctypes.c_uint * HISTCHAN)()

        # 측정 스레드
        self._meas_thread  = None
        self._stop_event   = threading.Event()
        self._measuring    = False

        # count rate 채널 인덱스 (connect() 후 _diag_count_rates()로 자동 결정)
        self._sync_rate_ch = 0   # Sync/CH0 에 해당하는 PH_GetCountRate 채널 인덱스
        self._chan_rate_ch = 1   # Input/CH1 에 해당하는 PH_GetCountRate 채널 인덱스

        # 마지막으로 적용된 CFD 파라미터 (PTU 헤더 기록용, 측정 시작 시 재적용)
        self._sync_cfd_level  = PH_SYNC_CFD_LEVEL_MV
        self._sync_cfd_zc     = PH_SYNC_CFD_ZERO_MV
        self._sync_div        = PH_SYNC_DIV
        self._chan_cfd_level   = PH_CHAN_CFD_LEVEL_MV
        self._chan_cfd_zc      = PH_CHAN_CFD_ZERO_MV
        self._sync_offset_ns   = 0   # Control Panel Sync Offset (ns)
        self._chan_offset_ns   = 0   # Control Panel Chan Offset (ns)

        # 콜백 (GUI에서 설정)
        self.on_histogram_update = None   # fn(histogram: np.ndarray, elapsed_ms: float)
        self.on_t2_progress      = None   # fn(elapsed_s: float, total_s: float, photons: int)
        self.on_measurement_done = None   # fn(mode: str)
        self.on_count_rate       = None   # fn(sync: int, chan: int)

        # T2 측정 완료 후 raw records (uint32 list) 보관 — g2 후처리용
        self.last_t2_records: list = []

        self._try_load()

    # ── DLL 로드 & 초기화 ──────────────────────────────────────────────────────

    def _try_load(self):
        if not os.path.exists(PICOHARP_DLL_PATH):
            print(f"[PicoHarp] DLL not found: {PICOHARP_DLL_PATH}")
            return
        try:
            self._lib = ctypes.windll.LoadLibrary(PICOHARP_DLL_PATH)
            self.ph_available = True
            print("[PicoHarp] DLL loaded OK")
        except Exception as e:
            print(f"[PicoHarp] DLL load failed: {e}")

    def connect(self) -> str:
        """장치를 열고 초기화한다. 성공 시 serial 문자열 반환, 실패 시 오류 문자열."""
        if not self.ph_available:
            return "DLL not available"
        try:
            ret = self._lib.PH_OpenDevice(self._dev, self._serial)
            if ret < 0:
                return self._get_error_string(ret)
            ret = self._lib.PH_Initialize(self._dev, ctypes.c_int(MODE_HIST))
            if ret < 0:
                return self._get_error_string(ret)
            self._lib.PH_Calibrate(self._dev)
            self._apply_cfd()
            self._fetch_resolution()
            # Sync rate API 버전 감지
            try:
                self._lib.PH_GetSyncRate
                self._sync_rate_api = "v2"
                self._sync_rate_ch  = -1   # v2.x: PH_GetSyncRate (별도 함수)
                print("[PicoHarp] Sync rate API: PH_GetSyncRate (v2.x)")
            except self._DLL_MISSING:
                self._sync_rate_api = "v3"
                # v3.x: ch=0 → Sync, ch=1 → Input Channel
                self._sync_rate_ch = 0
                self._chan_rate_ch  = 1
                print("[PicoHarp] Sync rate API: PH_GetCountRate ch=0/1 (v3.x)")
            self.ph_available = True
            serial = self._serial.value.decode(errors='replace')
            print(f"[PicoHarp] Connected — serial: {serial}")
            return f"OK ({serial})"
        except Exception as e:
            print(f"[PicoHarp] connect() exception: {e}")
            return f"Error: {e}"

    def disconnect(self):
        if not self.ph_available:
            return
        self.stop_measurement()
        self._lib.PH_CloseDevice(self._dev)
        print("[PicoHarp] Disconnected")

    # ── DLL 안전 호출 헬퍼 ────────────────────────────────────────────────────
    # Python 3.14: 없는 함수 → AttributeError  /  이전 버전: OSError
    _DLL_MISSING = (OSError, AttributeError)

    def _dll_call(self, name: str, *args, default=0):
        """DLL 함수를 안전하게 호출. 함수가 없으면 default 반환."""
        try:
            return getattr(self._lib, name)(*args)
        except self._DLL_MISSING:
            print(f"[PicoHarp] '{name}' not found in DLL — skipped")
            return default

    def _apply_cfd(self, sync_lvl=None, sync_zc=None, sync_div=None,
                   chan_lvl=None, chan_zc=None,
                   sync_offset_ns=None, chan_offset_ns=None):
        """CFD 설정을 장치에 적용하고 인스턴스 변수에 저장한다."""
        if sync_lvl        is not None: self._sync_cfd_level  = sync_lvl
        if sync_zc         is not None: self._sync_cfd_zc     = sync_zc
        if sync_div        is not None: self._sync_div         = sync_div
        if chan_lvl        is not None: self._chan_cfd_level   = chan_lvl
        if chan_zc         is not None: self._chan_cfd_zc      = chan_zc
        if sync_offset_ns  is not None: self._sync_offset_ns  = sync_offset_ns
        if chan_offset_ns   is not None: self._chan_offset_ns  = chan_offset_ns
        self._dll_call("PH_SetSyncDiv", self._dev, ctypes.c_int(self._sync_div))

        # ── CFD 설정 전략 ──────────────────────────────────────────────────────
        # 로그에서 확인된 DLL 특성 (phlib64 v3.x):
        #   PH_SetInputCFD(ch=0) → Sync 채널   (ch=0/1 이 GetCountRate와 동일 매핑)
        #   PH_SetInputCFD(ch=1) → Input CH1
        #   PH_SetInputCFD(ch=-1) → error -17 (invalid channel)
        #   PH_SetSyncCFD / PH_SetCFDLevel → DLL에 없음
        # 우선순위:
        #   1) PH_SetSyncCFD (일부 v3.x 빌드)
        #   2) PH_SetInputCFD(ch=0) for Sync, PH_SetInputCFD(ch=1) for CH1
        #   3) v2.x: PH_SetCFDLevel(ch=0/1)

        sync_cfd_ok = False
        chan_cfd_ok = False

        # ① PH_SetSyncCFD (Sync 전용, 일부 v3.x)
        try:
            ret = self._lib.PH_SetSyncCFD(self._dev,
                                          ctypes.c_int(self._sync_cfd_level),
                                          ctypes.c_int(self._sync_cfd_zc))
            if ret == 0:
                sync_cfd_ok = True
                print(f"[PicoHarp] Sync CFD ← PH_SetSyncCFD "
                      f"level={self._sync_cfd_level}mV zc={self._sync_cfd_zc}mV")
            else:
                print(f"[PicoHarp] PH_SetSyncCFD error {ret} — fallback")
        except self._DLL_MISSING:
            pass

        # ② PH_SetInputCFD: ch=0→Sync, ch=1→CH1 (v3.x GetCountRate와 동일 매핑)
        try:
            if not sync_cfd_ok:
                ret = self._lib.PH_SetInputCFD(self._dev, ctypes.c_int(0),
                                               ctypes.c_int(self._sync_cfd_level),
                                               ctypes.c_int(self._sync_cfd_zc))
                if ret == 0:
                    sync_cfd_ok = True
                    print(f"[PicoHarp] Sync CFD ← PH_SetInputCFD(ch=0) "
                          f"level={self._sync_cfd_level}mV zc={self._sync_cfd_zc}mV")
                else:
                    print(f"[PicoHarp] PH_SetInputCFD(ch=0/Sync) error {ret}")

            ret = self._lib.PH_SetInputCFD(self._dev, ctypes.c_int(1),
                                           ctypes.c_int(self._chan_cfd_level),
                                           ctypes.c_int(self._chan_cfd_zc))
            if ret == 0:
                chan_cfd_ok = True
                print(f"[PicoHarp] CH1  CFD ← PH_SetInputCFD(ch=1) "
                      f"level={self._chan_cfd_level}mV zc={self._chan_cfd_zc}mV")
            else:
                print(f"[PicoHarp] PH_SetInputCFD(ch=1/CH1) error {ret} — fallback")
        except self._DLL_MISSING:
            pass

        # ③ v2.x fallback: PH_SetCFDLevel(ch=0→Sync, ch=1→CH1)
        if not sync_cfd_ok:
            try:
                self._lib.PH_SetCFDLevel(self._dev, ctypes.c_int(0),
                                         ctypes.c_int(self._sync_cfd_level))
                self._lib.PH_SetCFDZeroCross(self._dev, ctypes.c_int(0),
                                              ctypes.c_int(self._sync_cfd_zc))
                sync_cfd_ok = True
                print(f"[PicoHarp] Sync CFD ← PH_SetCFDLevel(ch=0) "
                      f"level={self._sync_cfd_level}mV zc={self._sync_cfd_zc}mV")
            except self._DLL_MISSING:
                print("[PicoHarp] !! Sync CFD 설정 실패 — 모든 API 사용 불가. "
                      "PicoHarp SW에서 수동 설정 필요.")

        if not chan_cfd_ok:
            try:
                self._lib.PH_SetCFDLevel(self._dev, ctypes.c_int(1),
                                         ctypes.c_int(self._chan_cfd_level))
                self._lib.PH_SetCFDZeroCross(self._dev, ctypes.c_int(1),
                                              ctypes.c_int(self._chan_cfd_zc))
                chan_cfd_ok = True
                print(f"[PicoHarp] CH1  CFD ← PH_SetCFDLevel(ch=1) "
                      f"level={self._chan_cfd_level}mV zc={self._chan_cfd_zc}mV")
            except self._DLL_MISSING:
                print("[PicoHarp] !! CH1 CFD 설정 실패 — 모든 API 사용 불가.")
        # Sync / Chan Offset — phlib64 단위: ps (변수는 ns로 저장 → ×1000 변환)
        self._dll_call("PH_SetSyncOffset",  self._dev, ctypes.c_int(int(self._sync_offset_ns * 1000)))
        self._dll_call("PH_SetInputOffset", self._dev, ctypes.c_int(0),
                       ctypes.c_int(int(self._chan_offset_ns * 1000)))

    def _fetch_resolution(self):
        res = ctypes.c_double(0)
        try:
            self._lib.PH_GetResolution(self._dev, ctypes.byref(res))
            self.resolution = res.value
        except self._DLL_MISSING:
            self.resolution = 0.0

    def _get_error_string(self, errcode: int) -> str:
        buf = ctypes.create_string_buffer(40)
        try:
            self._lib.PH_GetErrorString(buf, ctypes.c_int(errcode))
            return buf.value.decode(errors='replace')
        except self._DLL_MISSING:
            return f"error code {errcode}"

    # ── 카운트레이트 조회 ──────────────────────────────────────────────────────

    def _diag_count_rates(self):
        """연결 직후 1회: 채널 인덱스별 count rate를 출력해 매핑을 확인한다."""
        buf = ctypes.c_int(0)
        print("[PicoHarp] ── Count Rate Channel Diagnosis ──")
        for ch in (-1, 0, 1, 2):
            try:
                ret = self._lib.PH_GetCountRate(self._dev, ctypes.c_int(ch), ctypes.byref(buf))
                print(f"  PH_GetCountRate(ch={ch:2d}) ret={ret}  rate={buf.value}")
            except Exception as e:
                print(f"  PH_GetCountRate(ch={ch:2d}) exception: {e}")
        print("[PicoHarp] ────────────────────────────────────")

    def fetch_count_rates(self):
        """Sync 및 채널 카운트레이트를 읽어 저장하고 콜백을 호출한다."""
        if not self.ph_available:
            return
        sr = ctypes.c_int(0)
        cr = ctypes.c_int(0)
        # v2.x: PH_GetSyncRate(dev, &rate)
        # v3.x: PH_GetSyncRate 없음 → _sync_rate_ch 인덱스로 PH_GetCountRate 호출
        try:
            self._lib.PH_GetSyncRate(self._dev, ctypes.byref(sr))
            self.sync_rate = sr.value
        except self._DLL_MISSING:
            try:
                self._lib.PH_GetCountRate(
                    self._dev, ctypes.c_int(self._sync_rate_ch), ctypes.byref(sr))
                self.sync_rate = sr.value
            except Exception:
                self.sync_rate = -1
        except Exception:
            self.sync_rate = -1
        try:
            self._lib.PH_GetCountRate(
                self._dev, ctypes.c_int(self._chan_rate_ch), ctypes.byref(cr))
            self.count_rate = cr.value
        except Exception:
            self.count_rate = -1
        if self.on_count_rate:
            self.on_count_rate(self.sync_rate, self.count_rate)

    # ── Histogram 모드 ─────────────────────────────────────────────────────────

    def set_histogram_params(self, acqtime_ms: int, binning: int,
                             offset_ps: int, stop_overflow: bool):
        if not self.ph_available:
            return
        self._lib.PH_SetBinning(self._dev, ctypes.c_int(binning))
        self._dll_call("PH_SetOffset", self._dev, ctypes.c_int(offset_ps))
        stop_val = 1 if stop_overflow else 0
        self._dll_call("PH_SetStopOverflow", self._dev, ctypes.c_int(stop_val),
                       ctypes.c_int(65535))
        self._fetch_resolution()

    def start_histogram(self, acqtime_ms: int, binning: int,
                        offset_ps: int, stop_overflow: bool):
        """Histogram 모드 측정을 백그라운드 스레드에서 시작한다.
        초기화(PH_Initialize, Calibrate, CFD 설정)는 모두 백그라운드 스레드에서 실행하여
        GUI 스레드를 블로킹하지 않는다."""
        if not self.ph_available or self._measuring:
            return
        self._mode = MODE_HIST
        self._stop_event.clear()
        self._measuring = True
        self._meas_thread = threading.Thread(
            target=self._histogram_loop,
            args=(acqtime_ms, binning, offset_ps, stop_overflow),
            daemon=True
        )
        self._meas_thread.start()

    def _histogram_loop(self, acqtime_ms: int, binning: int = None,
                        offset_ps: int = None, stop_overflow: bool = None):
        # 이전 측정 잔재 정리 후 초기화 (ERROR_DEVICE_LOCKED 방지)
        self._dll_call("PH_StopMeas", self._dev)
        time.sleep(0.05)
        ret = self._dll_call("PH_Initialize", self._dev, ctypes.c_int(MODE_HIST), default=-1)
        if ret < 0:
            time.sleep(0.5)   # DEVICE_LOCKED 회복 대기 후 재시도
            ret = self._dll_call("PH_Initialize", self._dev, ctypes.c_int(MODE_HIST), default=-1)
        if ret < 0:
            print(f"[PicoHarp] Init(Hist) error: {self._get_error_string(ret)}")
            self._measuring = False
            if self.on_measurement_done:
                self.on_measurement_done("histogram")
            return
        self._dll_call("PH_Calibrate", self._dev)
        self._apply_cfd()
        if binning is not None:
            self.set_histogram_params(acqtime_ms, binning, offset_ps, stop_overflow)
        self._dll_call("PH_ClearHistMem", self._dev, ctypes.c_int(0))

        ret = self._dll_call("PH_StartMeas", self._dev, ctypes.c_int(acqtime_ms), default=-1)
        if ret < 0:
            print(f"[PicoHarp] StartMeas error: {self._get_error_string(ret)}")
            self._measuring = False
            return

        ctc_status = ctypes.c_int(0)
        elapsed    = ctypes.c_double(0)

        while not self._stop_event.is_set():
            self._dll_call("PH_CTCStatus", self._dev, ctypes.byref(ctc_status))
            self._dll_call("PH_GetElapsedMeasTime", self._dev, ctypes.byref(elapsed))
            self.elapsed_ms = elapsed.value

            # 히스토그램 읽기
            self._dll_call("PH_GetHistogram", self._dev, self._hist_buf,
                           ctypes.c_int(0), ctypes.c_int(0))
            self.histogram = np.frombuffer(self._hist_buf, dtype=np.uint32).copy()

            if self.on_histogram_update:
                self.on_histogram_update(self.histogram, self.elapsed_ms)

            if ctc_status.value != 0:   # 측정 완료
                break
            time.sleep(0.2)

        self._dll_call("PH_StopMeas", self._dev)
        # 최종 히스토그램 읽기
        self._dll_call("PH_GetHistogram", self._dev, self._hist_buf,
                       ctypes.c_int(0), ctypes.c_int(0))
        self.histogram = np.frombuffer(self._hist_buf, dtype=np.uint32).copy()
        if self.on_histogram_update:
            self.on_histogram_update(self.histogram, self.elapsed_ms)

        self._measuring = False
        if self.on_measurement_done:
            self.on_measurement_done("histogram")

    # ── T2 모드 ───────────────────────────────────────────────────────────────

    def start_t2(self, acqtime_s: float, save_path: str,
                 sync_cfd_mv: int = None, chan_cfd_mv: int = None):
        """T2 모드 측정을 백그라운드 스레드에서 시작한다.
        초기화는 백그라운드 스레드에서 실행하여 GUI 스레드를 블로킹하지 않는다."""
        if not self.ph_available or self._measuring:
            return
        self._mode = MODE_T2
        self._stop_event.clear()
        self._measuring = True
        self._meas_thread = threading.Thread(
            target=self._t2_loop,
            args=(acqtime_s, save_path),
            daemon=True
        )
        self._meas_thread.start()

    def _t2_loop(self, acqtime_s: float, save_path: str):
        acqtime_ms = int(acqtime_s * 1000)
        # 이전 측정 잔재 정리 후 초기화 (ERROR_DEVICE_LOCKED 방지)
        self._dll_call("PH_StopMeas", self._dev)
        time.sleep(0.05)
        ret = self._dll_call("PH_Initialize", self._dev, ctypes.c_int(MODE_T2), default=-1)
        if ret < 0:
            time.sleep(0.5)
            ret = self._dll_call("PH_Initialize", self._dev, ctypes.c_int(MODE_T2), default=-1)
        if ret < 0:
            print(f"[PicoHarp] Init(T2) error: {self._get_error_string(ret)}")
            self._measuring = False
            if self.on_measurement_done:
                self.on_measurement_done("t2")
            return
        self._dll_call("PH_Calibrate", self._dev)
        self._apply_cfd()

        ret = self._dll_call("PH_StartMeas", self._dev, ctypes.c_int(acqtime_ms), default=-1)
        if ret < 0:
            print(f"[PicoHarp] StartMeas(T2) error: {self._get_error_string(ret)}")
            self._measuring = False
            return

        buf_type  = ctypes.c_uint * TTREADMAX
        buf       = buf_type()
        nactual   = ctypes.c_int(0)
        ctc_stat  = ctypes.c_int(0)
        flags     = ctypes.c_int(0)
        elapsed   = ctypes.c_double(0)
        total_photons = 0
        records   = []

        os.makedirs(os.path.dirname(save_path) if os.path.dirname(save_path) else ".", exist_ok=True)

        while not self._stop_event.is_set():
            self._dll_call("PH_CTCStatus", self._dev, ctypes.byref(ctc_stat))
            self._dll_call("PH_GetElapsedMeasTime", self._dev, ctypes.byref(elapsed))
            self._dll_call("PH_GetFlags", self._dev, ctypes.byref(flags))

            if flags.value & FLAG_FIFOFULL:
                print("[PicoHarp] FIFO full — data loss possible")

            self._dll_call("PH_ReadFiFo", self._dev, buf, ctypes.c_int(TTREADMAX),
                           ctypes.byref(nactual))
            n = nactual.value
            if n > 0:
                records.extend(buf[:n])
                total_photons += n

            if self.on_t2_progress:
                self.on_t2_progress(elapsed.value / 1000.0, acqtime_s, total_photons)

            if ctc_stat.value != 0:
                break
            time.sleep(0.1)

        self._dll_call("PH_StopMeas", self._dev)
        # 잔여 FIFO 비우기
        while True:
            self._dll_call("PH_ReadFiFo", self._dev, buf, ctypes.c_int(TTREADMAX),
                           ctypes.byref(nactual))
            if nactual.value == 0:
                break
            records.extend(buf[:nactual.value])

        # PTU 포맷으로 저장
        ptu_path = save_path if save_path.endswith(".ptu") else save_path.replace(".pt2", ".ptu")
        # 마지막 elapsed 값을 TTResult_StopAfter에 사용
        elapsed_ms_final = int(elapsed.value) if elapsed.value > 0 else int(acqtime_s * 1000)
        write_ptu(
            ptu_path,
            records,
            acqtime_ms     = int(acqtime_s * 1000),
            sync_rate_hz   = self.sync_rate if self.sync_rate > 0 else 0,
            input_rate_hz  = self.count_rate if self.count_rate > 0 else 0,
            stop_after_ms  = elapsed_ms_final,
            sync_cfd_level = self._sync_cfd_level,
            sync_cfd_zc    = self._sync_cfd_zc,
            sync_div       = self._sync_div,
            chan_cfd_level  = self._chan_cfd_level,
            chan_cfd_zc     = self._chan_cfd_zc,
        )
        print(f"[PicoHarp] T2 done — {len(records):,} records")

        # g2 후처리를 위해 raw records 보관
        self.last_t2_records = list(records)

        self._measuring = False
        if self.on_measurement_done:
            self.on_measurement_done("t2")

    # ── 공통 제어 ─────────────────────────────────────────────────────────────

    def stop_measurement(self):
        """진행 중인 측정을 즉시 중지한다."""
        if not self._measuring:
            return
        self._stop_event.set()
        if self._meas_thread and self._meas_thread.is_alive():
            self._meas_thread.join(timeout=2.0)
        if self.ph_available:
            self._dll_call("PH_StopMeas", self._dev)
        self._measuring = False

    @property
    def is_measuring(self) -> bool:
        return self._measuring

    def get_time_axis_ns(self, num_bins: int = None) -> np.ndarray:
        """히스토그램 시간 축 (ns) 배열을 반환한다."""
        n = num_bins if num_bins is not None else HISTCHAN
        return np.arange(n) * self.resolution / 1000.0  # ps → ns
