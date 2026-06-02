from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, 
                             QTabWidget, QGroupBox, QLabel, QLineEdit, QPushButton, 
                             QCheckBox, QSpinBox, QProgressBar, QToolButton,
                             QRadioButton, QButtonGroup) # QRadioButton, QButtonGroup 추가
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---------------------------------------------------------------------
        # Global Center Plot View Mode
        # ---------------------------------------------------------------------
        view_group = QGroupBox("Center Plot View Mode")
        view_layout = QHBoxLayout()
        
        self.radio_view_ph = QRadioButton("PicoHarp Histogram")
        self.radio_view_ws = QRadioButton("WinSpec Spectrum")
        
        self.radio_view_ph.setChecked(True) # 기본값

        # 버튼 그룹으로 묶어서 상호 배타적(Exclusive)으로 동작하게 만듦
        self.view_btn_group = QButtonGroup(self)
        self.view_btn_group.addButton(self.radio_view_ph)
        self.view_btn_group.addButton(self.radio_view_ws)

        view_layout.addWidget(self.radio_view_ph)
        view_layout.addWidget(self.radio_view_ws)
        view_group.setLayout(view_layout)
        
        layout.addWidget(view_group) # 탭 위에 배치

        # 상태 변경 이벤트 연결
        self.radio_view_ph.toggled.connect(
            lambda checked: checked and self.sig_view_mode_changed.emit("picoharp")
                                            )
        self.radio_view_ws.toggled.connect(
            lambda checked: checked and self.sig_view_mode_changed.emit("winspec")
        )

        
        # ---------------------------------------------------------------------

        self.tabs = QTabWidget()
        self.winspec_tab = QWidget()
        self.picoharp_tab = QWidget()
        
        self._build_winspec_tab()
        self._build_picoharp_tab()
        
        

        self.tabs.addTab(self.winspec_tab, "WinSpec")
        self.tabs.addTab(self.picoharp_tab, "PicoHarp")

        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(self._build_obis_group())


    # -------------------------------------------------------------------------
    # WinSpec Tab (Acton SP300i 제어)
    # -------------------------------------------------------------------------
    def _build_winspec_tab(self):
        layout = QVBoxLayout(self.winspec_tab)
        layout.setSpacing(10)

        # 1. Connection Group
        conn_group = QGroupBox("Connection")
        conn_layout = QHBoxLayout()
        self.lbl_ws_status_dot = QLabel("●")
        self.lbl_ws_status_dot.setStyleSheet("color: red; font-size: 16px;")
        self.lbl_ws_status = QLabel("Disconnected")
        self.btn_ws_connect = QPushButton("Connect")
        self.btn_ws_disconnect = QPushButton("Disconnect")
        self.btn_ws_disconnect.setEnabled(False)
        
        conn_layout.addWidget(self.lbl_ws_status_dot)
        conn_layout.addWidget(self.lbl_ws_status)
        conn_layout.addWidget(self.btn_ws_connect)
        conn_layout.addWidget(self.btn_ws_disconnect)
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # 2. Parameters Group
        param_group = QGroupBox("Parameters")
        form = QFormLayout()
        
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
        dev_layout = QGridLayout()
        
        self.lbl_ph_status_dot = QLabel("●")
        self.lbl_ph_status_dot.setStyleSheet("color: red; font-size: 16px;")
        self.lbl_ph_status = QLabel("Disconnected")
        self.btn_ph_connect = QPushButton("Connect")
        self.btn_ph_disconnect = QPushButton("Disconnect")
        self.btn_ph_disconnect.setEnabled(False)
        self.btn_ph_ctrl_panel = QPushButton("Control Panel")

        dev_layout.addWidget(self.lbl_ph_status_dot, 0, 0)
        dev_layout.addWidget(self.lbl_ph_status, 0, 1)
        dev_layout.addWidget(self.btn_ph_connect, 0, 2)
        dev_layout.addWidget(self.btn_ph_disconnect, 0, 3)
        dev_layout.addWidget(self.btn_ph_ctrl_panel, 0, 4)

        self.lbl_ph_res = QLabel("Res: -- ps")
        self.lbl_ph_res.setStyleSheet("font-family: Courier;")
        dev_layout.addWidget(self.lbl_ph_res, 1, 0, 1, 5)

        # Signals (QProgressBar 활용)
        dev_layout.addWidget(QLabel("Sync:"), 2, 0)
        self.prog_ph_sync = QProgressBar()
        self.prog_ph_sync.setTextVisible(False)
        self.prog_ph_sync.setFixedHeight(10)
        self.lbl_ph_sync_rate = QLabel("CH0: -- cps")
        dev_layout.addWidget(self.prog_ph_sync, 2, 1, 1, 3)
        dev_layout.addWidget(self.lbl_ph_sync_rate, 2, 4)

        dev_layout.addWidget(QLabel("Chan:"), 3, 0)
        self.prog_ph_chan = QProgressBar()
        self.prog_ph_chan.setTextVisible(False)
        self.prog_ph_chan.setFixedHeight(10)
        self.lbl_ph_chan_rate = QLabel("CH1: -- cps")
        dev_layout.addWidget(self.prog_ph_chan, 3, 1, 1, 3)
        dev_layout.addWidget(self.lbl_ph_chan_rate, 3, 4)

        dev_group.setLayout(dev_layout)
        layout.addWidget(dev_group)

        # 3. Histogram Scale
        scale_group = QGroupBox("Histogram Scale")
        scale_grid = QGridLayout()
        
        self.chk_ph_log = QCheckBox("Log Scale")
        self.chk_ph_log.setChecked(True)
        scale_grid.addWidget(self.chk_ph_log, 0, 0, 1, 2)

        self.chk_ph_xauto = QCheckBox("X Auto")
        self.chk_ph_xauto.setChecked(True)
        self.le_ph_xmin = QLineEdit("0")
        self.le_ph_xmax = QLineEdit("100")
        scale_grid.addWidget(self.chk_ph_xauto, 1, 0)
        scale_grid.addWidget(QLabel("min"), 1, 1)
        scale_grid.addWidget(self.le_ph_xmin, 1, 2)
        scale_grid.addWidget(QLabel("max"), 1, 3)
        scale_grid.addWidget(self.le_ph_xmax, 1, 4)

        self.chk_ph_yauto = QCheckBox("Y Auto")
        self.chk_ph_yauto.setChecked(True)
        self.le_ph_ymin = QLineEdit("1")
        self.le_ph_ymax = QLineEdit("100000")
        self.btn_ph_apply_scale = QPushButton("Apply")
        scale_grid.addWidget(self.chk_ph_yauto, 2, 0)
        scale_grid.addWidget(QLabel("min"), 2, 1)
        scale_grid.addWidget(self.le_ph_ymin, 2, 2)
        scale_grid.addWidget(QLabel("max"), 2, 3)
        scale_grid.addWidget(self.le_ph_ymax, 2, 4)
        scale_grid.addWidget(self.btn_ph_apply_scale, 2, 5)

        scale_group.setLayout(scale_grid)
        layout.addWidget(scale_group)

        # 4. Acquisition (QSpinBox 적용)
        acq_group = QGroupBox("Acquisition")
        acq_form = QFormLayout()

       
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
        group = QGroupBox("OBIS Lasers")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # 1. 통합 서버 연결부 (TCP Socket Connect)
        conn_layout = QHBoxLayout()
        self.le_obis_ip = QLineEdit(OBIS_IP) 
        self.btn_obis_connect = QPushButton("Connect Server")
        self.btn_obis_connect.setStyleSheet("font-weight: bold;")
        
        conn_layout.addWidget(QLabel("IP:"))
        conn_layout.addWidget(self.le_obis_ip)
        conn_layout.addWidget(self.btn_obis_connect)
        layout.addLayout(conn_layout)

        # 시각적 구분을 위한 수평선(Line)
        line = QLabel()
        line.setFrameShape(QLabel.HLine)
        line.setFrameShadow(QLabel.Sunken)
        layout.addWidget(line)

        # 2. 532nm 레이저 제어부 (오직 Emission ON/OFF만 담당)
        h_layout_532 = QHBoxLayout()
        self.btn_obis_532 = QPushButton("⚫ 532nm OFF")
        self.btn_obis_532.setFixedWidth(100)
        self.btn_obis_532.setEnabled(False) # 서버 연결 전까지는 조작 불가(Lock)
        
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
        self.btn_obis_633.setFixedWidth(100)
        self.btn_obis_633.setEnabled(False)
        
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