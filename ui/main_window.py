import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QSplitter,
                             QVBoxLayout, QTabWidget, QScrollArea, QLabel, QStatusBar)
from PyQt5.QtCore import Qt

# -----------------------------------------------------------------------------
# Placeholder Classes (ui/ 디렉토리 하위로 분리된 모듈들)
# -----------------------------------------------------------------------------

from ui.left_panel_widget import LeftPanelWidget
from ui.center_plot_widget import CenterPlotWidget
from ui.right_panel_widget import RightPanelWidget

# -----------------------------------------------------------------------------
# Main Window
# -----------------------------------------------------------------------------

class DAQMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QNP galvo control and scanning ver4.0 (PyQt5)")
        self.resize(1500, 900)

        self._last_winspec_data = None  # (x_array, y_array) 튜플 형태로 저장할 예정
        self._last_ph_hist_data = None  # (t_array, counts_array) 튜플 형태로 저장할 예정


        self._setup_ui()
        self._setup_statusbar()
        self._connect_signals()

    def _setup_ui(self):
        """메인 레이아웃 및 Splitter 구성"""
        main_splitter = QSplitter(Qt.Horizontal)

        self.left_panel = LeftPanelWidget()
        self.center_panel = CenterPlotWidget()
        self.right_panel = RightPanelWidget()

        main_splitter.addWidget(self.left_panel)
        main_splitter.addWidget(self.center_panel)
        main_splitter.addWidget(self.right_panel)

        main_splitter.setSizes([300, 900, 300])
        main_splitter.setHandleWidth(4)

        self.setCentralWidget(main_splitter)

    def _setup_statusbar(self):
        """하단 상태바 설정"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.status_left_label = QLabel("State: default")
        self.status_right_label = QLabel("00:00:00")
        
        self.status_bar.addWidget(self.status_left_label, 1) # stretch=1
        self.status_bar.addPermanentWidget(self.status_right_label)

    def _connect_signals(self):
        """하위 위젯들의 시그널을 메인 윈도우의 제어 로직(Slot)과 연결"""
        # 우측 패널의 뷰 모드 변경 시그널 -> 메인 윈도우의 토글 슬롯으로 연결
        self.right_panel.sig_view_mode_changed.connect(self._on_view_mode_changed)

    def _on_view_mode_changed(self, mode: str):
        """라디오 버튼 토글 시 호출되어 중앙 플롯을 캐싱된 데이터로 덮어씌움"""
        if mode == "winspec":
            if self._last_winspec_data is not None:
                x, y = self._last_winspec_data
                self.center_panel.update_spectrum_plot(x, y)
            else:
                # 데이터가 없을 경우 빈 축과 안내 타이틀 렌더링
                self.center_panel.update_spectrum_plot([], [], title="WinSpec Spectrum (No Data)")
                
        elif mode == "picoharp":
            if self._last_ph_hist_data is not None:
                t, counts = self._last_ph_hist_data
                # 주의: center_plot_widget에 이 메서드가 아직 없다면 구현해야 해
                self.center_panel.update_histogram_plot(t, counts)
            else:
                # 임시 더미 데이터로 빈 히스토그램 축 복원
                # update_histogram_plot 메서드 내부 구현에 맞춰 호출할 것
                pass