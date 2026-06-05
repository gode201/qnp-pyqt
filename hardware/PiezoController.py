# PiezoController.py
# nanoFaktur 피에조 스테이지 제어 클래스
# DLL + xDev.py wrapper를 사용하여 피에조와 통신

import threading
import time
import os
import atexit

from hardware.xDev import (
    xDev_load_dll, xDev_init, xDev_exit,
    xDev_get_pos, xDev_move, xDev_move_inc,
    xDev_set_svo_softly, xDev_get_svo, xDev_get_ont,
    xDev_get_param_float
)


class PiezoController:
    """nanoFaktur 피에조 스테이지(Z축) 제어 클래스.

    - DLL 호출은 threading.Lock()으로 보호 (SDK 전역 상태 사용)
    - 연결 실패 시 graceful return (crash 방지)
    - 상대 경로로 DLL 로딩 (폴더 이동 가능)
    """

    AXIS = 0  # 단축 컨트롤러

    def __init__(self):
        self._lock = threading.Lock()
        self._connected = False
        self._handle = None
        self.pos_min = 0.0
        self.pos_max = 150.0
        self._target_pos = None  # 마지막으로 명령한 위치 (센서 노이즈 없이 step 정확도 유지)
        # 프로세스 종료 시(크래시, 강제종료 포함) 자동으로 포트 해제
        atexit.register(self._cleanup)

    def connect(self, port='4'):
        """피에조 컨트롤러에 연결.

        Args:
            port: COM 포트 번호 (문자열, 예: '4' → COM4)

        Returns:
            True: 연결 성공, False: 연결 실패
        """
        with self._lock:
            if self._connected:
                print("Piezo: already connected.")
                return True

            try:
                self._handle = xDev_load_dll()
                res = xDev_init(self._handle, b'com', port.encode())
                if res != 0:
                    print(f"Piezo: connection failed (error: {res})")
                    try:
                        xDev_exit()  # 실패해도 DLL 리소스/포트 정리
                    except Exception:
                        pass
                    self._handle = None
                    return False

                # 이동 범위 읽기
                self.pos_min = xDev_get_param_float(self.AXIS, 0x20400031)
                self.pos_max = xDev_get_param_float(self.AXIS, 0x20400030)

                # Closed-loop servo 안전하게 활성화
                xDev_set_svo_softly(self.AXIS, True)

                self._connected = True
                pos = xDev_get_pos(self.AXIS)
                self._target_pos = pos  # 연결 시 현재 센서 위치로 초기화
                print(f"Piezo: connected (COM{port}), "
                      f"range: {self.pos_min:.3f}~{self.pos_max:.3f} μm, "
                      f"pos: {pos:.3f} μm")
                return True

            except Exception as e:
                print(f"Piezo: connection error - {e}")
                self._handle = None
                self._connected = False
                return False

    def disconnect(self):
        """피에조 컨트롤러 연결 해제."""
        with self._lock:
            if not self._connected:
                return
            try:
                xDev_exit()
            except Exception as e:
                print(f"Piezo: disconnect error - {e}")
            finally:
                self._connected = False
                self._handle = None
                print("Piezo: disconnected.")

    def _cleanup(self):
        """atexit/del 에서 호출. 포트가 잠기지 않도록 안전 해제."""
        if self._connected:
            try:
                xDev_exit()
            except Exception:
                pass
            self._connected = False
            self._handle = None

    def __del__(self):
        self._cleanup()

    def is_connected(self):
        """연결 상태 반환."""
        return self._connected

    def get_position(self):
        """현재 위치 읽기 (μm) — 센서 값.

        Returns:
            float: 현재 위치 (μm). 미연결 시 0.0
        """
        with self._lock:
            if not self._connected:
                return 0.0
            try:
                return xDev_get_pos(self.AXIS)
            except Exception as e:
                print(f"Piezo: get_position error - {e}")
                return 0.0

    def get_target_position(self):
        """마지막으로 커맨드한 목표 위치 (μm) — 센서 노이즈 없음.

        move_to / move_relative 호출 후 입력 박스 표시용으로 사용.
        미이동 시 현재 센서 위치 반환.

        Returns:
            float: 커맨드 위치 (μm). 미연결 시 0.0
        """
        with self._lock:
            if not self._connected:
                return 0.0
            if self._target_pos is not None:
                return self._target_pos
            try:
                return xDev_get_pos(self.AXIS)
            except Exception:
                return 0.0

    def move_to(self, target_um):
        """지정 위치로 이동 (closed-loop).

        Args:
            target_um: 목표 위치 (μm)

        Returns:
            True: 이동 명령 성공, False: 실패
        """
        with self._lock:
            if not self._connected:
                print("Piezo: not connected.")
                return False

            # 범위 클램핑
            clamped = max(self.pos_min, min(self.pos_max, target_um))
            if clamped != target_um:
                print(f"Piezo: target {target_um:.3f} clamped to {clamped:.3f} μm")

            try:
                xDev_move(self.AXIS, clamped)
                self._target_pos = clamped
                return True
            except Exception as e:
                print(f"Piezo: move_to error - {e}")
                return False

    def move_relative(self, delta_um):
        """현재 위치에서 상대 이동.

        센서를 읽지 않고 마지막 명령 위치(_target_pos)를 기준으로 계산하여
        센서 노이즈/settling 오차 없이 step 크기를 정확히 유지한다.

        Args:
            delta_um: 이동량 (μm, 양수=forward, 음수=backward)

        Returns:
            True: 성공, False: 실패
        """
        with self._lock:
            if not self._connected:
                print("Piezo: not connected.")
                return False
            try:
                if self._target_pos is None:
                    self._target_pos = xDev_get_pos(self.AXIS)
                target = max(self.pos_min, min(self.pos_max, self._target_pos + delta_um))
                xDev_move(self.AXIS, target)
                self._target_pos = target
                return True
            except Exception as e:
                print(f"Piezo: move_relative error - {e}")
                return False

    def wait_on_target(self, timeout=5.0):
        """on-target 상태까지 대기.

        Args:
            timeout: 최대 대기 시간 (초)

        Returns:
            True: on-target 도달, False: 타임아웃
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if not self._connected:
                    return False
                try:
                    if xDev_get_ont(self.AXIS):
                        return True
                except Exception:
                    return False
            time.sleep(0.01)  # 10ms 간격 폴링
        print(f"Piezo: on-target timeout ({timeout}s)")
        return False

    def get_travel_range(self):
        """이동 범위 반환.

        Returns:
            tuple: (min_um, max_um)
        """
        return (self.pos_min, self.pos_max)

    def enable_servo(self):
        """Closed-loop servo 활성화."""
        with self._lock:
            if not self._connected:
                return False
            try:
                xDev_set_svo_softly(self.AXIS, True)
                return bool(xDev_get_svo(self.AXIS))
            except Exception as e:
                print(f"Piezo: enable_servo error - {e}")
                return False

    def disable_servo(self):
        """Closed-loop servo 비활성화 (open-loop)."""
        with self._lock:
            if not self._connected:
                return False
            try:
                xDev_set_svo_softly(self.AXIS, False)
                return not bool(xDev_get_svo(self.AXIS))
            except Exception as e:
                print(f"Piezo: disable_servo error - {e}")
                return False
