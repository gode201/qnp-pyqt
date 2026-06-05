"""
z_autofocus.py — 매핑 전 Z축 Auto-Focus 모듈
2-Pass 방식 + 다중 Focus 모드

사용법:
    from z_autofocus import run_autofocus

    # 모드 1: Plateau 중심 (기존 동작)
    best_z = run_autofocus(piezo, count_task, focus_mode="plateau_center")

    # 모드 2: 최대 기울기 (Slope) 지점
    best_z = run_autofocus(piezo, count_task, focus_mode="max_slope")

    # 모드 3: Rising Edge (포화 직전)
    best_z = run_autofocus(piezo, count_task, focus_mode="rising_edge")

알고리즘:
    1. Coarse Scan (0.1 μm 스텝): 전체 Z 범위에서 대략적 최대 PL 위치 탐색
    2. Fine Scan (0.02 μm 스텝): Coarse 최대값 주변에서 정밀 탐색
    3. Focus 모드에 따라 최종 Z 위치 결정:
       - plateau_center : 최대값의 threshold% 이상인 연속 구간의 중심 (기존)
       - max_slope      : dCPS/dZ (1차 미분)가 최대인 Z 위치
       - rising_edge    : 상승 구간에서 포화가 시작되는 직전 (knee point)
"""
import numpy as np
import time

# ── 지원 모드 상수 ──
FOCUS_MODES = ("plateau_center", "max_slope", "rising_edge")


def z_scan(piezo, count_task, z_positions, dwell):
    """Z 위치 배열을 순회하며 각 위치에서 APD count를 측정.

    Args:
        piezo: PiezoController 인스턴스
        count_task: 이미 start()된 nidaqmx counter task
        z_positions: 측정할 Z 위치 배열 (μm)
        dwell: 각 점 측정 시간 (sec)

    Returns:
        list of (z_um, counts_per_sec)
    """
    data = []
    for z in z_positions:
        piezo.move_to(z)
        piezo.wait_on_target(timeout=2.0)

        c_before = count_task.read()
        t_start = time.perf_counter()
        time.sleep(dwell)
        c_after = count_task.read()
        elapsed = time.perf_counter() - t_start

        cps = (c_after - c_before) / elapsed
        data.append((z, cps))
    return data


# ═══════════════════════════════════════════════════════════
#  Focus 모드별 타겟 Z 결정 함수
# ═══════════════════════════════════════════════════════════

def find_plateau_center(data, threshold_pct=95.0):
    """[모드 1] Fine 스캔 데이터에서 plateau 중심 위치를 찾는다.

    Plateau = 최대값의 threshold_pct% 이상인 연속 구간.
    여러 구간이 있으면 max_idx를 포함하는 구간 우선, 없으면 가장 긴 구간.

    Returns:
        dict with: center_z, max_z, max_cps, plateau_start/end/width
    """
    z_arr = np.array([d[0] for d in data])
    cps_arr = np.array([d[1] for d in data])

    max_idx = np.argmax(cps_arr)
    max_z = z_arr[max_idx]
    max_cps = cps_arr[max_idx]

    threshold = max_cps * (threshold_pct / 100.0)
    above = cps_arr >= threshold

    # 연속 구간(run) 찾기
    runs = []
    in_run = False
    start_idx = 0
    for i, val in enumerate(above):
        if val and not in_run:
            in_run = True
            start_idx = i
        elif not val and in_run:
            in_run = False
            runs.append((start_idx, i - 1))
    if in_run:
        runs.append((start_idx, len(above) - 1))

    if not runs:
        return {
            "center_z": max_z, "max_z": max_z, "max_cps": max_cps,
            "plateau_start": max_z, "plateau_end": max_z, "plateau_width": 0.0,
            "focus_mode": "plateau_center"
        }

    # max_idx를 포함하는 구간 우선
    best_run = None
    for s, e in runs:
        if s <= max_idx <= e:
            best_run = (s, e)
            break
    if best_run is None:
        best_run = max(runs, key=lambda r: r[1] - r[0])

    s, e = best_run
    plateau_start = z_arr[s]
    plateau_end = z_arr[e]
    center_z = (plateau_start + plateau_end) / 2.0

    return {
        "center_z": center_z,
        "max_z": max_z, "max_cps": max_cps,
        "plateau_start": plateau_start,
        "plateau_end": plateau_end,
        "plateau_width": plateau_end - plateau_start,
        "focus_mode": "plateau_center"
    }


