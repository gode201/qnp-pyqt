import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QSplitter,
                             QVBoxLayout, QTabWidget, QScrollArea, QLabel, QStatusBar)
# 🟢 QEvent 추가 임포트 필수
from PyQt5.QtCore import Qt, pyqtSignal, QEvent
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

        self._last_winspec_data = None  # (x_array, y_array) 튜플 형태로 저장할 예정
        self._last_ph_hist_data = None  # (t_array, counts_array) 튜플 형태로 저장할 예정


        self._setup_ui()
        self._setup_statusbar()
        self._connect_signals()
        QApplication.instance().installEventFilter(self)

    def _setup_ui(self):
        """메인 레이아웃 및 Splitter 구성"""
        main_splitter = QSplitter(Qt.Horizontal)

        self.left_panel = LeftPanelWidget()
        self.center_panel = CenterPlotWidget()
        self.right_panel = RightPanelWidget()

        fm = self.fontMetrics()
        ch = fm.averageCharWidth()

        # Constraints — ch 기반으로 설정하여 DPI 및 폰트 크기에 따라 동적으로 사이즈 조절
        self.left_panel.setMinimumWidth(int(45 * ch))
        self.left_panel.setMaximumWidth(int(58 * ch))
        self.center_panel.setMinimumWidth(int(40 * ch))
        self.right_panel.setMinimumWidth(int(42 * ch))
        self.right_panel.setMaximumWidth(int(55 * ch))

        # Window Resizing
        screen = QApplication.primaryScreen().availableGeometry()
        window_width = int(screen.width() * 0.88)
        self.resize(window_width, int(screen.height() * 0.90))

        main_splitter.addWidget(self.left_panel)
        main_splitter.addWidget(self.center_panel)
        main_splitter.addWidget(self.right_panel)

        # 중앙 패널이 남은 공간을 흡수하도록 stretch factor 설정
        main_splitter.setStretchFactor(0, 0)  # left: 고정
        main_splitter.setStretchFactor(1, 1)  # center: 확장
        main_splitter.setStretchFactor(2, 0)  # right: 고정

        left_init = int(48 * ch)
        right_init = int(45 * ch)
        center_init = window_width - left_init - right_init

        main_splitter.setSizes([left_init, center_init, right_init])
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
            if getattr(self, '_last_winspec_data', None) is not None:
                x, y = self._last_winspec_data
                self.center_panel.update_spectrum_plot(x, y)
            else:
                # 데이터가 없을 경우 빈 축과 안내 타이틀 렌더링
                self.center_panel.update_spectrum_plot([], [], title="WinSpec Spectrum")
                
        elif mode == "picoharp":
            if getattr(self, '_last_ph_hist_data', None) is not None:
                t, counts = self._last_ph_hist_data
                self.center_panel.update_histogram(t, counts)
            else:
                # 데이터가 없을 경우 기본 히스토그램 축 렌더링
                self.center_panel.update_histogram([], [])

    def eventFilter(self, obj, event):
            """
            이벤트 버블링을 무시하고 가장 먼저 키보드 이벤트를 검사한다.
            Galvo 방향키 제어는 '마우스가 스캔 맵 위에 있거나', '스캔 맵이 포커스를 가질 때'만 작동하도록 철저히 격리.
            """
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
                    from PyQt5.QtWidgets import QApplication
                    
                    # 1. 마우스 커서가 센터 패널(스캔 맵 영역) 위에 있는지 확인
                    is_mouse_on_map = self.center_panel.underMouse() or self.center_panel.canvas.underMouse()
                    
                    # 2. 현재 포커스가 센터 패널 내부의 위젯에 있는지 확인
                    focus_widget = QApplication.focusWidget()
                    is_map_focused = False
                    p = focus_widget
                    while p is not None:
                        if p == self.center_panel:
                            is_map_focused = True
                            break
                        p = p.parentWidget()
                    
                    # [핵심 로직] 사용자의 의도가 명확히 '맵 제어'에 있을 때만 Galvo 제어권 탈취
                    if is_mouse_on_map or is_map_focused:
                        # 왼쪽 패널 텍스트창 등에 포커스가 남아있다면 캔버스로 강제 회수 (입력 커서 끄기)
                        if not is_map_focused:
                            self.center_panel.canvas.setFocus()
                            
                        if key == Qt.Key_Up: self.sig_arrow_pressed.emit('up')
                        elif key == Qt.Key_Down: self.sig_arrow_pressed.emit('down')
                        elif key == Qt.Key_Left: self.sig_arrow_pressed.emit('left')
                        elif key == Qt.Key_Right: self.sig_arrow_pressed.emit('right')
                        return True # 이벤트를 삼켜서 텍스트 커서가 움직이는 등 UI 기본 동작 차단
                    
                    # 맵 영역 밖(왼쪽/오른쪽 패널)에서 마우스를 두고 텍스트 수정 등을 하고 있다면, 
                    # 프레임워크 기본 로직(글자 커서 이동 등)에 방향키를 온전히 양보함
                    return super().eventFilter(obj, event)

            return super().eventFilter(obj, event)