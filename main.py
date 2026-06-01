import sys
import subprocess
import importlib

# ============================================================================git
# 필수 패키지 자동 설치
# 패키지가 없으면 pip으로 설치 후 재시도한다.
# ============================================================================
_REQUIRED = {
    "numpy":      "numpy",
    "matplotlib": "matplotlib",
    "nidaqmx":    "nidaqmx",
    "PyQt5":      "PyQt5",  # PyQt5 추가
}

def _ensure_packages():
    missing = []
    for import_name, pip_name in _REQUIRED.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return

    print(f"[설치] 다음 패키지가 없어 자동 설치합니다: {', '.join(missing)}")
    for pkg in missing:
        print(f"  pip install {pkg} ...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"  ✓ {pkg} 설치 완료")
        else:
            print(f"  ✗ {pkg} 설치 실패:\n{result.stderr.strip()}")
            print("  수동으로 설치 후 다시 실행하세요.")
            sys.exit(1)

    print("[설치] 완료. 프로그램을 시작합니다.\n")

_ensure_packages()

# ============================================================================
# PyQt5 애플리케이션 진입점 (Entry Point)
# ============================================================================
from PyQt5.QtWidgets import QApplication
from ui.main_window import DAQMainWindow
from core.app_controller import AppController

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # OS 기본 테마보다 깔끔한 Fusion 스타일 적용
    app.setStyle("Fusion")
    
    # 1. UI 객체 생성 (순수 레이아웃 상태)
    window = DAQMainWindow()
    
    # 2. 비즈니스 로직 및 브릿지를 담당하는 컨트롤러 주입
    controller = AppController(window)
    
    # 3. 창을 닫을 때(앱 종료 시) 스레드 및 하드웨어 안전 정리(shutdown) 바인딩
    app.aboutToQuit.connect(controller.shutdown)    
    
    # 화면에 띄우기
    window.show()
    sys.exit(app.exec_())