def find_max_slope(data, side="left"):
    """[모드 2] 1차 미분(dCPS/dZ)이 최대인 Z 위치를 찾는다.

    상승 구간(좌측)의 양의 기울기 최대값을 탐색한다.

    Args:
        data: list of (z_um, counts_per_sec)
        side: "left"  → 최대값 왼쪽(상승) 구간에서만 탐색 (기본)
              "right" → 최대값 오른쪽(하강) 구간에서만 탐색
              "both"  → 전체 구간에서 |기울기| 최대

    Returns:
        dict with: center_z, max_z, max_cps, slope_z, slope_value, deriv_z, deriv_cps
    """
    z_arr = np.array([d[0] for d in data])
    cps_arr = np.array([d[1] for d in data])

    max_idx = np.argmax(cps_arr)
    max_z = z_arr[max_idx]
    max_cps = cps_arr[max_idx]

    # Savitzky-Golay 스타일 smoothing → 노이즈에 강건한 미분
    # 데이터가 충분하면 np.gradient 후 moving average, 아니면 그냥 np.gradient
    deriv = np.gradient(cps_arr, z_arr)  # dCPS/dZ

    # 간단한 3-point moving average로 미분값 스무딩
    if len(deriv) >= 5:
        kernel = np.ones(3) / 3.0
        deriv_smooth = np.convolve(deriv, kernel, mode="same")
    else:
        deriv_smooth = deriv

    # 탐색 범위 결정
    if side == "left":
        search_slice = slice(0, max_idx + 1)
        target_deriv = deriv_smooth[search_slice]
        target_z = z_arr[search_slice]
        best_local_idx = np.argmax(target_deriv)  # 양의 기울기 최대
    elif side == "right":
        search_slice = slice(max_idx, len(z_arr))
        target_deriv = deriv_smooth[search_slice]
        target_z = z_arr[search_slice]
        best_local_idx = np.argmin(target_deriv)  # 음의 기울기 최대 (하강)
    else:  # "both"
        target_deriv = deriv_smooth
        target_z = z_arr
        best_local_idx = np.argmax(np.abs(target_deriv))

    slope_z = target_z[best_local_idx]
    slope_value = target_deriv[best_local_idx]

    return {
        "center_z": slope_z,
        "max_z": max_z, "max_cps": max_cps,
        "slope_z": slope_z,
        "slope_value": slope_value,
        "deriv_z": z_arr,
        "deriv_cps": deriv_smooth,
        "focus_mode": "max_slope"
    }


