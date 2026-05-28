from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, 
                             QTabWidget, QGroupBox, QLabel, QLineEdit, QPushButton, 
                             QCheckBox, QSpinBox, QProgressBar, QToolButton,
                             QRadioButton, QButtonGroup) # QRadioButton, QButtonGroup 추가
from PyQt5.QtCore import pyqtSignal, Qt

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
            # [신규 추가] Global Center Plot View Mode
            # ---------------------------------------------------------------------
            view_group = QGroupBox("Center Plot View Mode")
            view_layout = QHBoxLayout()
            
            self.radio_view_ph = QRadioButton("PicoHarp Histogram")
            self.radio_view_ws = QRadioButton("WinSpec Spectrum")
            
            self.radio_view_ph.setChecked(True) # 기본값

            # 버튼 그룹으로 묶어서 상호 배타적(Exclusive)으로 동작하게 만듦
            self.view_btn_group = QButtonGroup()
            self.view_btn_group.addButton(self.radio_view_ph)
            self.view_btn_group.addButton(self.radio_view_ws)

            view_layout.addWidget(self.radio_view_ph)
            view_layout.addWidget(self.radio_view_ws)
            view_group.setLayout(view_layout)
            
            layout.addWidget(view_group) # 탭 위에 배치

            # 상태 변경 이벤트 연결
            self.radio_view_ph.clicked.connect(lambda: self.sig_view_mode_changed.emit("picoharp"))
            self.radio_view_ws.clicked.connect(lambda: self.sig_view_mode_changed.emit("winspec"))
            # ---------------------------------------------------------------------

            self.tabs = QTabWidget()
            self.winspec_tab = QWidget()
            self.picoharp_tab = QWidget()

            self._build_winspec_tab()
            self._build_picoharp_tab()

            self.tabs.addTab(self.winspec_tab, "WinSpec")
            self.tabs.addTab(self.picoharp_tab, "PicoHarp")

            layout.addWidget(self.tabs)

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
        
        self.le_ws_ip = QLineEdit("192.168.0.100") # WINSPEC_IP 기본값
        self.le_ws_prefix = QLineEdit("spectrum")
        
        exp_layout = QHBoxLayout()
        self.le_ws_exposure = QLineEdit("1.0")
        self.le_ws_accum = QLineEdit("1")
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
        
        self.le_ws_spe_dir = QLineEdit("C:/WinSpec_Data")
        self.le_ws_csv_dir = QLineEdit("./Data/Spectrum")
        
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

        # Tkinter의 억지스러운 버튼 증감을 QSpinBox로 깔끔하게 교체
        self.spin_ph_acqtime = QSpinBox()
        self.spin_ph_acqtime.setRange(1, 3600000)
        self.spin_ph_acqtime.setSingleStep(100)
        self.spin_ph_acqtime.setValue(1000)

        self.spin_ph_binning = QSpinBox()
        self.spin_ph_binning.setRange(0, 7)
        self.spin_ph_binning.setValue(0)

        self.spin_ph_offset = QSpinBox()
        self.spin_ph_offset.setRange(-500000, 500000)
        self.spin_ph_offset.setSingleStep(1000)
        self.spin_ph_offset.setValue(0)

        self.chk_ph_stop_ovf = QCheckBox("Stop on Overflow")

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
        self.spin_ph_t2_acqtime.setValue(10)
        
        dir_layout = QHBoxLayout()
        self.le_ph_t2_dir = QLineEdit("./Data/T2")
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
        if not self.radio_view_ws.isChecked():
            self.radio_view_ws.setChecked(True)
            self.sig_view_mode_changed.emit("winspec")

    def _auto_switch_to_picoharp(self):
        if not self.radio_view_ph.isChecked():
            self.radio_view_ph.setChecked(True)
            self.sig_view_mode_changed.emit("picoharp")