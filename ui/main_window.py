import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QSplitter,
                             QVBoxLayout, QTabWidget, QScrollArea, QLabel, QStatusBar)

from PyQt5.QtCore import Qt, pyqtSignal
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
    sig_arrow_pressed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("QNP galvo control and scanning ver4.0 (PyQt5)")
        self.resize(1650, 970)

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

        # [레이아웃 고정 및 크래시 방지 로직]
        # Matplotlib 캔버스가 0 이하로 찌그러지는 치명적 에러를 원천 차단
        self.center_panel.setMinimumWidth(500)
        
        # 좌/우 제어 패널이 화면을 다 잡아먹지 못하게 최소/최대 폭을 엄격히 고정
        self.left_panel.setMinimumWidth(450)
        self.left_panel.setMaximumWidth(550)
        self.right_panel.setMinimumWidth(300)
        self.right_panel.setMaximumWidth(350)

        main_splitter.addWidget(self.left_panel)
        main_splitter.addWidget(self.center_panel)
        main_splitter.addWidget(self.right_panel)

        main_splitter.setSizes([550, 1000, 100])
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

    def keyPressEvent(self, event):
        """
        키보드 이벤트를 전역에서 낚아챈다. 
        단, QLineEdit(텍스트 입력창)에 포커스가 없을 때만 Galvo를 움직인다.
        """
        from PyQt5.QtWidgets import QLineEdit
        
        # 현재 포커스를 가진 위젯이 텍스트 입력창이면, 방향키를 글자 편집용으로 양보함
        if isinstance(self.focusWidget(), QLineEdit):
            super().keyPressEvent(event)
            return

        # 그 외의 상태에서는 방향키를 무조건 Galvo 컨트롤용으로 강제 할당
        if event.key() == Qt.Key_Up:
            self.sig_arrow_pressed.emit('up')
            event.accept()
        elif event.key() == Qt.Key_Down:
            self.sig_arrow_pressed.emit('down')
            event.accept()
        elif event.key() == Qt.Key_Left:
            self.sig_arrow_pressed.emit('left')
            event.accept()
        elif event.key() == Qt.Key_Right:
            self.sig_arrow_pressed.emit('right')
            event.accept()
        else:
            super().keyPressEvent(event)        