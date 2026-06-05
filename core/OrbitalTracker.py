"""
OrbitalTracker.py — 원형 궤도 스캔 기반 실시간 단일 에미터 추적 (v5.4.0)

알고리즘 개요
------------
1. 현재 궤도 중심 (cx, cy) 기준으로 반경 A의 원형 파형 생성
2. AO FINITE 출력 + CI 하드웨어 동기화로 N포인트 동시 수집
3. 1주기 카운트 배열 I[k]에서 1차 Fourier 계수 추출
       a1 = (2/N) Σ I[k]·cos(θ[k])   ← X 오차
       b1 = (2/N) Σ I[k]·sin(θ[k])   ← Y 오차
4. a0(평균 강도)로 정규화 → Takahashi PID → 중심 갱신

하드웨어 동기화
--------------
AO SampleClock → CI SampleClock source 연결
(hw_4pt_track 과 동일한 방식, qudi national_instruments_x_series.py 참조)

참고
----
- Stefani-Lab/MINFLUX-3D : Fourier 오차 추출 알고리즘
- Ulm-IQO/qudi           : PID (software_pid_controller.py), AO-CI 동기화
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

try:
    import nidaqmx
    from nidaqmx.constants import AcquisitionType, Edge
    _NIDAQMX_OK = True
except ImportError:
    _NIDAQMX_OK = False

from PID import PID


# ---------------------------------------------------------------------------
# 설정 데이터클래스
# ---------------------------------------------------------------------------

@dataclass
class OrbitalConfig:
    # 궤도 파라미터
    radius_nm: float = 50.0        # 궤도 반경 (nm). PSF σ의 1/3~1/5 권장.
    n_pts: int = 200               # 1주기 샘플 수. 높을수록 Fourier 정밀도 ↑
    ao_rate: float = 200_000.0     # AO 클럭 (S/s). GVS202 LPF 7 kHz 이상 유지.

    # PID 게인
    kp: float = 0.3                # Proportional. 처음엔 0.1~0.3으로 시작.
    ki: float = 0.0                # Integral. 느린 drift 보상. 기본 0.
    kd: float = 0.0                # Derivative. 기본 0.

    # 보정 제한
    max_correction_nm: float = 20.0  # 1사이클당 최대 보정량 (nm). 발산 방지.

    # EMA 필터 (shot noise 억제)
    ema_alpha: float = 0.2  # 0~1. 작을수록 강한 필터. 0.1~0.3 권장.

    # 하드웨어 채널
    daq_ao_x: str = "Dev2/ao0"
    daq_ao_y: str = "Dev2/ao1"
    daq_counter: str = "Dev2/ctr0"
    daq_pfi: str = "/Dev2/PFI0"
    daq_ao_clk: str = "/Dev2/ao/SampleClock"

    # 단위 변환
    um_per_v: float = 33.333       # Default.py UNIT_CONVERSION_FACTOR 와 일치

    def radius_v(self) -> float:
        """nm → V 변환"""
        return (self.radius_nm * 1e-3) / self.um_per_v

    def max_correction_v(self) -> float:
        return (self.max_correction_nm * 1e-3) / self.um_per_v

    def orbit_period_ms(self) -> float:
        return self.n_pts / self.ao_rate * 1000.0

    def __post_init__(self):
        if self.radius_nm <= 0:
            raise ValueError("radius_nm must be > 0")
        if self.n_pts < 16:
            raise ValueError("n_pts must be >= 16 for reliable Fourier extraction")
        if self.ao_rate < 20_000:
            raise ValueError("ao_rate must be >= 20000 S/s (GVS202 requirement)")
        if self.kp < 0 or self.ki < 0 or self.kd < 0:
            raise ValueError("PID gains must be >= 0")


# ---------------------------------------------------------------------------
# 메인 추적 클래스
# ---------------------------------------------------------------------------

class OrbitalTracker:
    """
    원형 궤도 스캔으로 단일 에미터를 실시간 추적한다.

    사용법
    ------
    tracker = OrbitalTracker(config)
    tracker.start(cx_v, cy_v, update_callback=my_callback)
    ...
    tracker.stop()

    update_callback(info: dict)
        info 키: cx_um, cy_um, a0_cps, a1_norm, b1_norm,
                 orbit_period_ms, cycle_count
    """

    def __init__(self, config: OrbitalConfig):
        self.cfg = config
        self._cx = 0.0          # 현재 궤도 중심 X (V)
        self._cy = 0.0          # 현재 궤도 중심 Y (V)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # PID (X, Y 독립)
        dt_s = config.n_pts / config.ao_rate
        self._pid_x = PID(
            kp=config.kp, ki=config.ki, kd=config.kd,
            dt=dt_s,
            output_min=-config.max_correction_v(),
            output_max= config.max_correction_v(),
        )
        self._pid_y = PID(
            kp=config.kp, ki=config.ki, kd=config.kd,
            dt=dt_s,
            output_min=-config.max_correction_v(),
            output_max= config.max_correction_v(),
        )

        # 미리 계산: 고정 배열
        self._theta = np.linspace(0, 2 * np.pi, config.n_pts, endpoint=False)
        self._cos_t = np.cos(self._theta)
        self._sin_t = np.sin(self._theta)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def start(
        self,
        cx_v: float,
        cy_v: float,
        update_callback: Optional[Callable[[dict], None]] = None,
    ):
        """추적 시작. cx_v, cy_v는 초기 궤도 중심 (V)."""
        if self._running:
            return
        if not _NIDAQMX_OK:
            print("[OrbitalTracker] nidaqmx 없음 — 시뮬레이션 모드로 실행")

        with self._lock:
            self._cx = cx_v
            self._cy = cy_v

        # EMA 필터 초기화 (shot noise 억제)
        self._ema_a1 = 0.0
        self._ema_b1 = 0.0

        self._pid_x.reset()
        self._pid_y.reset()
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(update_callback,),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """추적 종료. 스레드가 끝날 때까지 최대 2초 대기."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def get_center(self) -> tuple[float, float]:
        """현재 추적 중심 (V, V) 반환."""
        with self._lock:
            return self._cx, self._cy

    def update_gains(self, kp: float, ki: float, kd: float):
        """실행 중에도 PID 게인을 업데이트한다."""
        self._pid_x.kp = self._pid_y.kp = kp
        self._pid_x.ki = self._pid_y.ki = ki
        self._pid_x.kd = self._pid_y.kd = kd

    def update_config(self, config: OrbitalConfig):
        """설정 갱신 (다음 사이클부터 적용)."""
        self.cfg = config
        self._theta = np.linspace(0, 2 * np.pi, config.n_pts, endpoint=False)
        self._cos_t = np.cos(self._theta)
        self._sin_t = np.sin(self._theta)
        dt_s = config.n_pts / config.ao_rate
        for pid in (self._pid_x, self._pid_y):
            pid.kp = config.kp
            pid.ki = config.ki
            pid.kd = config.kd
            pid.dt = dt_s
            pid.output_min = -config.max_correction_v()
            pid.output_max  =  config.max_correction_v()

    # ------------------------------------------------------------------
    # 내부 루프
    # ------------------------------------------------------------------

    def _run_loop(self, update_callback):
        cycle = 0
        while self._running:
            with self._lock:
                cx, cy = self._cx, self._cy

            try:
                I, elapsed = self._one_orbit(cx, cy)
            except Exception as e:
                print(f"[OrbitalTracker] 궤도 스캔 오류: {e}")
                if update_callback:
                    try:
                        update_callback({"error": str(e)[:60], "cycle_count": cycle,
                                         "cx_um": 0, "cy_um": 0, "a0_cps": 0,
                                         "displacement_nm": 0})
                    except Exception:
                        pass
                time.sleep(0.5)
                continue

            a0, a1, b1 = self._extract_error(I)

            # a0 정규화: 오차를 emitter 밝기 무관하게 만듦
            # a0 = I.mean() = 샘플당 평균 카운트 (CPS × dt_sample)
            # 60k CPS, 200k S/s → a0 ≈ 0.3 → 임계값은 0.01 이면 충분
            if a0 > 0.01:
                a1_norm = a1 / a0
                b1_norm = b1 / a0
            else:
                a1_norm = b1_norm = 0.0

            # EMA 필터: shot noise 억제 (alpha 작을수록 강한 필터)
            alpha = self.cfg.ema_alpha
            self._ema_a1 = alpha * a1_norm + (1.0 - alpha) * self._ema_a1
            self._ema_b1 = alpha * b1_norm + (1.0 - alpha) * self._ema_b1

            # 위치형 비례 보정
            max_v = self.cfg.max_correction_v()
            dx_v = float(np.clip(self.cfg.kp * self._ema_a1, -max_v, max_v))
            dy_v = float(np.clip(self.cfg.kp * self._ema_b1, -max_v, max_v))

            with self._lock:
                self._cx += dx_v
                self._cy += dy_v
                new_cx, new_cy = self._cx, self._cy

            cycle += 1

            if update_callback:
                info = {
                    "cx_um":  new_cx * self.cfg.um_per_v,
                    "cy_um":  new_cy * self.cfg.um_per_v,
                    "a0_cps": float(I.sum()) / elapsed if elapsed > 0 else 0.0,
                    "a1_norm": a1_norm,
                    "b1_norm": b1_norm,
                    "displacement_nm": np.hypot(a1_norm, b1_norm) * self.cfg.radius_nm,
                    "orbit_period_ms": elapsed * 1000,
                    "cycle_count": cycle,
                }
                try:
                    update_callback(info)
                except Exception:
                    pass

    def _one_orbit(self, cx_v: float, cy_v: float) -> tuple[np.ndarray, float]:
        """
        AO 파형 출력 + CI 동기 수집 → (I[N], elapsed_s)

        CI 읽기 전략: N+1 샘플 수집 후 첫 diff 버리기
        (이전 태스크 누적값 오염 방지)
        """
        cfg = self.cfg
        n = cfg.n_pts
        A = cfg.radius_v()

        vx = cx_v + A * self._cos_t   # shape (N,)
        vy = cy_v + A * self._sin_t   # shape (N,)

        # AO 인터리브: [x0,y0, x1,y1, ...]
        waveform = np.empty((2, n))
        waveform[0] = vx
        waveform[1] = vy

        if not _NIDAQMX_OK:
            # DAQ 없을 때: 시뮬레이션 (가우시안 PSF 가정)
            return self._simulate_orbit(cx_v, cy_v, vx, vy), cfg.n_pts / cfg.ao_rate

        with nidaqmx.Task() as ao_task, nidaqmx.Task() as ci_task:
            # AO 설정
            ao_task.ao_channels.add_ao_voltage_chan(
                cfg.daq_ao_x, min_val=-10, max_val=10)
            ao_task.ao_channels.add_ao_voltage_chan(
                cfg.daq_ao_y, min_val=-10, max_val=10)
            ao_task.timing.cfg_samp_clk_timing(
                rate=cfg.ao_rate,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=n,
            )

            # CI 설정 — AO SampleClock 동기화 (hw_4pt_track 동일 방식)
            # samps_per_chan = n (AO와 동일) → AO n펄스에 맞춰 CI n샘플 수집
            ci_task.ci_channels.add_ci_count_edges_chan(
                counter=cfg.daq_counter, edge=Edge.RISING)
            ci_task.ci_channels[0].ci_count_edges_term = cfg.daq_pfi
            ci_task.timing.cfg_samp_clk_timing(
                rate=cfg.ao_rate,
                source=cfg.daq_ao_clk,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=n,   # AO 샘플 수와 일치 (n+1 이면 마지막 펄스 없어 타임아웃)
            )

            ci_task.start()
            ao_task.write(waveform, auto_start=False)
            ao_task.start()

            timeout = n / cfg.ao_rate * 3 + 1.0
            ao_task.wait_until_done(timeout=timeout)
            ci_raw = np.array(
                ci_task.read(number_of_samples_per_channel=n),
                dtype=np.float64,
            )

        elapsed = n / cfg.ao_rate   # 이론 궤도 시간 (실측보다 정확)

        # 누적 카운터 → 구간별 카운트
        # prepend=ci_raw[0] → 첫 diff=0 (자기 자신 빼기), 나머지 n-1개가 유효
        # hw_4pt_track 동일 방식, rollover 보정 포함
        I = np.diff(ci_raw, prepend=ci_raw[0])
        I[I < -1e8] += 2**32   # 32-bit 카운터 rollover 보정
        I = np.clip(I[1:], 0, None)   # 첫 원소(=0) 제거 → shape (n-1,)
        return I, elapsed

    def _extract_error(self, I: np.ndarray) -> tuple[float, float, float]:
        """
        1차 Fourier 계수 추출.

        a0 : 평균 강도 (counts per sample)
        a1 : cos 성분 → X 방향 오차
        b1 : sin 성분 → Y 방향 오차

        정규화 공식 (MINFLUX-3D / sml-ssi 참조):
            a1 = (2/N) Σ I[k]·cos(θ[k])
            b1 = (2/N) Σ I[k]·sin(θ[k])
        """
        n = len(I)
        a0 = float(I.mean())
        a1 = float((2.0 / n) * np.dot(I, self._cos_t[:n]))
        b1 = float((2.0 / n) * np.dot(I, self._sin_t[:n]))
        return a0, a1, b1

    # ------------------------------------------------------------------
    # 시뮬레이션 (DAQ 없을 때 테스트용)
    # ------------------------------------------------------------------

    def _simulate_orbit(
        self,
        cx_v: float, cy_v: float,
        vx: np.ndarray, vy: np.ndarray,
        true_x_v: float = 0.0,
        true_y_v: float = 0.0,
        peak_cps: float = 100_000,
        sigma_v: float = None,
    ) -> np.ndarray:
        """가우시안 PSF 시뮬레이션. 궤도 중심이 true_x_v, true_y_v에서 벗어나면
        I(θ)가 변조되어 오차 신호가 발생한다."""
        if sigma_v is None:
            sigma_v = 0.15e-3 / self.cfg.um_per_v  # ~150 nm
        dx = vx - true_x_v
        dy = vy - true_y_v
        r2 = dx ** 2 + dy ** 2
        I_mean = peak_cps * np.exp(-r2 / (2 * sigma_v ** 2))
        # Poisson shot noise
        return np.random.poisson(I_mean * (self.cfg.n_pts / self.cfg.ao_rate)).astype(float)


# ---------------------------------------------------------------------------
# 편의 함수: GUI에서 단발성으로 궤도 1회 테스트
# ---------------------------------------------------------------------------

def single_orbit_test(cx_um: float, cy_um: float, config: OrbitalConfig) -> dict:
    """
    단발 궤도 스캔 후 결과 딕셔너리 반환.
    GUI 버튼에서 즉시 호출 가능.
    """
    tracker = OrbitalTracker(config)
    cx_v = cx_um / config.um_per_v
    cy_v = cy_um / config.um_per_v
    I, elapsed = tracker._one_orbit(cx_v, cy_v)
    a0, a1, b1 = tracker._extract_error(I)
    if a0 > 1.0:
        a1_n, b1_n = a1 / a0, b1 / a0
    else:
        a1_n = b1_n = 0.0
    return {
        "a0_cps":   a0 / elapsed if elapsed > 0 else 0,
        "a1_norm":  a1_n,
        "b1_norm":  b1_n,
        "displacement_nm": np.hypot(a1_n, b1_n) * config.radius_nm,
        "elapsed_ms": elapsed * 1000,
        "I": I,
    }
