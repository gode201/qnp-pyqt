import os
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

# 네가 기존에 작성해둔 모듈은 수정 없이 그대로 Import 한다.
from core.SpectrumClient import SpecClient

class WinSpecWorker(QObject):
    """
    WinSpec(Acton SP300i) 통신 및 데이터 저장을 전담하는 Worker 클래스.
    이 클래스의 모든 메서드는 QThread 내부에서 비동기로 실행되어야 한다.
    """
    # -------------------------------------------------------------------------
    # Signals (메인 GUI 스레드로 결과를 전달하는 통로)
    # -------------------------------------------------------------------------
    sig_connected = pyqtSignal(bool, str)       # 연결 성공 여부, 메시지
    sig_disconnected = pyqtSignal()
    sig_acquired = pyqtSignal(bool, dict)       # 성공 여부, 결과 딕셔너리(경로 또는 에러)
    sig_progress = pyqtSignal(str)              # 상태바 또는 UI에 표시할 진행 상황

    def __init__(self):
        super().__init__()
        self.client = None

    @pyqtSlot(str, int)
    def connect_device(self, ip, port=9000):
        """WinSpec 서버에 연결 시도"""
        self.sig_progress.emit(f"Connecting to {ip}:{port}...")
        try:
            self.client = SpecClient(host=ip, port=port)
            if self.client.ping():
                self.sig_connected.emit(True, f"Connected to {ip}")
            else:
                self.client = None
                self.sig_connected.emit(False, "Ping failed. Check if WinSpec server is running.")
        except Exception as e:
            self.client = None
            self.sig_connected.emit(False, f"Connection error: {e}")

    @pyqtSlot()
    def disconnect_device(self):
        """연결 해제"""
        if self.client:
            # SpecClient에 명시적인 close()가 있다면 여기서 호출
            self.client = None
        self.sig_disconnected.emit()
        self.sig_progress.emit("Disconnected from WinSpec.")

    @pyqtSlot(dict)
    def acquire_spectrum(self, params):
        """스펙트럼 측정 및 CSV 파일 저장 (GUI 스레드 블로킹 방지)"""
        if self.client is None:
            self.sig_acquired.emit(False, {"error": "Not connected to WinSpec."})
            return

        self.sig_progress.emit("Acquiring spectrum...")
        try:
            # 파라미터 파싱
            exposure = params.get("exposure", 1.0)
            accum = params.get("accumulations", 1)
            spe_dir = params.get("spe_dir", "").rstrip('/\\')
            csv_dir = params.get("csv_dir", "").rstrip('/\\')
            prefix = params.get("prefix", "spectrum")

            # 파일명 생성
            ts = datetime.now().strftime("%y%m%d_%H%M%S")
            fname = f"{prefix}_{ts}"
            spe_path = f"{spe_dir}/{fname}.spe" if spe_dir else ""

            # 1. 하드웨어 스펙트럼 획득 (가장 오래 걸리는 Blocking I/O)
            result = self.client.acquire(exposure=exposure, accumulations=accum, savepath=spe_path)

            data = result.get('data')
            wavelength = result.get('wavelength')

            # 2. 로컬 CSV 저장 처리
            if data:
                if csv_dir:
                    os.makedirs(csv_dir, exist_ok=True)
                    csv_path = os.path.join(csv_dir, f"{fname}.csv")
                    
                    with open(csv_path, 'w') as f:
                        if wavelength and len(wavelength) == len(data):
                            f.write('wavelength_nm,intensity\n')
                            for wl, v in zip(wavelength, data):
                                f.write(f"{wl},{v}\n")
                        else:
                            f.write('pixel,intensity\n')
                            for i, v in enumerate(data):
                                f.write(f"{i},{v}\n")
                else:
                    csv_path = ""

                self.sig_progress.emit(f"Acquisition complete: {fname}")
                self.sig_acquired.emit(True, {"csv_path": csv_path, "spe_path": spe_path, "fname": fname})
            else:
                self.sig_acquired.emit(False, {"error": "Device returned empty data."})

        except Exception as e:
            self.sig_acquired.emit(False, {"error": str(e)})