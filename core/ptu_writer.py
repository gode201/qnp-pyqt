"""
ptu_writer.py — PicoQuant PTU (PQTTTR) 포맷 저장 모듈
=====================================================
PicoHarp 300 T2 모드 raw 레코드(uint32 배열)를 PicoHarp SW 3.0
호환 PTU 바이너리 파일로 저장한다.

PTU 파일 구조:
  1. Magic   : b"PQTTTR\x00\x00"  (8 bytes)
  2. Version : b"1.0.00\x00\x00"  (8 bytes)
  3. Tags    :
     [Fast-load 섹션]  File_GUID … TTResult_StopReason
     Fast_Load_End     (tyEmpty8 마커)
     [Full 헤더 섹션]  TTResultFormat … TTResult_NumberOfRecords
     Header_End        (tyEmpty8 종료 마커)
  4. Records : uint32 TTTR 레코드 스트림

태그 엔트리 구조 (48 bytes 고정 헤더):
  TagIdent  : 32 bytes  (ASCII 문자열, null-padded)
  TagIdx    : 4 bytes   (int32,  인덱스가 없으면 -1)
  TagTyp    : 4 bytes   (uint32, 타입 코드)
  TagVal    : 8 bytes   (int64/float64/string 길이)
  → tyAnsiString의 경우 TagVal 뒤에 문자열 데이터가 연속으로 붙음

PicoHarp 300 T2 레코드 (32-bit):
  bits 31-28: channel/special
  bits 27-0 : timetag  (단위: 4 ps per tick, T2WRAPAROUND = 210698240)
"""

import struct
import numpy as np
from datetime import datetime

# ── PTU 태그 타입 코드 ─────────────────────────────────────────
tyEmpty8     = 0xFFFF0008
tyBool8      = 0x00000008
tyInt8       = 0x10000008
tyFloat8     = 0x20000008
tyTDateTime  = 0x21000008   # Delphi TDateTime (float64, days since 1899-12-30)
tyAnsiString = 0x4001FFFF

# ── 측정 모드 코드 ──────────────────────────────────────────────
MEAS_MODE_T2     = 2
MEAS_SUBMODE_OSC = 0


def _delphi_now() -> float:
    """현재 시각을 Delphi TDateTime (1899-12-30 기준 일수)으로 반환."""
    epoch = datetime(1899, 12, 30)
    delta = datetime.now() - epoch
    return delta.days + delta.seconds / 86400.0 + delta.microseconds / 86400e6


def _pack_tag(ident: str, idx: int, typ: int, value) -> bytes:
    """단일 태그 엔트리를 bytes로 직렬화한다."""
    ident_b = ident.encode("ascii")[:32].ljust(32, b"\x00")
    header = ident_b + struct.pack("<i", idx) + struct.pack("<I", typ)

    if typ == tyAnsiString:
        s = value.encode("ascii") + b"\x00"
        return header + struct.pack("<q", len(s)) + s
    elif typ in (tyFloat8, tyTDateTime):
        return header + struct.pack("<d", float(value))
    elif typ == tyBool8:
        return header + struct.pack("<q", 1 if value else 0)
    elif typ == tyEmpty8:
        return header + struct.pack("<q", 0)
    else:  # tyInt8
        return header + struct.pack("<q", int(value))