def find_rising_edge(data, edge_pct=90.0, method="threshold"):
    """[모드 3] 상승 구간에서 포화 직전 (Rising Edge / Knee Point)을 찾는다.

    두 가지 방법 제공:
      - "threshold" : 상승 구간에서 최대값의 edge_pct%에 처음 도달하는 Z 위치
                      (보간으로 sub-step 정밀도 확보)
      - "knee"      : 2차 미분이 가장 큰 음수가 되는 지점
                      (기울기가 급격히 감소하기 시작하는 변곡점)

    Args:
        data: list of (z_um, counts_per_sec)
        edge_pct: 최대값 대비 임계 비율 (%, 기본 90)
        method: "threshold" 또는 "knee"

    Returns:
        dict with: center_z, max_z, max_cps, edge_z, edge_pct_used
    """
    z_arr = np.array([d[0] for d in data])
    cps_arr = np.array([d[1] for d in data])

    max_idx = np.argmax(cps_arr)
    max_z = z_arr[max_idx]
    max_cps = cps_arr[max_idx]

    # 상승 구간만 추출 (max_idx 왼쪽)
    rise_z = z_arr[:max_idx + 1]
    rise_cps = cps_arr[:max_idx + 1]

    if len(rise_z) < 3:
        # 상승 구간이 너무 짧으면 max 위치 반환
        return {
            "center_z": max_z, "max_z": max_z, "max_cps": max_cps,
            "edge_z": max_z, "edge_pct_used": edge_pct,
            "focus_mode": "rising_edge"
        }

    if method == "threshold":
        # ── Threshold 방식: edge_pct%에 처음 도달하는 위치 ──
        target_cps = max_cps * (edge_pct / 100.0)

        # 처음으로 target_cps를 넘는 인덱스 찾기
        above_mask = rise_cps >= target_cps
        above_indices = np.where(above_mask)[0]

        if len(above_indices) == 0:
            edge_z = max_z
        else:
            cross_idx = above_indices[0]
            if cross_idx > 0:
                # 선형 보간으로 정확한 교차점 계산
                z0, z1 = rise_z[cross_idx - 1], rise_z[cross_idx]
                c0, c1 = rise_cps[cross_idx - 1], rise_cps[cross_idx]
                if c1 != c0:
                    frac = (target_cps - c0) / (c1 - c0)
                    edge_z = z0 + frac * (z1 - z0)
                else:
                    edge_z = z0
            else:
                edge_z = rise_z[0]

    elif method == "knee":
        # ── Knee 방식: 2차 미분이 가장 큰 음수인 지점 ──
        # (기울기가 급격히 줄어드는 = 포화가 시작되는 변곡점)
        deriv1 = np.gradient(rise_cps, rise_z)
        deriv2 = np.gradient(deriv1, rise_z)

        # 스무딩
        if len(deriv2) >= 5:
            kernel = np.ones(3) / 3.0
            deriv2 = np.convolve(deriv2, kernel, mode="same")

        # 상승 구간 후반부(max 쪽 절반)에서 가장 큰 음의 2차 미분
        half = len(deriv2) // 2
        search_d2 = deriv2[half:]
        search_z = rise_z[half:]

        if len(search_d2) > 0:
            knee_local_idx = np.argmin(search_d2)
            edge_z = search_z[knee_local_idx]
        else:
            edge_z = max_z

    else:
        raise ValueError(f"Unknown rising_edge method: {method}. Use 'threshold' or 'knee'.")

    return {
        "center_z": edge_z,
        "max_z": max_z, "max_cps": max_cps,
        "edge_z": edge_z,
        "edge_pct_used": edge_pct,
        "focus_mode": "rising_edge"
    }


def find_focus_target(data, focus_mode="plateau_center", **kwargs):
    """통합 디스패처: focus_mode에 따라 적절한 분석 함수를 호출한다.

    Args:
        data: Fine 스캔 데이터 list of (z_um, counts_per_sec)
        focus_mode: "plateau_center" | "max_slope" | "rising_edge"
        **kwargs: 각 모드별 추가 파라미터
            - plateau_center: threshold_pct (기본 95)
            - max_slope: side (기본 "left")
            - rising_edge: edge_pct (기본 90), method (기본 "threshold")

    Returns:
        dict (각 모드별 결과, 공통 키: center_z, max_z, max_cps, focus_mode)
    """
    if focus_mode == "plateau_center":
        return find_plateau_center(data,
                                   threshold_pct=kwargs.get("threshold_pct", 95.0))
    elif focus_mode == "max_slope":
        return find_max_slope(data,
                              side=kwargs.get("side", "left"))
    elif focus_mode == "rising_edge":
        return find_rising_edge(data,
                                edge_pct=kwargs.get("edge_pct", 90.0),
                                method=kwargs.get("rising_edge_method", "threshold"))
    else:
        raise ValueError(
            f"Unknown focus_mode: '{focus_mode}'. "
            f"Supported modes: {FOCUS_MODES}"
        )


# ═══════════════════════════════════════════════════════════
#  메인 Auto-Focus 실행
# ═══════════════════════════════════════════════════════════

