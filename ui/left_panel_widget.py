from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, 
                             QTabWidget, QScrollArea, QGroupBox, QLabel, QLineEdit, 
                             QPushButton, QComboBox, QCheckBox, QDoubleSpinBox)
from PyQt5.QtCore import pyqtSignal, Qt

class LeftPanelWidget(QWidget):
    """
    좌측 제어 패널 전담 위젯.
    Scan, Image 파라미터 입력 및 Move(Galvo/Piezo), Tracking, Auto-Focus 제어 UI를 포함.
    """
    # 외부(Main Window 또는 Controller)로 전달할 커스텀 시그널 정의
    sig_scan_requested = pyqtSignal(dict)
    sig_apd_count_toggled = pyqtSignal(bool)
    sig_galvo_move_requested = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._connect_internal_signals()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 스크롤 영역 생성
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_area.setFocusPolicy(Qt.NoFocus) 
        
        scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setSpacing(10)

        # 1. 탭 위젯 (Scan / Image)
        self.tabs = QTabWidget()
        self.scan_tab = QWidget()
        self.image_tab = QWidget()
        
        self._build_scan_tab()
        self._build_image_tab()
        
        self.tabs.addTab(self.scan_tab, "Scan")
        self.tabs.addTab(self.image_tab, "Image")
        self.scroll_layout.addWidget(self.tabs)

        # 2. Galvo Move 제어부
        self._build_galvo_group()

        # 3. Piezo Z 제어부
        self._build_piezo_group()

        # 4. Tracking & Orbital 제어부
        self._build_tracking_group()

        # 5. 하단 Auto-Focus / Z-Scan 탭
        self.af_zscan_tabs = QTabWidget()
        self.af_tab = QWidget()
        self.zscan_tab = QWidget()
        self._build_af_tab()
        self._build_zscan_tab()
        self.af_zscan_tabs.addTab(self.af_tab, "Auto-Focus")
        self.af_zscan_tabs.addTab(self.zscan_tab, "Z Scan")
        self.scroll_layout.addWidget(self.af_zscan_tabs)

        self.scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area)

    # -------------------------------------------------------------------------
    # UI 빌드 메서드
    # -------------------------------------------------------------------------

    def _build_scan_tab(self):
        layout = QVBoxLayout(self.scan_tab)
        
        # Range & Steps (QGridLayout 활용)
        grid = QGridLayout()
        grid.addWidget(QLabel("X Range:"), 0, 0)
        self.le_x_min = QLineEdit("-10")
        self.le_x_max = QLineEdit("10")
        self.lbl_x_len = QLabel("len: 20.00")
        grid.addWidget(self.le_x_min, 0, 1)
        grid.addWidget(self.le_x_max, 0, 2)
        grid.addWidget(self.lbl_x_len, 0, 3)

        grid.addWidget(QLabel("Y Range:"), 1, 0)
        self.le_y_min = QLineEdit("-10")
        self.le_y_max = QLineEdit("10")
        self.lbl_y_len = QLabel("len: 20.00")
        grid.addWidget(self.le_y_min, 1, 1)
        grid.addWidget(self.le_y_max, 1, 2)
        grid.addWidget(self.lbl_y_len, 1, 3)

        grid.addWidget(QLabel("X Steps:"), 2, 0)
        self.le_x_steps = QLineEdit("100")
        self.lbl_dx = QLabel("dx: 0.200")
        grid.addWidget(self.le_x_steps, 2, 1, 1, 2)
        grid.addWidget(self.lbl_dx, 2, 3)

        grid.addWidget(QLabel("Y Steps:"), 3, 0)
        self.le_y_steps = QLineEdit("100")
        self.lbl_dy = QLabel("dy: 0.200")
        grid.addWidget(self.le_y_steps, 3, 1, 1, 2)
        grid.addWidget(self.lbl_dy, 3, 3)

        layout.addLayout(grid)

        # 파라미터 (Dwell, Mode 등)
        form = QFormLayout()
        
        dwell_layout = QHBoxLayout()
        self.le_dwell = QLineEdit("0.001")
        self.le_avg = QLineEdit("1")
        dwell_layout.addWidget(self.le_dwell)
        dwell_layout.addWidget(QLabel("Avg:"))
        dwell_layout.addWidget(self.le_avg)
        form.addRow("Dwell [s]:", dwell_layout)

        self.le_ao_rate = QLineEdit("50000")
        form.addRow("AO Rate [S/s]:", self.le_ao_rate)
        
        self.cb_scan_mode = QComboBox()
        self.cb_scan_mode.addItems(["Triangle", "Discrete", "Sine", "XZ", "YZ", "3D Stack"])
        form.addRow("Mode:", self.cb_scan_mode)
        
        layout.addLayout(form)

        # 제어 버튼
        btn_layout = QHBoxLayout()
        self.btn_apd_count = QPushButton("APD Count")
        self.btn_scan_start = QPushButton("Scan Start")
        self.btn_scan_resume = QPushButton("Resume")
        self.btn_scan_resume.setEnabled(False)
        btn_layout.addWidget(self.btn_apd_count)
        btn_layout.addWidget(self.btn_scan_start)
        btn_layout.addWidget(self.btn_scan_resume)
        layout.addLayout(btn_layout)

        # 정보 레이블
        self.lbl_scan_info = QLabel("No data")
        self.lbl_scan_info.setStyleSheet("color: blue; font-size: 11px;")

        # 가로 폭이 꽉 차면 자동으로 줄바꿈을 수행한다.
        self.lbl_scan_info.setWordWrap(True)
        # 2~3줄이 써져도 UI가 위아래로 출렁이지 않도록 최소 세로 공간 확보
        self.lbl_scan_info.setMinimumHeight(45)

        layout.addWidget(self.lbl_scan_info)

        # Drift Correction Group
        drift_group = QGroupBox("Drift Correction")
        drift_layout = QGridLayout()
        self.chk_drift_enable = QCheckBox("Enable")
        self.le_drift_interval = QLineEdit("50")
        self.le_drift_ref_x = QLineEdit("0.0")
        self.le_drift_ref_y = QLineEdit("0.0")
        self.btn_drift_set = QPushButton("Set")
        
        drift_layout.addWidget(self.chk_drift_enable, 0, 0)
        drift_layout.addWidget(QLabel("Every:"), 0, 1)
        drift_layout.addWidget(self.le_drift_interval, 0, 2)
        drift_layout.addWidget(QLabel("Ref X:"), 1, 0)
        drift_layout.addWidget(self.le_drift_ref_x, 1, 1)
        drift_layout.addWidget(QLabel("Y:"), 1, 2)
        drift_layout.addWidget(self.le_drift_ref_y, 1, 3)
        drift_layout.addWidget(self.btn_drift_set, 1, 4)
        drift_group.setLayout(drift_layout)
        layout.addWidget(drift_group)
        layout.addStretch()

    def _build_image_tab(self):
        layout = QFormLayout(self.image_tab)
        
        self.chk_cb_lock = QCheckBox("Lock Colorbar")
        self.le_cb_max = QLineEdit("1")
        self.le_cb_min = QLineEdit("0")
        self.le_cb_max.setEnabled(False)
        self.le_cb_min.setEnabled(False)
        
        self.chk_log_scale = QCheckBox("Log Scale")
        
        self.cb_colormap = QComboBox()
        self.cb_colormap.addItems(["gist_heat", "viridis", "jet", "plasma", "inferno"])

        layout.addRow(self.chk_cb_lock)
        layout.addRow("CB Max:", self.le_cb_max)
        layout.addRow("CB Min:", self.le_cb_min)
        layout.addRow(self.chk_log_scale)
        layout.addRow("Colormap:", self.cb_colormap)

        
        self.btn_save_image = QPushButton("Save Image (PNG)")
        self.btn_save_image.setStyleSheet("background-color: #607D8B; color: white;")
        
        self.btn_export_data = QPushButton("Export Data (TXT/CSV)")
        self.btn_import_data = QPushButton("Import Data (TXT/CSV)")
        
        # 버튼들을 레이아웃에 패킹
        layout.addRow(self.btn_save_image)
        layout.addRow(self.btn_export_data, self.btn_import_data)

        self.lbl_image_info = QLabel("Ready")
        self.lbl_image_info.setStyleSheet("color: gray; font-size: 11px;")

        # 가로 폭 제한 시 줄바꿈 활성화 및 최소 공간 확보
        self.lbl_image_info.setWordWrap(True)
        self.lbl_image_info.setMinimumHeight(45)

        layout.addRow(self.lbl_image_info)

    def _build_galvo_group(self):
        group = QGroupBox("Galvo Move")
        layout = QGridLayout()

        self.le_galvo_x = QLineEdit("0.0")
        self.le_galvo_y = QLineEdit("0.0")
        self.btn_galvo_move = QPushButton("Move")
        
        layout.addWidget(QLabel("X (μm):"), 0, 0)
        layout.addWidget(self.le_galvo_x, 0, 1)
        layout.addWidget(QLabel("Y (μm):"), 0, 2)
        layout.addWidget(self.le_galvo_y, 0, 3)
        layout.addWidget(self.btn_galvo_move, 0, 4)

        # 화살표 패드 (간략화)
        pad_layout = QGridLayout()
        self.btn_up = QPushButton("↑")
        self.btn_down = QPushButton("↓")
        self.btn_left = QPushButton("←")
        self.btn_right = QPushButton("→")
        pad_layout.addWidget(self.btn_up, 0, 1)
        pad_layout.addWidget(self.btn_left, 1, 0)
        pad_layout.addWidget(self.btn_right, 1, 2)
        pad_layout.addWidget(self.btn_down, 2, 1)
        layout.addLayout(pad_layout, 1, 0, 1, 3)

        self.btn_set_zero = QPushButton("Set Zero")
        layout.addWidget(self.btn_set_zero, 1, 3, 1, 2)

        group.setLayout(layout)
        self.scroll_layout.addWidget(group)

    def _build_piezo_group(self):
        group = QGroupBox("Piezo Z")
        layout = QGridLayout()
        
        self.le_piezo_z = QLineEdit("10.0")
        self.le_piezo_step = QLineEdit("0.1")
        self.btn_piezo_move = QPushButton("Move Z")
        
        layout.addWidget(QLabel("Z (μm):"), 0, 0)
        layout.addWidget(self.le_piezo_z, 0, 1)
        layout.addWidget(QLabel("Step:"), 0, 2)
        layout.addWidget(self.le_piezo_step, 0, 3)
        
        btn_layout = QHBoxLayout()
        self.btn_z_up = QPushButton("▲")
        self.btn_z_down = QPushButton("▼")
        btn_layout.addWidget(self.btn_piezo_move)
        btn_layout.addWidget(self.btn_z_up)
        btn_layout.addWidget(self.btn_z_down)
        layout.addLayout(btn_layout, 1, 0, 1, 4)

        self.lbl_piezo_live = QLabel("Z: ---.--- μm")
        self.lbl_piezo_live.setStyleSheet("font-family: Consolas; color: blue;")
        layout.addWidget(self.lbl_piezo_live, 2, 0, 1, 4)

        group.setLayout(layout)
        self.scroll_layout.addWidget(group)

    def _build_tracking_group(self):
        group = QGroupBox("Auto / Orbital Tracking")
        layout = QVBoxLayout()
        
        h_layout = QHBoxLayout()
        self.btn_auto_track = QPushButton("Auto-Track OFF")
        self.btn_auto_track.setStyleSheet("background-color: #f44336; color: white;")
        self.chk_z_track = QCheckBox("Z Track")
        h_layout.addWidget(self.btn_auto_track)
        h_layout.addWidget(self.chk_z_track)
        layout.addLayout(h_layout)

        self.btn_orbital = QPushButton("Orbital OFF")
        self.btn_orbital.setStyleSheet("background-color: purple; color: white;")
        layout.addWidget(self.btn_orbital)

        group.setLayout(layout)
        self.scroll_layout.addWidget(group)

    def _build_af_tab(self):
        layout = QFormLayout(self.af_tab)
        self.cb_af_mode = QComboBox()
        self.cb_af_mode.addItems(["plateau_center", "max_slope", "rising_edge"])
        layout.addRow("Mode:", self.cb_af_mode)
        self.le_af_zmin = QLineEdit("0")
        self.le_af_zmax = QLineEdit("20")
        layout.addRow("Z Min/Max:", QHBoxLayout()) # Placeholder, 실제론 더 깔끔하게 패킹
        self.btn_af_start = QPushButton("Auto-Focus")
        self.btn_af_start.setStyleSheet("background-color: #4CAF50; color: white;")
        layout.addRow(self.btn_af_start)

    def _build_zscan_tab(self):
        layout = QFormLayout(self.zscan_tab)
        self.le_zscan_min = QLineEdit("0")
        self.le_zscan_max = QLineEdit("20")
        self.le_zscan_steps = QLineEdit("50")
        layout.addRow("Z Min:", self.le_zscan_min)
        layout.addRow("Z Max:", self.le_zscan_max)
        layout.addRow("Steps:", self.le_zscan_steps)

    # -------------------------------------------------------------------------
    # Internal Signals & Slots (UI 자체 로직 처리)
    # -------------------------------------------------------------------------
    def _connect_internal_signals(self):
        # 파라미터 변경 시 자동으로 dx, dy, len 계산
        self.le_x_min.textChanged.connect(self._recalculate_scan_params)
        self.le_x_max.textChanged.connect(self._recalculate_scan_params)
        self.le_x_steps.textChanged.connect(self._recalculate_scan_params)
        
        self.le_y_min.textChanged.connect(self._recalculate_scan_params)
        self.le_y_max.textChanged.connect(self._recalculate_scan_params)
        self.le_y_steps.textChanged.connect(self._recalculate_scan_params)

        # Colorbar Lock 토글
        self.chk_cb_lock.toggled.connect(self._on_colorbar_lock_toggled)

    def _recalculate_scan_params(self):
        """Tkinter의 trace를 대체하는 PyQt5 슬롯 함수. 입력값 검증 후 자동 계산."""
        try:
            x_min, x_max = float(self.le_x_min.text()), float(self.le_x_max.text())
            x_steps = int(self.le_x_steps.text())
            x_len = x_max - x_min
            dx = x_len / x_steps if x_steps > 0 else 0
            self.lbl_x_len.setText(f"len: {x_len:.2f}")
            self.lbl_dx.setText(f"dx: {dx:.3f}")
        except ValueError:
            pass # 입력 도중 숫자가 아닌 문자(- 등)가 있을 경우 무시

        try:
            y_min, y_max = float(self.le_y_min.text()), float(self.le_y_max.text())
            y_steps = int(self.le_y_steps.text())
            y_len = y_max - y_min
            dy = y_len / y_steps if y_steps > 0 else 0
            self.lbl_y_len.setText(f"len: {y_len:.2f}")
            self.lbl_dy.setText(f"dy: {dy:.3f}")
        except ValueError:
            pass

    def _on_colorbar_lock_toggled(self, checked):
        self.le_cb_max.setEnabled(checked)
        self.le_cb_min.setEnabled(checked)