def write_ptu(
    filepath: str,
    records,                        # list[int] 또는 np.ndarray(dtype=uint32)
    *,
    acqtime_ms: int   = 1000,
    sync_rate_hz: int = 0,          # PH_GetSyncRate 값 (0 이면 0 기재)
    input_rate_hz: int = 0,         # PH_GetCountRate(0) 값
    stop_after_ms: int = 0,         # 실제 측정 경과 시간 (ms)
    sync_div: int        = 1,
    sync_cfd_level: int  = 100,
    sync_cfd_zc: int     = 10,
    chan_cfd_level: int  = 100,
    chan_cfd_zc: int     = 10,
    hw_serial: str       = "",
    comment: str         = "T2 Mode",
) -> None:
    """
    PicoHarp 300 T2 레코드를 PicoHarp SW 호환 PTU 파일로 저장한다.

    헤더 구조는 PicoHarp Software 3.0.0.3이 저장하는 형식과 동일하다.

    Parameters
    ----------
    filepath      : 저장 경로 (.ptu 확장자 권장)
    records       : PH_ReadFiFo로 수집한 uint32 레코드 리스트 또는 배열
    acqtime_ms    : 설정 취득 시간 (ms) — MeasDesc_AcquisitionTime
    sync_rate_hz  : Sync 카운트레이트 (Hz)
    input_rate_hz : CH1 카운트레이트 (Hz)
    stop_after_ms : 실제 측정 경과 시간 (ms) — TTResult_StopAfter
    sync_div      : Sync 분주비
    sync_cfd_level, sync_cfd_zc : Sync CFD 설정 (mV)
    chan_cfd_level, chan_cfd_zc  : CH1 CFD 설정 (mV)
    hw_serial     : 장비 시리얼 넘버 (빈 문자열이면 미기재)
    comment       : 파일 코멘트 문자열
    """
    arr = np.asarray(records, dtype=np.uint32)
    n_records = len(arr)

    tags: list[bytes] = []

    def t(ident, value, typ=tyInt8, idx=-1):
        tags.append(_pack_tag(ident, idx, typ, value))

    # ════════════════════════════════════════════════════════════
    # Fast-load 섹션  (readPTU 빠른 식별용 최소 정보)
    # ════════════════════════════════════════════════════════════
    t("File_GUID",              "{00000000-0000-0000-0000-000000000000}", tyAnsiString)
    t("File_AssuredContent",    "PicoHarp 300: HWSETG SWSETG",           tyAnsiString)
    t("CreatorSW_ContentVersion", "3.0",                                 tyAnsiString)
    t("CreatorSW_Name",         "PicoHarp Software",                     tyAnsiString)
    t("CreatorSW_Version",      "3.0.0.3",                               tyAnsiString)
    t("File_CreatingTime",      _delphi_now(),                           tyTDateTime)
    t("File_Comment",           comment,                                  tyAnsiString)
    t("Measurement_Mode",       MEAS_MODE_T2)
    t("Measurement_SubMode",    MEAS_SUBMODE_OSC)
    t("TTResult_StopReason",    1)          # 1 = time limit reached

    # Fast-load 종료 마커
    tags.append(_pack_tag("Fast_Load_End", -1, tyEmpty8, 0))

    # ════════════════════════════════════════════════════════════
    # Full 헤더 섹션
    # ════════════════════════════════════════════════════════════

    # ── 포맷 식별 ─────────────────────────────────────────────
    t("TTResultFormat_TTTRRecType",   0x00010203)   # rtPicoHarp300T2
    t("TTResultFormat_BitsPerRecord", 32)

    # ── 측정 파라미터 ─────────────────────────────────────────
    t("MeasDesc_BinningFactor",   1)                # T2 모드: binning 없음
    t("MeasDesc_Offset",          0)
    t("MeasDesc_AcquisitionTime", int(acqtime_ms))  # ms, Int8
    t("MeasDesc_StopAt",          65535)
    t("MeasDesc_StopOnOvfl",      False,  tyBool8)
    t("MeasDesc_Restart",         False,  tyBool8)

    # ── SW 디스플레이 설정 (PicoHarp SW 호환 — 8 curves) ───────
    t("CurSWSetting_DispLog",            False,   tyBool8)
    t("CurSWSetting_DispAxisTimeFrom",   0)
    t("CurSWSetting_DispAxisTimeTo",     160)
    t("CurSWSetting_DispAxisCountFrom",  0)
    t("CurSWSetting_DispAxisCountTo",    50)
    t("CurSWSetting_DispCurves",         8)
    for i in range(8):
        t("CurSWSetting_DispCurve_MapTo",  i,    tyInt8, i)
        t("CurSWSetting_DispCurve_Show",   True,  tyBool8, i)

    # ── 하드웨어 정보 ─────────────────────────────────────────
    t("HW_Type",    "PicoHarp 300", tyAnsiString)
    t("HW_PartNo",  "930004",       tyAnsiString)
    t("HW_Version", "1.0",          tyAnsiString)
    if hw_serial:
        t("HW_SerialNo", hw_serial, tyAnsiString)

    # ── Sync (Ch0) CFD 설정 ───────────────────────────────────
    t("HWSync_Divider",      sync_div)
    t("HWSync_Offset",       0)
    t("HWSync_CFDZeroCross", sync_cfd_zc)
    t("HWSync_CFDLevel",     sync_cfd_level)

    # ── CH1 CFD 설정 ─────────────────────────────────────────
    t("HW_InpChannels",             1)
    t("HWInpChan_CFDZeroCross", chan_cfd_zc,    tyInt8, 0)
    t("HWInpChan_CFDLevel",     chan_cfd_level, tyInt8, 0)

    # ── 해상도 ─────────────────────────────────────────────────
    # T2 모드: MeasDesc_Resolution = MeasDesc_GlobalResolution = 4 ps
    t("MeasDesc_Resolution",       4e-12,  tyFloat8)   # s/tick (T2 base clock)
    t("HW_BaseResolution",         4e-12,  tyFloat8)   # s/tick

    # ── 라우터 / 마커 ─────────────────────────────────────────
    t("HW_ExternalDevices",  0)
    t("HWRouter_ModelCode",  0)
    t("HW_Markers",          4)
    for i in range(4):
        t("HWMarkers_RisingEdge", False, tyBool8, i)
    for i in range(4):
        t("HWMarkers_Enabled",    True,  tyBool8, i)
    t("HWMarkers_HoldOff",   0)

    # ── Global 해상도 (T2 base clock) ─────────────────────────
    t("MeasDesc_GlobalResolution", 4e-12, tyFloat8)    # 4 ps

    # ── 측정 결과 통계 ────────────────────────────────────────
    t("TTResult_SyncRate",  sync_rate_hz)
    t("TTResult_InputRate", input_rate_hz, tyInt8, 0)
    t("TTResult_StopAfter", int(stop_after_ms) if stop_after_ms > 0 else int(acqtime_ms))
    t("TTResult_NumberOfRecords", n_records)

    # Header 종료 마커
    tags.append(_pack_tag("Header_End", -1, tyEmpty8, 0))

    # ════════════════════════════════════════════════════════════
    # 파일 쓰기
    # ════════════════════════════════════════════════════════════
    import os
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)

    # Critical #7 — 디스크 풀 / 권한 오류 시 부분 파일 삭제 후 명시적 예외 발생
    try:
        with open(filepath, "wb") as f:
            f.write(b"PQTTTR\x00\x00")   # Magic   (8 bytes)
            f.write(b"1.0.00\x00\x00")   # Version (8 bytes)
            for tag_bytes in tags:
                f.write(tag_bytes)
            f.write(arr.tobytes())        # Raw TTTR records
    except OSError as _e:
        # 쓰다 만 손상 파일 제거
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
        raise OSError(
            f"[PTU] 파일 저장 실패: {_e}\n"
            f"  경로   : {filepath}\n"
            f"  레코드 : {n_records:,}개 ({arr.nbytes / 1024 / 1024:.1f} MB)\n"
            f"  디스크 여유 공간 또는 경로 권한을 확인하세요."
        ) from _e

    print(f"[PTU] {n_records:,} records → {filepath}")
