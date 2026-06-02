# ============================================================================
# XY Scan Parameters (Galvo 스캔 영역 설정)
# ============================================================================
# 스캔 영역의 XY 범위 (μm). Galvo mirror가 이 범위를 래스터 스캔한다.
# UNIT_CONVERSION_FACTOR로 μm → V 변환 후 NI DAQ AO로 출력.
X_MIN = 12
X_MAX = 24
Y_MIN = 56
Y_MAX = 68
# 스캔 해상도. X_STEPS × Y_STEPS = 총 픽셀 수.
# 높을수록 해상도 ↑, 스캔 시간 ↑. 보통 20~100 사이 사용.
X_STEPS = 20
Y_STEPS = 20


# ============================================================================
# Galvo Mirror Settings (Thorlabs GVS202)
# ============================================================================
# Galvo 기본 위치 (μm). GUI 실행 시 이 위치로 설정된다.
# 샘플 위치에 맞춰 변경. 이전 값은 주석으로 보존.
GALVO_X_DEFAULT = 0.9  #2.3 #0 # -1.6 #-10.2 #-9.6 #18
GALVO_Y_DEFAULT = 2.2  #-6.3#0 #-1.3 #14.4 #2.8 #62
# GUI에서 화살표 버튼(←→↑↓) 클릭 시 이동하는 스텝 크기 (μm).
GALVO_X_STEP = 0.1
GALVO_Y_STEP = 0.1

# APD 카운트 수집 시간 (sec). 각 픽셀 또는 측정 포인트에서 이 시간만큼 카운트를 누적한다.
# 최소 0.1s (100ms). 스캔이 밀리면 값을 올릴 것. 신호 대 잡음비(SNR) ↑이면 값 증가.
SAMPLING_INTERVAL = 0.15

# Galvo 전압 ↔ 물리 거리 변환 계수. 1V = 33.333 μm.
# 광학계 배율에 의존. 대물렌즈나 광학 경로 변경 시 재교정 필요.
UNIT_CONVERSION_FACTOR = 33.333

# Galvo mirror가 새 위치로 이동 후 안정화되는 데 필요한 대기 시간 (sec).
# Discrete 모드에서만 사용됨. Triangle/Sine는 연속 이동이므로 settling 불필요.
# GVS202: 작은 스텝 ~0.3ms, 큰 스텝 ~0.5ms. 여유 있게 0.5ms 설정.
GALVO_SETTLING_TIME = 0.0005

# AO 하드웨어 타이밍 샘플링 레이트 (S/s). Triangle/Sine 스캔에서 사용.
# GVS202 스펙: 최소 20,000 S/s, 권장 100,000 S/s (입력단 7 kHz LPF 존재).
# USB-6341 AO 최대: 900,000 S/s.
# 낮으면 빠른 스텝에서 파형 왜곡 가능, 높으면 메모리/CPU 증가.
AO_SAMPLE_RATE = 200000

# ============================================================================
# XY Auto-Track Settings (v5.3.5 — 하드웨어 타이밍 4점 파형 방식)
# ============================================================================
# 4점 탐색 시 AO 클럭 주파수 (S/s). GVS202 권장 100 kS/s 이상.
TRACK_AO_RATE   = 200000

# 각 probe point 이동 후 갈바노 안정화 구간 (ms).
# GVS202 소형 스텝 정착: ~0.3 ms. 여유 있게 0.5 ms.
TRACK_SETTLE_MS = 0.5

# 각 probe point에서 APD 포톤 누적 구간 (ms).
# 90 kcps 기준: 10 ms = 900 photons (상대 노이즈 3.3%).
TRACK_DWELL_MS  = 10.0

# 기본 스캔 모드. "Triangle" (권장), "Discrete", "Sine" 중 선택.
# Triangle: 빠르고 Galvo 부하 적음, settling 불필요.
# Discrete: 가장 정확하지만 느림 (settling 필요).
# Sine: Galvo에 가장 부드럽지만 desinusoid 보정 필요.
DEFAULT_SCAN_MODE = "Triangle"

# Triangle 모드는 AO SampleClock에 CI를 동기화하여 하드웨어 레벨에서 타이밍을 맞추므로
# 별도의 bidirectional pixel shift 보정이 필요 없다.

# 픽셀당 반복 측정 횟수. 1이면 평균 없이 1회 측정.
# 노이즈가 클 때 2~5로 올리면 SNR 개선, 단 스캔 시간 비례 증가.
AVERAGING_COUNT = 1

