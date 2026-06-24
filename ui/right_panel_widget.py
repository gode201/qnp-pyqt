from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QScrollArea,
                             QTabWidget, QGroupBox, QLabel, QLineEdit, QPushButton, 
                             QCheckBox, QSpinBox, QProgressBar, QToolButton, QFrame, 
                             QRadioButton, QButtonGroup) 
from PyQt5.QtCore import pyqtSignal, Qt

from core.Default import (
    WINSPEC_IP, WINSPEC_EXPOSURE, WINSPEC_ACCUMULATIONS, WINSPEC_SPE_DIR, WINSPEC_CSV_DIR,
    PH_HIST_ACQTIME_MS, PH_HIST_BINNING, PH_HIST_OFFSET_PS, PH_HIST_STOP_OVERFLOW,
    PH_T2_ACQTIME_S, PH_T2_SAVE_DIR, OBIS_IP
)
class RightPanelWidget(QWidget):
    """
    우측 제어 패널 전담 위젯.
    WinSpec(분광기) 및 PicoHarp 300(TCSPC) 장비의 파라미터 설정과 통신을 담당.
    """
    # -------------------------------------------------------------------------
    # Custom Signals (로직 분리를 위한 시그널)
    # -------------------------------------------------------------------------
    sig_winspec_connect = pyqtSignal(str) # IP 주소 전달
    sig_winspec_acquire = pyqtSignal(dict)
    sig_ph_connect = pyqtSignal()
    sig_ph_start_hist = pyqtSignal(dict)
    sig_ph_start_t2 = pyqtSignal(dict)

    sig_view_mode_changed = pyqtSignal(str) # 'picoharp' 또는 'winspec' 발송
    # -------------------------------------------------------------------------
    # laser
    # -------------------------------------------------------------------------
    sig_obis_connect     = pyqtSignal(str)          # ip
    sig_obis_toggle      = pyqtSignal(str, bool)    # target_id, want_on
    sig_obis_set_power   = pyqtSignal(str, float)   # target_id, mW
    sig_obis_diagnostics = pyqtSignal(str)          # target_id  (선택)



    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # 1. 최상단 아우터 레이아웃
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # 2. 스크롤 영역 생성
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFocusPolicy(Qt.NoFocus)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(5, 5, 5, 5)

        # Global Center Plot View Mode
        view_group = QGroupBox("Center Plot View Mode")
        view_layout = QVBoxLayout()
        view_layout.setSpacing(4)
        self.radio_view_ph = QRadioButton("PicoHarp Histogram")
        self.radio_view_ws = QRadioButton("WinSpec Spectrum")
        self.radio_view_ph.setChecked(True)
        self.view_btn_group = QButtonGroup(self)
        self.view_btn_group.addButton(self.radio_view_ph)
        self.view_btn_group.addButton(self.radio_view_ws)
        view_layout.addWidget(self.radio_view_ph)
        view_layout.addWidget(self.radio_view_ws)
        view_group.setLayout(view_layout)
        self.radio_view_ph.toggled.connect(
            lambda c: c and self.sig_view_mode_changed.emit("picoharp"))
        self.radio_view_ws.toggled.connect(
            lambda c: c and self.sig_view_mode_changed.emit("winspec"))
        layout.addWidget(view_group)

        
        self.tabs = QTabWidget()
        self.winspec_tab = QWidget()
        self.picoharp_tab = QWidget()
        
        self._build_winspec_tab()
        self._build_picoharp_tab()

        self.tabs.addTab(self.winspec_tab, "WinSpec")
        self.tabs.addTab(self.picoharp_tab, "PicoHarp")

        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(self._build_obis_group())
        layout.addWidget(self._build_polarizer_group())
        
        # 3. 스크롤 영역에 콘텐츠 결합
        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll)

    def _tune_form(self, form: QFormLayout):
        """QFormLayout의 정렬 및 여백을 일관되게 설정하는 헬퍼 함수"""
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
    # -------------------------------------------------------------------------
    # WinSpec Tab (Acton SP300i 제어)
    # -------------------------------------------------------------------------
    def _build_winspec_tab(self):
        layout = QVBoxLayout(self.winspec_tab)
        layout.setSpacing(10)

        # 1. Connection Group
        conn_group = QGroupBox("Connection")
        conn_layout = QVBoxLayout()
        
        status_row = QHBoxLayout()
        self.lbl_ws_status_dot = QLabel("●")
        self.lbl_ws_status_dot.setStyleSheet("color: red; font-size: 16px;")
        self.lbl_ws_status = QLabel("Disconnected")
        status_row.addWidget(self.lbl_ws_status_dot)
        status_row.addWidget(self.lbl_ws_status)
        status_row.addStretch()
        conn_layout.addLayout(status_row)

        btn_row = QHBoxLayout()
        self.btn_ws_connect = QPushButton("Connect")
        self.btn_ws_disconnect = QPushButton("Disconnect")
        self.btn_ws_disconnect.setEnabled(False)
        btn_row.addWidget(self.btn_ws_connect)
        btn_row.addWidget(self.btn_ws_disconnect)
        conn_layout.addLayout(btn_row)
        
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # 2. Parameters Group
        param_group = QGroupBox("Parameters")
        form = QFormLayout()
        self._tune_form(form)  # 헬퍼 함수 적용
        
        self.le_ws_ip = QLineEdit(WINSPEC_IP) 
        self.le_ws_prefix = QLineEdit("spectrum")

        exp_layout = QHBoxLayout()
        self.le_ws_exposure = QLineEdit(str(WINSPEC_EXPOSURE))
        self.le_ws_accum = QLineEdit(str(WINSPEC_ACCUMULATIONS))
        exp_layout.addWidget(self.le_ws_exposure)
        exp_layout.addWidget(QLabel("Acc:"))
        exp_layout.addWidget(self.le_ws_accum)

        form.addRow("IP:", self.le_ws_ip)
        form.addRow("Prefix:", self.le_ws_prefix)
        form.addRow("Exp [s]:", exp_layout)
        param_group.setLayout(form)
        layout.addWidget(param_group)

        # 3. Directories Group
        dir_group = QGroupBox("Directories")
        dir_form = QFormLayout()
        self._tune_form(dir_form)  # 헬퍼 함수 적용
        
        self.le_ws_spe_dir = QLineEdit(WINSPEC_SPE_DIR)
        self.le_ws_csv_dir = QLineEdit(WINSPEC_CSV_DIR)
        
        def _add_dir_row(label_text, line_edit):
            row_layout = QHBoxLayout()
            row_layout.addWidget(line_edit)
            btn_browse = QToolButton()
            btn_browse.setText("...")
            row_layout.addWidget(btn_browse)
            dir_form.addRow(label_text, row_layout)
            return btn_browse

        self.btn_ws_browse_spe = _add_dir_row("SPE dir (VM):", self.le_ws_spe_dir)
        self.btn_ws_browse_csv = _add_dir_row("CSV dir (Local):", self.le_ws_csv_dir)
        dir_group.setLayout(dir_form)
        layout.addWidget(dir_group)

        # 4. Action Group
        action_layout = QHBoxLayout()
        self.btn_ws_acquire = QPushButton("Acquire Spectrum")
        self.btn_ws_acquire.setStyleSheet("background-color: #2196F3; color: white;")
        self.btn_ws_acquire.clicked.connect(self._auto_switch_to_winspec)

        self.chk_ws_auto = QCheckBox("Auto after scan")
        action_layout.addWidget(self.btn_ws_acquire)
        action_layout.addWidget(self.chk_ws_auto)
        layout.addLayout(action_layout)

        self.lbl_ws_info = QLabel("")
        self.lbl_ws_info.setStyleSheet("color: gray;")
        layout.addWidget(self.lbl_ws_info)
        layout.addStretch()

    # -------------------------------------------------------------------------
    # PicoHarp Tab (TCSPC 제어)
    # -------------------------------------------------------------------------
    def _build_picoharp_tab(self):
        layout = QVBoxLayout(self.picoharp_tab)
        layout.setSpacing(8)

        # 2. Device & Signals
        dev_group = QGroupBox("Device & Signals")
        dev_layout = QVBoxLayout()
        dev_layout.setSpacing(4)
        
        self.lbl_ph_status_dot = QLabel("●")
        self.lbl_ph_status_dot.setStyleSheet("color: red; font-size: 16px;")
        self.lbl_ph_status = QLabel("Disconnected")

        status_row = QHBoxLayout()
        status_row.addWidget(self.lbl_ph_status_dot)
        status_row.addWidget(self.lbl_ph_status)
        status_row.addStretch()
        dev_layout.addLayout(status_row)

        self.btn_ph_connect = QPushButton("Connect")
        self.btn_ph_disconnect = QPushButton("Disconnect")
        self.btn_ph_disconnect.setEnabled(False)
        self.btn_ph_ctrl_panel = QPushButton("Control Panel")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.btn_ph_connect)
        btn_row.addWidget(self.btn_ph_disconnect)
        btn_row.addWidget(self.btn_ph_ctrl_panel)
        dev_layout.addLayout(btn_row)

        self.lbl_ph_res = QLabel("Res: -- ps")
        self.lbl_ph_res.setStyleSheet("font-family: Courier;")
        dev_layout.addWidget(self.lbl_ph_res)

        # Signals (QProgressBar 활용)
        sig_grid = QGridLayout()
        sig_grid.setHorizontalSpacing(4)
        sig_grid.addWidget(QLabel("Sync:"), 0, 0)
        self.prog_ph_sync = QProgressBar()
        self.prog_ph_sync.setTextVisible(False)
        self.prog_ph_sync.setFixedHeight(10)
        self.lbl_ph_sync_rate = QLabel("CH0: -- cps")
        sig_grid.addWidget(self.prog_ph_sync, 0, 1)
        sig_grid.addWidget(self.lbl_ph_sync_rate, 0, 2)

        sig_grid.addWidget(QLabel("Chan:"), 1, 0)
        self.prog_ph_chan = QProgressBar()
        self.prog_ph_chan.setTextVisible(False)
        self.prog_ph_chan.setFixedHeight(10)
        self.lbl_ph_chan_rate = QLabel("CH1: -- cps")
        sig_grid.addWidget(self.prog_ph_chan, 1, 1)
        sig_grid.addWidget(self.lbl_ph_chan_rate, 1, 2)

        sig_grid.setColumnStretch(0, 0)
        sig_grid.setColumnStretch(1, 1)
        sig_grid.setColumnStretch(2, 0)
        dev_layout.addLayout(sig_grid)

        dev_group.setLayout(dev_layout)
        layout.addWidget(dev_group)

        # 3. Histogram Scale
        scale_group = QGroupBox("Histogram Scale")
        scale_layout = QVBoxLayout()
        scale_layout.setSpacing(4)
        
        self.chk_ph_log = QCheckBox("Log Scale")
        self.chk_ph_log.setChecked(True)
        scale_layout.addWidget(self.chk_ph_log)

        # X range row
        x_row = QHBoxLayout()
        self.chk_ph_xauto = QCheckBox("X Auto")
        self.chk_ph_xauto.setChecked(True)
        self.le_ph_xmin = QLineEdit("0")
        self.le_ph_xmax = QLineEdit("100")
        self.le_ph_xmin.setAlignment(Qt.AlignRight)
        self.le_ph_xmax.setAlignment(Qt.AlignRight)
        x_row.addWidget(self.chk_ph_xauto)
        x_row.addWidget(QLabel("min"))
        x_row.addWidget(self.le_ph_xmin, 1)
        x_row.addWidget(QLabel("max"))
        x_row.addWidget(self.le_ph_xmax, 1)
        scale_layout.addLayout(x_row)

        # Y range row
        y_row = QHBoxLayout()
        self.chk_ph_yauto = QCheckBox("Y Auto")
        self.chk_ph_yauto.setChecked(True)
        self.le_ph_ymin = QLineEdit("1")
        self.le_ph_ymax = QLineEdit("100000")
        self.le_ph_ymin.setAlignment(Qt.AlignRight)
        self.le_ph_ymax.setAlignment(Qt.AlignRight)
        self.btn_ph_apply_scale = QPushButton("Apply")
        y_row.addWidget(self.chk_ph_yauto)
        y_row.addWidget(QLabel("min"))
        y_row.addWidget(self.le_ph_ymin, 1)
        y_row.addWidget(QLabel("max"))
        y_row.addWidget(self.le_ph_ymax, 1)
        y_row.addWidget(self.btn_ph_apply_scale)
        scale_layout.addLayout(y_row)

        scale_group.setLayout(scale_layout)
        layout.addWidget(scale_group)

        # 4. Acquisition (QSpinBox 적용)
        acq_group = QGroupBox("Acquisition")
        acq_form = QFormLayout()
        self._tune_form(acq_form)  # 헬퍼 함수 적용
       
        self.spin_ph_acqtime = QSpinBox()
        self.spin_ph_acqtime.setRange(1, 3600000)
        self.spin_ph_acqtime.setSingleStep(100)
        self.spin_ph_acqtime.setValue(PH_HIST_ACQTIME_MS)

        self.spin_ph_binning = QSpinBox()
        self.spin_ph_binning.setRange(0, 7)
        self.spin_ph_binning.setValue(PH_HIST_BINNING)

        self.spin_ph_offset = QSpinBox()
        self.spin_ph_offset.setRange(-500000, 500000)
        self.spin_ph_offset.setSingleStep(1000)
        self.spin_ph_offset.setValue(PH_HIST_OFFSET_PS)

        self.chk_ph_stop_ovf = QCheckBox("Stop on Overflow")
        self.chk_ph_stop_ovf.setChecked(PH_HIST_STOP_OVERFLOW)


        acq_form.addRow("Time [ms]:", self.spin_ph_acqtime)
        acq_form.addRow("Binning (0-7):", self.spin_ph_binning)
        acq_form.addRow("Offset [ps]:", self.spin_ph_offset)
        acq_form.addRow("", self.chk_ph_stop_ovf)
        acq_group.setLayout(acq_form)
        layout.addWidget(acq_group)

        # 5. T2 Mode
        t2_group = QGroupBox("T2 Mode")
        t2_form = QFormLayout()
        self._tune_form(t2_form)  # 헬퍼 함수 적용
        
        self.spin_ph_t2_acqtime = QSpinBox()
        self.spin_ph_t2_acqtime.setRange(1, 3600)
        self.spin_ph_t2_acqtime.setValue(PH_T2_ACQTIME_S)
        
        dir_layout = QHBoxLayout()
        self.le_ph_t2_dir = QLineEdit(PH_T2_SAVE_DIR)
        self.btn_ph_t2_browse = QToolButton()
        self.btn_ph_t2_browse.setText("...")
        dir_layout.addWidget(self.le_ph_t2_dir)
        dir_layout.addWidget(self.btn_ph_t2_browse)

        t2_form.addRow("AcqTime [s]:", self.spin_ph_t2_acqtime)
        t2_form.addRow("Save dir:", dir_layout)
        t2_group.setLayout(t2_form)
        layout.addWidget(t2_group)

        # 6. Measurement Buttons
        meas_group = QGroupBox("Measurement")
        meas_layout = QVBoxLayout()

        self.btn_ph_start_hist = QPushButton("▶ Start Histogram")
        self.btn_ph_start_hist.setStyleSheet("background-color: #4CAF50; color: white;")

        self.btn_ph_start_hist.clicked.connect(self._auto_switch_to_picoharp)
        
        self.btn_ph_start_t2 = QPushButton("▶ Start T2")
        self.btn_ph_start_t2.setStyleSheet("background-color: #2196F3; color: white;")
        
        self.btn_ph_stop = QPushButton("■ Stop")
        self.btn_ph_stop.setStyleSheet("background-color: #F44336; color: white;")
        self.btn_ph_stop.setEnabled(False)

        meas_layout.addWidget(self.btn_ph_start_hist)
        meas_layout.addWidget(self.btn_ph_start_t2)
        meas_layout.addWidget(self.btn_ph_stop)

        self.lbl_ph_elapsed = QLabel("0 ms / 0 ms")
        self.lbl_ph_t2_photons = QLabel("0 photons")
        self.lbl_ph_elapsed.setStyleSheet("font-family: Courier;")
        self.lbl_ph_t2_photons.setStyleSheet("font-family: Courier;")
        
        meas_layout.addWidget(self.lbl_ph_elapsed)
        meas_layout.addWidget(self.lbl_ph_t2_photons)

        meas_group.setLayout(meas_layout)
        layout.addWidget(meas_group)

        layout.addStretch()
    # -------------------------------------------------------------------------
    # Auto-Switch Helper Methods
    # -------------------------------------------------------------------------
    def _auto_switch_to_winspec(self):
        self.radio_view_ws.setChecked(True)   # toggled가 알아서 emit

    def _auto_switch_to_picoharp(self):
        self.radio_view_ph.setChecked(True)
            
    def _build_obis_group(self):
        """OBIS 레이저 통합 제어부 (Single Server Connection)"""
        # 토글 상태 / 마지막 파워 캐시 (Dialog 초기값으로 사용)
        self._obis_on    = {'laser_532': False, 'laser_633': False}
        self._obis_power = {'laser_532': 0.0,   'laser_633': 0.0}   # mW

        group = QGroupBox("OBIS Lasers")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        
        # 1. 통합 서버 연결부 (TCP Socket Connect)
        conn_layout = QHBoxLayout()
        self.le_obis_ip = QLineEdit(OBIS_IP) 
        self.btn_obis_connect = QPushButton("Connect Server")
        self.btn_obis_connect.setStyleSheet("font-weight: bold;")
        self.btn_obis_connect.clicked.connect(
            lambda: self.sig_obis_connect.emit(self.le_obis_ip.text().strip())
        )
                
        conn_layout.addWidget(QLabel("IP:"))
        conn_layout.addWidget(self.le_obis_ip)
        conn_layout.addWidget(self.btn_obis_connect)
        layout.addLayout(conn_layout)

        # 시각적 구분을 위한 수평선(Line)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # 2. 532nm 레이저 제어부 (오직 Emission ON/OFF만 담당)
        h_layout_532 = QHBoxLayout()
        self.btn_obis_532 = QPushButton("⚫ 532nm OFF")
        self.btn_obis_532.setMinimumWidth(120)
        self.btn_obis_532.setEnabled(False) # 서버 연결 전까지는 조작 불가(Lock)
        self.btn_obis_532.setCheckable(False)  # 상태는 self._obis_on으로 관리
        self.btn_obis_532.clicked.connect(
            lambda: self.sig_obis_toggle.emit('laser_532',
                                            not self._obis_on['laser_532'])
        )
        self.lbl_obis_532_status = QLabel("--- mW")
        self.lbl_obis_532_status.setStyleSheet("font-family: Consolas; font-size: 11px;")
        
        self.btn_obis_532_cfg = QToolButton()
        self.btn_obis_532_cfg.setText("⚙")
        self.btn_obis_532_cfg.setEnabled(False)

        h_layout_532.addWidget(self.btn_obis_532)
        h_layout_532.addWidget(self.lbl_obis_532_status)
        h_layout_532.addStretch()
        h_layout_532.addWidget(self.btn_obis_532_cfg)

        # 3. 633nm 레이저 제어부 (오직 Emission ON/OFF만 담당)
        h_layout_633 = QHBoxLayout()
        self.btn_obis_633 = QPushButton("⚫ 633nm OFF")
        self.btn_obis_633.setMinimumWidth(120)
        self.btn_obis_633.setEnabled(False)
        self.btn_obis_633.setCheckable(False)
        self.btn_obis_633.clicked.connect(
            lambda: self.sig_obis_toggle.emit('laser_633',
                                            not self._obis_on['laser_633'])
        )

        self.lbl_obis_633_status = QLabel("--- mW")
        self.lbl_obis_633_status.setStyleSheet("font-family: Consolas; font-size: 11px;")
        
        self.btn_obis_633_cfg = QToolButton()
        self.btn_obis_633_cfg.setText("⚙")
        self.btn_obis_633_cfg.setEnabled(False)

        h_layout_633.addWidget(self.btn_obis_633)
        h_layout_633.addWidget(self.lbl_obis_633_status)
        h_layout_633.addStretch()
        h_layout_633.addWidget(self.btn_obis_633_cfg)

        layout.addLayout(h_layout_532)
        layout.addLayout(h_layout_633)
        
        group.setLayout(layout)
        
        return group
    
    def _open_obis_config(self, target_id: str):
        from laser_config_dialog import LaserConfigDialog   # 실제 경로에 맞게
        cur = self._obis_power.get(target_id, 0.0)
        dlg = LaserConfigDialog(target_name=target_id,
                                current_power=cur, parent=self)
        if dlg.exec_() == dlg.Accepted:
            self.sig_obis_set_power.emit(target_id, dlg.get_power())

    def set_obis_connected(self, connected: bool):
        for w in (self.btn_obis_532, self.btn_obis_532_cfg,
                self.btn_obis_633, self.btn_obis_633_cfg):
            w.setEnabled(connected)
        self.btn_obis_connect.setText("Disconnect" if connected else "Connect Server")

    def update_obis_status(self, target_id: str, is_on, power_w):
        on = (str(is_on).upper() == 'ON')
        self._obis_on[target_id] = on
        try:
            mw = float(power_w) * 1000.0
            self._obis_power[target_id] = mw
            power_txt = f"{mw:.2f} mW"
        except (TypeError, ValueError):
            power_txt = f"{power_w}"

        if target_id == 'laser_532':
            btn, lbl, tag = self.btn_obis_532, self.lbl_obis_532_status, "532nm"
        else:
            btn, lbl, tag = self.btn_obis_633, self.lbl_obis_633_status, "633nm"

        btn.setText(f"{'🟢' if on else '⚫'} {tag} {'ON' if on else 'OFF'}")
        lbl.setText(power_txt)


    def _build_polarizer_group(self):
        """KDC101 편광기 제어부"""
        group = QGroupBox("Polarizer (KDC101)")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # 1. 연결 및 컨트롤 버튼
        btn_layout = QHBoxLayout()
        self.btn_pol_connect = QPushButton("Connect")
        self.btn_pol_home = QPushButton("⮌ Go to 0°") # 이름 변경
        self.btn_pol_scan_start = QPushButton("▶ Start Scan")
        
        self.btn_pol_home.setEnabled(False)
        self.btn_pol_scan_start.setEnabled(False)
        self.btn_pol_scan_start.setStyleSheet("background-color: #9C27B0; color: white;")
        
        btn_layout.addWidget(self.btn_pol_connect)
        btn_layout.addWidget(self.btn_pol_home)
        btn_layout.addWidget(self.btn_pol_scan_start)
        layout.addLayout(btn_layout)

        # 2. 파라미터 입력부
        param_layout = QHBoxLayout()
        self.spin_pol_step = QSpinBox()
        self.spin_pol_step.setRange(1, 180)
        self.spin_pol_step.setValue(15)  
        
        self.spin_pol_end = QSpinBox()
        self.spin_pol_end.setRange(15, 360)
        self.spin_pol_end.setValue(360)  
        self.spin_pol_end.setSingleStep(15)

        param_layout.addWidget(QLabel("Step [°]:"))
        param_layout.addWidget(self.spin_pol_step)
        param_layout.addWidget(QLabel("End [°]:"))
        param_layout.addWidget(self.spin_pol_end)
        layout.addLayout(param_layout)
        
        # 3. 임의 각도 수동 이동부
        from PyQt5.QtWidgets import QDoubleSpinBox
        manual_layout = QHBoxLayout()
        self.spin_pol_manual = QDoubleSpinBox()
        self.spin_pol_manual.setRange(0, 360)
        self.spin_pol_manual.setDecimals(1)
        self.spin_pol_manual.setValue(0.0)
        
        self.btn_pol_manual_move = QPushButton("Move to")
        self.btn_pol_manual_move.setEnabled(False)
        
        manual_layout.addWidget(QLabel("Target [°]:"))
        manual_layout.addWidget(self.spin_pol_manual)
        manual_layout.addWidget(self.btn_pol_manual_move)
        layout.addLayout(manual_layout)

        # 4. Dry Run 체크박스
        self.chk_pol_dry_run = QCheckBox("Dry Run (No WinSpec)")
        self.chk_pol_dry_run.setStyleSheet("color: #E91E63; font-weight: bold;")
        layout.addWidget(self.chk_pol_dry_run)

        group.setLayout(layout)
        return group