def run_autofocus(piezo, count_task, dwell=0.15,
                  coarse_step=0.1, coarse_range=None,
                  fine_step=0.02, fine_range=1.0,
                  focus_mode="plateau_center",
                  threshold_pct=95.0,
                  edge_pct=90.0,
                  rising_edge_method="threshold",
                  slope_side="left",
                  galvo_xy=None, conv_factor=33.333,
                  verbose=True):
    """2-Pass Auto-Focus 실행 (다중 Focus 모드 지원).

    Args:
        piezo: PiezoController 인스턴스 (연결된 상태)
        count_task: 이미 start()된 nidaqmx counter task
        dwell: 측정 시간 (sec, 기본 0.15)
        coarse_step: Coarse 스캔 스텝 (μm, 기본 0.1)
        coarse_range: Coarse 스캔 범위 (min, max) tuple. None이면 전체 범위
        fine_step: Fine 스캔 스텝 (μm, 기본 0.02)
        fine_range: Fine 스캔 범위 — Coarse 최대값 ± 이 값 (μm, 기본 1.0)

        focus_mode: 포커싱 모드 선택
            "plateau_center" — 최대값 plateau의 중심 (기본, 기존 동작)
            "max_slope"      — dCPS/dZ 1차 미분 최대 지점
            "rising_edge"    — 포화 직전 knee point

        threshold_pct: [plateau_center] plateau 임계값 (%, 기본 95)
        edge_pct: [rising_edge] 포화 임계 비율 (%, 기본 90)
        rising_edge_method: [rising_edge] "threshold" 또는 "knee" (기본 "threshold")
        slope_side: [max_slope] "left"(상승), "right"(하강), "both" (기본 "left")

        galvo_xy: Galvo 위치 (x_um, y_um) tuple. None이면 현재 위치 유지
        conv_factor: μm → V 변환 계수 (기본 33.333)
        verbose: 진행 메시지 출력 여부

    Returns:
        dict: center_z, max_z, max_cps, focus_mode, + 모드별 상세 정보
        실패 시 None
    """
    if focus_mode not in FOCUS_MODES:
        raise ValueError(
            f"Unknown focus_mode: '{focus_mode}'. "
            f"Supported: {FOCUS_MODES}"
        )

    if not piezo.is_connected():
        print("[AutoFocus] ERROR: 피에조가 연결되어 있지 않습니다.")
        return None

    pos_min, pos_max = piezo.get_travel_range()

    # ── Galvo를 지정 위치로 이동 ──
    if galvo_xy is not None:
        import nidaqmx as _nidaqmx
        gx_um, gy_um = galvo_xy
        gx_v, gy_v = gx_um / conv_factor, gy_um / conv_factor
        with _nidaqmx.Task() as ao_task:
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-10, max_val=10)
            ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao1", min_val=-10, max_val=10)
            ao_task.write([gx_v, gy_v], auto_start=True)
        time.sleep(0.01)
        if verbose:
            print(f"[AutoFocus] Galvo → ({gx_um:.2f}, {gy_um:.2f}) μm")

    MODE_LABELS = {
        "plateau_center": "Plateau Center",
        "max_slope": "Max Slope (dCPS/dZ)",
        "rising_edge": "Rising Edge (knee)"
    }

    if verbose:
        print(f"[AutoFocus] 모드: {MODE_LABELS[focus_mode]}")

    # ── Coarse Scan ──
    if coarse_range is not None:
        c_min, c_max = coarse_range
    else:
        c_min, c_max = pos_min, pos_max

    c_min = max(c_min, pos_min)
    c_max = min(c_max, pos_max)
    coarse_z = np.arange(c_min, c_max + coarse_step / 2, coarse_step)
    n_coarse = len(coarse_z)

    if verbose:
        est_time = n_coarse * (dwell + 0.05)
        print(f"[AutoFocus] Coarse Scan: {c_min:.1f}~{c_max:.1f} μm, "
              f"step={coarse_step} μm, {n_coarse}점, ~{est_time:.0f}s")

    coarse_data = z_scan(piezo, count_task, coarse_z, dwell)

    if not coarse_data:
        print("[AutoFocus] ERROR: Coarse 스캔 데이터 없음")
        return None

    best_coarse_z = max(coarse_data, key=lambda x: x[1])[0]
    best_coarse_cps = max(coarse_data, key=lambda x: x[1])[1]

    if verbose:
        print(f"[AutoFocus] Coarse 최대: Z={best_coarse_z:.3f} μm, "
              f"PL={best_coarse_cps:.2e}")

    # ── Fine Scan ──
    # max_slope / rising_edge 모드에서는 상승 구간을 충분히 포함하도록
    # fine_range를 비대칭으로 확장 (왼쪽 2배)
    if focus_mode in ("max_slope", "rising_edge"):
        f_min = max(pos_min, best_coarse_z - fine_range * 2.0)
        f_max = min(pos_max, best_coarse_z + fine_range * 0.5)
    else:
        f_min = max(pos_min, best_coarse_z - fine_range)
        f_max = min(pos_max, best_coarse_z + fine_range)

    fine_z = np.arange(f_min, f_max + fine_step / 2, fine_step)
    n_fine = len(fine_z)

    if verbose:
        est_time = n_fine * (dwell + 0.05)
        print(f"[AutoFocus] Fine Scan: {f_min:.3f}~{f_max:.3f} μm, "
              f"step={fine_step} μm, {n_fine}점, ~{est_time:.0f}s")

    fine_data = z_scan(piezo, count_task, fine_z, dwell)

    if not fine_data:
        print("[AutoFocus] ERROR: Fine 스캔 데이터 없음")
        return None

    # ── Focus 모드별 타겟 결정 ──
    result = find_focus_target(
        fine_data,
        focus_mode=focus_mode,
        threshold_pct=threshold_pct,
        edge_pct=edge_pct,
        rising_edge_method=rising_edge_method,
        side=slope_side
    )

    # 최종 위치로 이동
    piezo.move_to(result["center_z"])
    piezo.wait_on_target(timeout=2.0)
    actual_z = piezo.get_position()

    if verbose:
        print(f"[AutoFocus] Fine 최대: Z={result['max_z']:.3f} μm, "
              f"PL={result['max_cps']:.2e}")

        if focus_mode == "plateau_center":
            print(f"[AutoFocus] Plateau: {result['plateau_start']:.3f} ~ "
                  f"{result['plateau_end']:.3f} μm "
                  f"(폭 {result['plateau_width']:.3f} μm)")
        elif focus_mode == "max_slope":
            print(f"[AutoFocus] Max Slope 위치: Z={result['slope_z']:.3f} μm, "
                  f"dCPS/dZ={result['slope_value']:.2e}")
        elif focus_mode == "rising_edge":
            print(f"[AutoFocus] Rising Edge: Z={result['edge_z']:.3f} μm "
                  f"({result['edge_pct_used']:.0f}% of max)")

        print(f"[AutoFocus] 최종 위치: Z={actual_z:.3f} μm "
              f"[{MODE_LABELS[focus_mode]}]")

    result["coarse_data"] = coarse_data
    result["fine_data"] = fine_data
    result["actual_z"] = actual_z
    result["galvo_xy"] = galvo_xy
    return result