# XY 스캔 중 drift 보정 주기. N행(row) 스캔마다 기준점으로 돌아가 위치를 재보정한다.
# 0이면 비활성화. 장시간 스캔에서 thermal drift 보상용.
DRIFT_CORRECTION_INTERVAL = 10

# Drift 보정 시 기준점 주변 탐색 오프셋 (μm).
# 기준점에서 ±이 값만큼 4방향으로 탐색하여 최대 PL 위치를 찾는다.
DRIFT_SEARCH_OFFSET = 0.02


# ============================================================================
# Piezo Z-axis Settings (nanoFaktur SFS-D00150 + EBD-060310)
# ============================================================================
# USB Serial 포트 번호. 측정 PC의 장치관리자에서 FTDI COM 포트 확인 후 변경.
PIEZO_COM_PORT = '4'

# GUI 시작 시 피에조 초기 Z 위치 (μm). 스테이지 전체 이동 범위는 0~150 μm.
# 75.0은 중간값. 샘플 두께/마운트 위치에 따라 조절.
PIEZO_Z_DEFAULT = 75.0

# GUI에서 ▲/▼ 버튼 또는 PageUp/PageDown 클릭 시 Z축 이동 스텝 (μm).
PIEZO_Z_STEP = 1.0

# 피에조 이동 명령 후 on-target 상태 대기 타임아웃 (sec).
# SGS closed-loop 센서가 목표 위치 도달을 확인할 때까지 최대 이 시간만큼 대기.
# 150 μm 전체 이동도 수 초 이내이므로 5.0s면 충분.
PIEZO_SETTLING_TIMEOUT = 5.0

# ============================================================================
# Auto-Focus Settings (2-Pass 방식)
# ============================================================================
# 1st Pass (Coarse Scan): 넓은 Z 범위를 큰 스텝으로 빠르게 훑어 대략적 최대 PL 위치를 찾는다.
AF_Z_MIN = 0.0               # Coarse 스캔 시작 위치 (μm). 0 = 피에조 최하단.
AF_Z_MAX = 150.0             # Coarse 스캔 끝 위치 (μm). 150 = 피에조 최상단.
AF_COARSE_STEP = 5.0         # Coarse 스캔 스텝 (μm). 작을수록 정밀하나 시간 증가.
                              # (150-0)/5 = 30점 → 약 30×0.15s = 4.5s

# 2nd Pass (Fine Scan): Coarse 최대값 주변을 작은 스텝으로 정밀 탐색한다.
AF_FINE_RANGE = 10.0         # Coarse 최대값 ± 이 범위 (μm) 내에서 Fine 스캔.
                              # PSF가 넓으면 줄여도 되고, 좁으면 유지.
AF_FINE_STEP = 0.5           # Fine 스캔 스텝 (μm). 0.1까지 줄일 수 있으나 시간 증가.
                              # 20/0.5 = 40점 → 약 40×0.15s = 6s

# ============================================================================
# Z Tracking Settings (Auto-Track 중 Z drift 자동 보정)
# ============================================================================
# XY tracking은 매 사이클 실행되고, Z tracking은 매 N사이클마다 1회 실행된다.
# Z drift는 thermal drift에 의해 발생하며 XY보다 느린 시간 스케일이므로
# 매 사이클 보정할 필요가 없다 (Approach B).
Z_TRACK_CYCLE = 5            # 매 N회 XY tracking 사이클마다 Z tracking 1회 실행.
                              # drift가 빠르면 줄이고(2~3), 느리면 늘린다(10~20).

Z_TRACK_STEP = 0.02          # Z 탐색 스텝 크기 (μm). 현재 Z 기준 5점 측정:
                              # Z-2Δ, Z-Δ, Z, Z+Δ, Z+2Δ (Δ = 이 값)
                              # 전체 탐색 범위 = ±2×0.02 = ±0.04 μm.
                              # confocal PSF 폭에 맞춰 조절. 너무 작으면 noise에 묻힘.

Z_TRACK_ENABLED = False      # Z tracking 기본 ON/OFF. GUI 체크박스로도 전환 가능.
                              # 피에조 미연결 시 자동으로 무시됨.