# ═══════════════════════════════════════════════════════════
#  결과 저장 / 플롯
# ═══════════════════════════════════════════════════════════

def save_autofocus_result(result, save_dir, prefix=""):
    """Auto-Focus 결과를 텍스트 파일과 CSV 파일로 동시 저장한다."""
    import os
    import csv
    from itertools import zip_longest
    from datetime import datetime

    os.makedirs(save_dir, exist_ok=True)
    ts = datetime.now().strftime("%y%m%d_%H%M%S")

    mode = result.get("focus_mode", "plateau_center")

    # 1. TXT 파일 저장 (메타데이터 및 로깅용)
    txt_fname = f"{prefix}autofocus_{ts}.txt" if prefix else f"autofocus_{ts}.txt"
    txt_fpath = os.path.join(save_dir, txt_fname)

    with open(txt_fpath, "w", encoding="utf-8") as f:
        f.write(f"# Auto-Focus Result\n")
        f.write(f"# Focus Mode: {mode}\n")
        f.write(f"# Final Z: {result['center_z']:.3f} μm\n")
        f.write(f"# Max Z: {result['max_z']:.3f} μm\n")
        f.write(f"# Max PL: {result['max_cps']:.2e}\n")

        if mode == "plateau_center":
            f.write(f"# Plateau: {result['plateau_start']:.3f} ~ "
                    f"{result['plateau_end']:.3f} μm "
                    f"(width: {result['plateau_width']:.3f} μm)\n")
        elif mode == "max_slope":
            f.write(f"# Max Slope Z: {result['slope_z']:.3f} μm\n")
            f.write(f"# Slope value: {result['slope_value']:.2e}\n")
        elif mode == "rising_edge":
            f.write(f"# Edge Z: {result['edge_z']:.3f} μm\n")
            f.write(f"# Edge %: {result['edge_pct_used']:.1f}%\n")

        f.write(f"# Actual Z: {result['actual_z']:.3f} μm\n")
        f.write(f"\n# === Coarse Scan Data ===\n")
        f.write("Z(um)\tCounts/s\n")
        for z, cps in result["coarse_data"]:
            f.write(f"{z:.3f}\t{cps:.2e}\n")
        f.write(f"\n# === Fine Scan Data ===\n")
        f.write("Z(um)\tCounts/s\n")
        for z, cps in result["fine_data"]:
            f.write(f"{z:.3f}\t{cps:.2e}\n")

    # 2. CSV 파일 저장 (Origin / Excel 데이터 분석용 4-Column 포맷)
    csv_fname = f"{prefix}autofocus_{ts}.csv" if prefix else f"autofocus_{ts}.csv"
    csv_fpath = os.path.join(save_dir, csv_fname)

    coarse = result["coarse_data"]
    fine = result["fine_data"]

    with open(csv_fpath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # 메타데이터 헤더 (분석 툴에서 주석으로 무시할 수 있도록 # 기호 추가)
        writer.writerow([f"# Focus Mode: {mode}", f"Target Z: {result['center_z']:.3f}"])
        # 데이터 컬럼 헤더
        writer.writerow(["Coarse_Z(um)", "Coarse_CPS", "Fine_Z(um)", "Fine_CPS"])

        # zip_longest를 사용하여 길이가 다른 Coarse와 Fine 데이터를 나란히 패킹
        for c_row, f_row in zip_longest(coarse, fine, fillvalue=("", "")):
            # 소수점 포맷팅 적용 (빈 문자열일 경우 TypeError 방어를 위해 타입 체크)
            c_z = f"{c_row[0]:.3f}" if isinstance(c_row[0], (int, float)) else ""
            c_cps = f"{c_row[1]:.2f}" if isinstance(c_row[1], (int, float)) else ""
            f_z = f"{f_row[0]:.3f}" if isinstance(f_row[0], (int, float)) else ""
            f_cps = f"{f_row[1]:.2f}" if isinstance(f_row[1], (int, float)) else ""
            
            writer.writerow([c_z, c_cps, f_z, f_cps])

    print(f"[AutoFocus] 결과 저장 완료: {txt_fpath} 및 {csv_fpath}")
    return txt_fpath


def plot_autofocus_result(result, save_dir, prefix=""):
    """Auto-Focus 결과를 플롯으로 저장 (모드별 시각화)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    import os
    from datetime import datetime

# # AUTO-INJECTED: Korean font setup for matplotlib
# import os as _os
# import matplotlib.font_manager as _fm
# import matplotlib.pyplot as _plt
# if not any('NanumGothic' in f.name for f in _fm.fontManager.ttflist):
#     for _font in ['/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
#                   '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf']:
#         if _os.path.exists(_font):
#             _fm.fontManager.addfont(_font)
# _plt.rcParams.update({'font.family': 'NanumGothic', 'axes.unicode_minus': False})
# del _os, _fm, _plt
# # END AUTO-INJECTED Korean font setup


    mode = result.get("focus_mode", "plateau_center")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # ── Coarse Scan ──
    cz = [d[0] for d in result["coarse_data"]]
    cc = [d[1] for d in result["coarse_data"]]
    ax1.plot(cz, cc, "o-", markersize=3, color="steelblue")
    ax1.axvline(result["max_z"], color="r", linestyle="--", alpha=0.5, label="Max PL")
    ax1.axvline(result["center_z"], color="g", linestyle="-", alpha=0.7,
                label=f"Target ({mode})")
    ax1.set_xlabel("Z (μm)")
    ax1.set_ylabel("Counts/s")
    ax1.set_title("Coarse Scan")
    ax1.legend(fontsize=8)

    # ── Fine Scan + 모드별 표시 ──
    fz = [d[0] for d in result["fine_data"]]
    fc = [d[1] for d in result["fine_data"]]
    ax2.plot(fz, fc, "o-", markersize=3, color="steelblue", label="PL counts")

    if mode == "plateau_center":
        ax2.axvline(result["center_z"], color="g", linestyle="-", linewidth=2,
                    label=f"Plateau center ({result['center_z']:.3f})")
        ax2.axvspan(result["plateau_start"], result["plateau_end"],
                    alpha=0.15, color="green", label="Plateau region")
        ax2.axvline(result["max_z"], color="r", linestyle="--", alpha=0.5,
                    label=f"Max ({result['max_z']:.3f})")

    elif mode == "max_slope":
        ax2.axvline(result["slope_z"], color="darkorange", linestyle="-",
                    linewidth=2, label=f"Max slope ({result['slope_z']:.3f})")
        ax2.axvline(result["max_z"], color="r", linestyle="--", alpha=0.5,
                    label=f"Max ({result['max_z']:.3f})")
        # 미분 커브를 secondary axis에 표시
        if "deriv_z" in result:
            ax2b = ax2.twinx()
            ax2b.plot(result["deriv_z"], result["deriv_cps"],
                      "-", color="darkorange", alpha=0.4, linewidth=1)
            ax2b.set_ylabel("dCPS/dZ (a.u.)", color="darkorange", fontsize=8)
            ax2b.tick_params(axis="y", labelcolor="darkorange", labelsize=7)

    elif mode == "rising_edge":
        ax2.axvline(result["edge_z"], color="purple", linestyle="-",
                    linewidth=2,
                    label=f"Rising edge ({result['edge_z']:.3f})")
        ax2.axhline(result["max_cps"] * result["edge_pct_used"] / 100.0,
                    color="purple", linestyle=":", alpha=0.5,
                    label=f"{result['edge_pct_used']:.0f}% threshold")
        ax2.axvline(result["max_z"], color="r", linestyle="--", alpha=0.5,
                    label=f"Max ({result['max_z']:.3f})")

    ax2.set_xlabel("Z (μm)")
    ax2.set_ylabel("Counts/s")
    MODE_TITLES = {
        "plateau_center": "Fine Scan — Plateau Center",
        "max_slope": "Fine Scan — Max Slope",
        "rising_edge": "Fine Scan — Rising Edge"
    }
    ax2.set_title(MODE_TITLES.get(mode, "Fine Scan"))
    ax2.legend(fontsize=8, loc="lower right")

    plt.tight_layout()
    ts = datetime.now().strftime("%y%m%d_%H%M%S")
    fname = f"{prefix}autofocus_{mode}_{ts}.png" if prefix else f"autofocus_{mode}_{ts}.png"
    fpath = os.path.join(save_dir, fname)
    os.makedirs(save_dir, exist_ok=True)
    plt.savefig(fpath, dpi=150)
    plt.close()
    print(f"[AutoFocus] 플롯 저장: {fpath}")
    return fpath