# ============================================================================
# Z Scan Settings (XZ/YZ Cross-Section + 3D Stack)
# ============================================================================
# XZ/YZ cross-section 또는 3D stack 스캔에서 Z축 스텝 수.
# Z 범위는 GUI Z Scan 패널의 Z Min/Max에서 설정한다.
Z_SCAN_STEPS = 20            # Z축 스텝 수. 높을수록 해상도 ↑, 스캔 시간 ↑.
Z_SCAN_MIN = 60.0            # Z 스캔 시작 위치 (μm).
Z_SCAN_MAX = 90.0            # Z 스캔 끝 위치 (μm).

# ============================================================================
# PicoHarp 300 (TCSPC) Settings
# ============================================================================
PICOHARP_DEVICE_IDX    = 0           # 장치 인덱스 (여러 대 연결 시 0, 1, ...)
PICOHARP_DLL_PATH      = r"C:\Windows\System32\phlib64.dll"

# Histogram 모드 파라미터
PH_HIST_ACQTIME_MS     = 1000        # 취득 시간 (ms). 1ms ~ 3,600,000ms
PH_HIST_BINNING        = 3           # 시간 해상도 지수. 분해능 = 2^n × 4 ps
                                      # 0 → 4ps, 1 → 8ps, ..., 7 → 512ps
PH_HIST_OFFSET_PS      = 0           # 타임 오프셋 (ps). -500,000 ~ +500,000
PH_HIST_STOP_OVERFLOW  = False        # overflow 시 자동 정지

# 채널 CFD 파라미터 (기본값 — 실험 조건에 따라 조정)
PH_SYNC_CFD_LEVEL_MV   = 111         # Sync 채널 CFD 레벨 (mV)
PH_SYNC_CFD_ZERO_MV    = 11          # Sync 채널 CFD 영점 교차 (mV)
PH_CHAN_CFD_LEVEL_MV   = 100         # 검출 채널 CFD 레벨 (mV)
PH_CHAN_CFD_ZERO_MV    = 10          # 검출 채널 CFD 영점 교차 (mV)
PH_SYNC_DIV            = 1           # Sync 분주비 (1, 2, 4, 8)
PH_SYNC_OFFSET_NS      = 0           # Sync 채널 타이밍 오프셋 (ns)
PH_CHAN_OFFSET_NS      = 0           # Ch1 채널 타이밍 오프셋 (ns)

# Acquisition 파라미터 (Control Panel)
PH_STOP_AT             = 65535       # Stop At 카운트 (Stop on Overflow와 함께 사용)
PH_TRC_BLOCK           = 0           # Trace/Block 누적 횟수 (0 = 단일)
PH_ACQMODE             = "INT"       # 측정 모드: OSC / INT / TRES
PH_ROUTED              = False       # Routed 모드 (라우터 연결 시)
PH_RESTART             = False       # 자동 재시작

# T2 모드 파라미터
PH_T2_ACQTIME_S        = 10          # T2 취득 시간 (초)
PH_T2_SAVE_DIR         = r"C:/Users/user/Desktop/pl plots"  # .pt2 저장 경로

# HBT g2 분석 파라미터 (g2_analysis_gui.py 기본값)
G2_TAU_RANGE_NS        = 10000         # g2 분석 범위 ±τ (ns)
G2_BIN_WIDTH_PS        = 256         # g2 히스토그램 bin 폭 (ps)

# ============================================================================
# File Save Paths
# ============================================================================
SAVE_PATH = r"C:/Users/user/Desktop/pl plots"           # 수동 저장 경로
AUTO_SAVE_PATH = r"C:/Users/user/Desktop/pl plots/auto save"  # 자동 저장 경로
PHOTON_COUNT_SAVE_PATH = r"C:/Users/user/Desktop/pl plots/photon counts"  # photon count 자동 저장 경로

# ============================================================================
# WinSpec Spectrum Settings (COM1 Win7 VM)
# ============================================================================
WINSPEC_IP          = '192.168.0.54'  # Win7 VM IP
WINSPEC_PORT        = 8765
WINSPEC_EXPOSURE    = 1.0             # 기본 노출 시간 (초)
WINSPEC_ACCUMULATIONS = 1            # 기본 누적 횟수
WINSPEC_SPE_DIR     = 'C:/winspec_data'           # Win7 VM SPE 저장 경로 (서버 기준)
WINSPEC_CSV_DIR     = r'Z:'                        # COM2 CSV 저장 경로 (Z: = C:\winspec_data)

# ============================================================================
# Obis Laser IP
# ============================================================================
OBIS_IP = '192.168.0.54'
