import sys
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QMetaObject, Qt, Q_ARG

from ui.apd_count_window import APDCountWindow

# UI 위젯들
from ui.left_panel_widget import LeftPanelWidget
from ui.center_plot_widget import CenterPlotWidget
from ui.right_panel_widget import RightPanelWidget
from ui.laser_config_dialog import LaserConfigDialog

# 하드웨어 워커들
from core.daq_workers import PLScanWorker, ContinuousAPDWorker, GalvoWorker
from core.winspec_worker import WinSpecWorker
from core.picoharp_worker import PicoHarpWorker 
from core.piezo_worker import PiezoWorker
from core.obis_worker import ObisWorker

class AppController(QObject):
    """
    애플리케이션의 메인 컨트롤러.
    모든 UI 이벤트 수신, Worker 스레드 관리, 데이터 흐름 라우팅을 담당한다.
    """
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        # --- 데이터 캐싱용 상태 변수 ---
        self._latest_pl_data = None
        self._latest_extent = None

        # 메인 윈도우에서 UI 컴포넌트 참조 가져오기
        self.left_panel: LeftPanelWidget = main_window.left_panel
        self.center_panel: CenterPlotWidget = main_window.center_panel
        self.right_panel: RightPanelWidget = main_window.right_panel

        # 워커 스레드 및 객체 초기화
        self._init_threads_and_workers()
        self._init_subwindows()
        # 시그널 라우팅
        self._connect_ui_to_controllers()
        self._connect_workers_to_ui()

    def _init_subwindows(self):
        self.apd_window = APDCountWindow()

    def _init_threads_and_workers(self):
        """Worker 객체를 생성하고 각각의 QThread로 밀어넣는다."""
        # 1. WinSpec Worker 초기화
        self.ws_thread = QThread()
        self.ws_worker = WinSpecWorker()
        self.ws_worker.moveToThread(self.ws_thread)
        self.ws_thread.start()

        # 2. DAQ Worker 초기화 
        self.scan_thread = QThread()
        self.scan_worker = PLScanWorker()
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.start()

        
        self.apd_thread = QThread()
        self.apd_worker = ContinuousAPDWorker()
        self.apd_worker.moveToThread(self.apd_thread)
        self.apd_thread.start()

        # 3. PicoHarp Worker 초기화 
        self.ph_thread = QThread()
        self.ph_worker = PicoHarpWorker()
        self.ph_worker.moveToThread(self.ph_thread)

        # 1) 히스토그램 데이터 -> 센터 플롯
        self.ph_worker.sig_histogram_updated.connect(self._on_ph_histogram_updated)
        # 2) 메시지 -> 좌측 패널 정보창
        self.ph_worker.sig_message.connect(self._on_worker_message)
        # 3) Count Rate -> 우측 패널 라벨 업데이트
        self.ph_worker.sig_count_rate_updated.connect(
            lambda sync, chan: (
                self.right_panel.lbl_ph_sync_rate.setText(f"CH0: {sync} cps"),
                self.right_panel.lbl_ph_chan_rate.setText(f"CH1: {chan} cps")
            )
        )
        # 4) 측정 완료 상태 복구
        self.ph_worker.sig_measurement_finished.connect(self._on_ph_finished)

        self.ph_thread.start()
        # 스레드 시작 후 장비 초기화 명령 하달
        QMetaObject.invokeMethod(self.ph_worker, "initialize", Qt.QueuedConnection)


        # 4. Galvo Move Worker 초기화
        self.galvo_thread = QThread()
        self.galvo_worker = GalvoWorker()
        self.galvo_worker.moveToThread(self.galvo_thread)
        
        # GalvoWorker의 메시지를 UI에 연결
        self.galvo_worker.sig_message.connect(self._on_worker_message)
        
        self.galvo_thread.start()

        # 5. Piezo Worker 초기화 및 배선
        self.piezo_thread = QThread()
        self.piezo_worker = PiezoWorker()
        self.piezo_worker.moveToThread(self.piezo_thread)
        self.piezo_worker.sig_message.connect(self._on_worker_message)
        
        # 폴링되어 올라오는 현재 Z 위치를 UI 레이블에 실시간으로 쏴줌
        self.piezo_worker.sig_position_updated.connect(
            lambda z: self.left_panel.lbl_piezo_live.setText(f"Z: {z:.3f} μm")
        )
        self.piezo_thread.start()
                # 스레드가 안전하게 뜬 후, 내부 타이머 생성을 위해 initialize 호출
        QMetaObject.invokeMethod(self.piezo_worker, "initialize", Qt.QueuedConnection)
        # 6. OBIS Laser Worker 초기화 및 배선
        self.obis_thread = QThread()
        self.obis_worker = ObisWorker()
        self.obis_worker.moveToThread(self.obis_thread)
        
        # 메시지는 왼쪽 패널 콘솔로 통일해서 쏜다
        self.obis_worker.sig_message.connect(self._on_worker_message)
        
        self.obis_thread.start()
        
        # 스레드가 안전하게 뜬 후, 내부 타이머 생성을 위해 initialize 호출
        QMetaObject.invokeMethod(self.obis_worker, "initialize", Qt.QueuedConnection)
        
        # 내부 상태 추적용 딕셔너리 (UI 토글 및 동기화 방어용)
        self._obis_state = {'connected': False, 'laser_532': False, 'laser_633': False}

    def _get_current_scan_params(self):
        """UI에서 스캔 파라미터를 추출하여 딕셔너리로 반환한다. 변환 실패 시 None 반환."""
        try:
            return {
                'x_min': float(self.left_panel.le_x_min.text()),
                'x_max': float(self.left_panel.le_x_max.text()),
                'y_min': float(self.left_panel.le_y_min.text()),
                'y_max': float(self.left_panel.le_y_max.text()),
                'x_steps': int(self.left_panel.le_x_steps.text()),
                'y_steps': int(self.left_panel.le_y_steps.text()),
                'exposure_time': float(self.left_panel.le_dwell.text()),
                'ao_sample_rate': float(self.left_panel.le_ao_rate.text()),
                'mode': self.left_panel.cb_scan_mode.currentText()
            }
        except ValueError as e:
            self.left_panel.lbl_scan_info.setText("Error: 파라미터 입력 오류 (숫자 아님)")
            self.left_panel.lbl_scan_info.setStyleSheet("color: red;")
            return None
        
    def _connect_ui_to_controllers(self):
        """UI에서 발생한 이벤트를 Controller의 처리 로직으로 연결"""

        # ==========================================
        # Right Panel (WinSpec) -> Controller
        # ==========================================

        self.right_panel.btn_ws_connect.clicked.connect(self.handle_ws_connect)
        self.right_panel.btn_ws_disconnect.clicked.connect(self.handle_ws_disconnect)
        self.right_panel.btn_ws_acquire.clicked.connect(self.handle_ws_acquire)

        # ==========================================
        # Right Panel (OBIS Lasers) -> Controller
        # ==========================================
        self.right_panel.btn_obis_connect.clicked.connect(self.handle_obis_connect)
        self.right_panel.btn_obis_532.clicked.connect(lambda: self.handle_obis_toggle('laser_532'))
        self.right_panel.btn_obis_633.clicked.connect(lambda: self.handle_obis_toggle('laser_633'))
        
        # 톱니바퀴 버튼 (팝업 호출)
        self.right_panel.btn_obis_532_cfg.clicked.connect(lambda: self.show_obis_config('laser_532'))
        self.right_panel.btn_obis_633_cfg.clicked.connect(lambda: self.show_obis_config('laser_633'))

        # ==========================================
        # Left Panel (Scan / APD / Move) -> Controller
        # ==========================================
        # -- image I/O  -- 
        self.left_panel.btn_save_image.clicked.connect(self.handle_save_image)
        self.left_panel.btn_export_data.clicked.connect(self.handle_export_data)
        self.left_panel.btn_import_data.clicked.connect(self.handle_import_data)

        # -- Scan / APD  --
        self.left_panel.btn_scan_start.clicked.connect(self.handle_scan_toggle)
        self.left_panel.btn_apd_count.clicked.connect(self.handle_apd_count_toggle)

        # ── Move Control (Galvo / Piezo) 연결 ──
        self.left_panel.btn_galvo_move.clicked.connect(self.handle_galvo_move)
        self.left_panel.btn_set_zero.clicked.connect(self.handle_galvo_set_zero)
        self.left_panel.btn_piezo_connect.clicked.connect(self.handle_piezo_connect)
        self.left_panel.btn_piezo_disconnect.clicked.connect(self.handle_piezo_disconnect)

        self.left_panel.btn_piezo_move.clicked.connect(self.handle_piezo_move)

        # Sub-window (APD Count) -> Controller
        # ==========================================
        # 창 닫힘 → 폴링 중단 & UI 원복
        # (apd_window 인스턴스 생성은 _init_subwindows()로 분리 권장)
        self.apd_window.sig_closed.connect(self._on_apd_window_closed)

        # ==========================================
        # PicoHarp Panel -> Controller 
        # ==========================================
        self.right_panel.btn_ph_start_hist.clicked.connect(self.handle_ph_start_hist)
        self.right_panel.btn_ph_stop.clicked.connect(self.handle_ph_stop)
        # btn_ph_start_t2 #히스토그램부터 성공하면 해제

        # ==========================================
        # Center Panel (Scan map click/ galvo) -> Controller
        # ==========================================
        self.center_panel.sig_map_clicked.connect(self.handle_map_clicked)
        self.left_panel.btn_up.clicked.connect(lambda: self.handle_galvo_arrow('up'))
        self.left_panel.btn_down.clicked.connect(lambda: self.handle_galvo_arrow('down'))
        self.left_panel.btn_left.clicked.connect(lambda: self.handle_galvo_arrow('left'))
        self.left_panel.btn_right.clicked.connect(lambda: self.handle_galvo_arrow('right'))

        # 🟢 메인 윈도우에서 낚아챈 전역 화살표 키 시그널 연결 추가
        self.main_window.sig_arrow_pressed.connect(self.handle_galvo_arrow)

    def _on_ph_histogram_updated(self, time_bins, counts):
        """PicoHarp 데이터를 메인 윈도우에 캐싱하고, 뷰 모드가 일치할 때만 플롯을 갱신한다."""
        # 1. 데이터 캐싱 (나중에 뷰를 전환했을 때 복구하기 위함)
        self.main_window._last_ph_hist_data = (time_bins, counts)
        
        # 2. 현재 우측 패널의 라디오 버튼 상태 확인
        # PicoHarp 모드일 때만 실시간으로 화면을 갱신함
        if self.right_panel.radio_view_ph.isChecked():
            self.center_panel.update_histogram(time_bins, counts)

    def _connect_workers_to_ui(self):
        # WinSpec
        self.ws_worker.sig_connected.connect(self._on_ws_connected)
        self.ws_worker.sig_disconnected.connect(self._on_ws_disconnected)
        self.ws_worker.sig_acquired.connect(self._on_ws_acquired)
        self.ws_worker.sig_progress.connect(self.right_panel.lbl_ws_info.setText)

        # PL Scan
        self.scan_worker.sig_scan_progress.connect(self._on_scan_progress)
        self.scan_worker.sig_scan_finished.connect(self._on_scan_finished)
        self.scan_worker.sig_message.connect(self._on_worker_message)

        # Galvo가 물리적 이동을 마치면(sig_moved), Center Panel의 원을 업데이트하도록 연동
        self.galvo_worker.sig_moved.connect(self.center_panel.update_galvo_indicator)

        # APD (데이터 스트림만)
        self.apd_worker.sig_counts_updated.connect(self.apd_window.update_plot)

        # OBIS Laser 상태 폴링 업데이트
        self.obis_worker.sig_status_updated.connect(self._on_obis_status_updated)


    # -------------------------------------------------------------------------
    # UI Action Handlers (명령 하달)
    # -------------------------------------------------------------------------
    def handle_ws_connect(self):
        ip = self.right_panel.le_ws_ip.text()
        self.right_panel.btn_ws_connect.setEnabled(False)
        # QMetaObject.invokeMethod를 쓰거나, 별도 커맨드 시그널을 만들어 Worker로 전달
        # 여기서는 워커의 슬롯을 직접 호출(비동기 큐에 삽입됨)
        
        QMetaObject.invokeMethod(self.ws_worker, "connect_device", 
                                 Qt.QueuedConnection, 
                                 Q_ARG(str, ip), Q_ARG(int, 9000))

    def handle_ws_disconnect(self):
        
        QMetaObject.invokeMethod(self.ws_worker, "disconnect_device", Qt.QueuedConnection)

    def handle_ws_acquire(self):
        params = {
            "exposure": float(self.right_panel.le_ws_exposure.text()),
            "accumulations": int(self.right_panel.le_ws_accum.text()),
            "spe_dir": self.right_panel.le_ws_spe_dir.text(),
            "csv_dir": self.right_panel.le_ws_csv_dir.text(),
            "prefix": self.right_panel.le_ws_prefix.text()
        }
        self.right_panel.btn_ws_acquire.setEnabled(False)
        
        QMetaObject.invokeMethod(self.ws_worker, "acquire_spectrum", 
                                 Qt.QueuedConnection, Q_ARG(dict, params))
    def handle_scan_toggle(self):
        """Scan Start / Stop 버튼 클릭 시 실행. 하드웨어 충돌 방지 및 파라미터 파싱."""
        

        # 1. 이미 스캔 중이면 중지 명령 하달
        if getattr(self.scan_worker, '_is_scanning', False):
            QMetaObject.invokeMethod(self.scan_worker, "stop_scan", Qt.QueuedConnection)
            self.left_panel.btn_scan_start.setText("Scan Start")
            self.left_panel.lbl_scan_info.setText("Stopping...")
            return

        # 2. 하드웨어 리소스 충돌 방지: APD 폴링이 돌고 있다면 강제 종료 (nidaqmx Dev2/ctr0 해제)
        if getattr(self.apd_worker, '_is_running', False):
            QMetaObject.invokeMethod(self.apd_worker, "stop_counting", Qt.QueuedConnection)

        # 3. 파라미터 추출 및 타입 변환 (Type Casting)
        params = self._get_current_scan_params()
        if params is None:
            return

        # 4. UI 상태 변경
        self.left_panel.btn_scan_start.setText("Scan Stop")
        self.left_panel.lbl_scan_info.setText(f"Scanning... ({params['mode']})")
        self.left_panel.lbl_scan_info.setStyleSheet("color: blue;")
        self.main_window.status_left_label.setText("State: scanning")

        # 5. 비동기 큐를 통해 Worker의 start_scan 호출
        QMetaObject.invokeMethod(self.scan_worker, "start_scan", 
                                 Qt.QueuedConnection, Q_ARG(dict, params))
  
    # -------------------------------------------------------------------------
    # Manual Move Handlers
    # -------------------------------------------------------------------------

    def handle_piezo_move(self):
        """Piezo Z 수동 이동 명령"""
        try:
            z_um = float(self.left_panel.le_piezo_z.text())
            # TODO: Piezo Worker 연동 예정
            print(f"[Move] Piezo 이동: Z={z_um}μm")
        except ValueError:
            pass

    def handle_piezo_connect(self):
        port = self.left_panel.le_piezo_port.text().strip()
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        QMetaObject.invokeMethod(self.piezo_worker, "connect_device", 
                                 Qt.QueuedConnection, Q_ARG(str, port))
        
        self.left_panel.btn_piezo_connect.setEnabled(False)
        self.left_panel.btn_piezo_disconnect.setEnabled(True)

    def handle_piezo_disconnect(self):
        from PyQt5.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self.piezo_worker, "disconnect_device", 
                                 Qt.QueuedConnection)
        
        self.left_panel.btn_piezo_connect.setEnabled(True)
        self.left_panel.btn_piezo_disconnect.setEnabled(False)

    def _on_apd_window_closed(self):
        """APD 창의 X 버튼을 누르거나 코드로 close() 했을 때 상태 복구 및 스레드 종료"""        
        QMetaObject.invokeMethod(self.apd_worker, "stop_counting", Qt.QueuedConnection)
            
        # UI 상태 원복
        self.left_panel.btn_apd_count.setText("APD Count")
        self.main_window.status_left_label.setText("State: default")

    def handle_apd_count_toggle(self):
            """APD Count 창을 띄우고 폴링 스레드를 제어한다."""
            
            if self.apd_window.isVisible():
                # 이미 실행 중이면 창을 닫는다. (창이 닫히면 _on_apd_window_closed가 연쇄적으로 호출됨)
                self.apd_window.close()
            else:
                # 스캔이 진행 중이면 실행 거부 (리소스 충돌 방지)
                if getattr(self.scan_worker, '_is_scanning', False):
                    self.left_panel.lbl_scan_info.setText("Error: 스캔 중에는 APD를 켤 수 없음.")
                    self.left_panel.lbl_scan_info.setStyleSheet("color: red;")
                    return
                    
                # 윈도우 띄우기
                self.apd_window.show()
                
                try:
                    expo = float(self.left_panel.le_dwell.text())
                except ValueError:
                    expo = 0.1
                    
                self.left_panel.btn_apd_count.setText("Stop Counting")
                self.main_window.status_left_label.setText("State: apd_counting")
                QMetaObject.invokeMethod(self.apd_worker, "start_counting", 
                                        Qt.QueuedConnection, Q_ARG(float, expo), Q_ARG(int, 50))

    # -------------------------------------------------------------------------
    # OBIS Laser Handlers
    # -------------------------------------------------------------------------
    def handle_obis_connect(self):
        """서버 연결 요청. (UI는 응답이 올 때까지 잠금 상태로 대기)"""
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        
        self.right_panel.btn_obis_connect.setEnabled(False) # 응답 올 때까지 연타 방지
        
        if not self._obis_state.get('connected', False):
            ip = self.right_panel.le_obis_ip.text().strip()
            self.right_panel.btn_obis_connect.setText("Connecting...")
            QMetaObject.invokeMethod(self.obis_worker, "connect_server", 
                                     Qt.QueuedConnection, Q_ARG(str, ip), Q_ARG(int, 9000))
        else:
            self.right_panel.btn_obis_connect.setText("Disconnecting...")
            QMetaObject.invokeMethod(self.obis_worker, "disconnect_server", Qt.QueuedConnection)
    
    def _on_obis_connection_changed(self, connected):
        """워커에서 물리적 연결 상태를 확정지었을 때 UI를 동기화한다."""
        self._obis_state['connected'] = connected
        self.right_panel.btn_obis_connect.setEnabled(True)
        
        if connected:
            self.right_panel.btn_obis_connect.setText("Disconnect Server")
            self.right_panel.btn_obis_532.setEnabled(True)
            self.right_panel.btn_obis_633.setEnabled(True)
            self.right_panel.btn_obis_532_cfg.setEnabled(True)
            self.right_panel.btn_obis_633_cfg.setEnabled(True)
        else:
            self.right_panel.btn_obis_connect.setText("Connect Server")
            self.right_panel.btn_obis_532.setEnabled(False)
            self.right_panel.btn_obis_633.setEnabled(False)
            self.right_panel.btn_obis_532_cfg.setEnabled(False)
            self.right_panel.btn_obis_633_cfg.setEnabled(False)
            
            # 서버가 다운되었을 때 남은 잔상 지우기 및 안전 초기화
            self.right_panel.btn_obis_532.setText("⚫ 532nm OFF")
            self.right_panel.btn_obis_532.setStyleSheet("")
            self.right_panel.lbl_obis_532_status.setText("--- mW [Offline]")
            
            self.right_panel.btn_obis_633.setText("⚫ 633nm OFF")
            self.right_panel.btn_obis_633.setStyleSheet("")
            self.right_panel.lbl_obis_633_status.setText("--- mW [Offline]")

    def handle_obis_toggle(self, target):
        """각 레이저의 Emission 상태를 토글(ON/OFF)한다."""
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        
        # 내부 상태 사전을 읽어 반대 상태(Not)를 명령으로 하달
        current_state = self._obis_state.get(target, False)
        new_state = not current_state
        
        QMetaObject.invokeMethod(self.obis_worker, "set_state", 
                                 Qt.QueuedConnection, Q_ARG(str, target), Q_ARG(bool, new_state))

    def show_obis_config(self, target):
        """팝업 다이얼로그를 띄워 파워를 설정한다 (Modal)"""
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        
        # 현재 UI 라벨에서 파워 값만 파싱(추출)해서 팝업의 기본값으로 넘김
        lbl = self.right_panel.lbl_obis_532_status if target == 'laser_532' else self.right_panel.lbl_obis_633_status
        txt = lbl.text()
        try:
            curr_pow = float(txt.split()[0])
        except (ValueError, IndexError):
            curr_pow = 0.0
            
        dialog = LaserConfigDialog(target_name=target, current_power=curr_pow, parent=self.main_window)
        
        # 모달 창이 열려있는 동안 메인 UI 루프는 대기하지만, 
        # 백그라운드 폴링(Polling) 스레드는 멈추지 않으므로 Race Condition을 우회할 수 있음.
        if dialog.exec_() == dialog.Accepted:
            new_power = dialog.get_power()
            QMetaObject.invokeMethod(self.obis_worker, "set_power", 
                                     Qt.QueuedConnection, Q_ARG(str, target), Q_ARG(float, new_power))

    def _on_obis_status_updated(self, data):
        """워커의 폴링 데이터를 해석하여 2초마다 UI 라벨과 버튼의 디자인을 갱신한다."""
        for target, btn, lbl in [
            ('laser_532', self.right_panel.btn_obis_532, self.right_panel.lbl_obis_532_status),
            ('laser_633', self.right_panel.btn_obis_633, self.right_panel.lbl_obis_633_status)
        ]:
            info = data.get(target)
            if info is None:
                continue
                
            power = info.get('power', 0.0)
            is_on = info.get('emission', False)
            interlock = info.get('interlock', 'Unknown')
            
            # 동기화 락(Lock)을 위해 내부 상태 갱신
            self._obis_state[target] = is_on
            
            lbl.setText(f"{power:.1f} mW [{interlock}]")
            
            if is_on:
                btn.setText(f"⚡ {target.split('_')[1]}nm ON")
                btn.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold;")
            else:
                btn.setText(f"⚫ {target.split('_')[1]}nm OFF")
                btn.setStyleSheet("")



    # -------------------------------------------------------------------------
    # Worker Callbacks (상태 갱신)
    # -------------------------------------------------------------------------
    def _on_ws_connected(self, success, msg):
        if success:
            self.right_panel.lbl_ws_status.setText("Connected")
            self.right_panel.lbl_ws_status_dot.setStyleSheet("color: green; font-size: 16px;")
            self.right_panel.btn_ws_disconnect.setEnabled(True)
        else:
            self.right_panel.lbl_ws_status.setText("Failed")
            self.right_panel.btn_ws_connect.setEnabled(True)
        self.right_panel.lbl_ws_info.setText(msg)

    def _on_ws_disconnected(self):
        self.right_panel.lbl_ws_status.setText("Disconnected")
        self.right_panel.lbl_ws_status_dot.setStyleSheet("color: red; font-size: 16px;")
        self.right_panel.btn_ws_connect.setEnabled(True)
        self.right_panel.btn_ws_disconnect.setEnabled(False)

    def _on_ws_acquired(self, success, result):
        self.right_panel.btn_ws_acquire.setEnabled(True)
        if success:
            csv_path = result.get("csv_path")
            self.right_panel.lbl_ws_info.setText(f"Saved: {result.get('fname')}")
            # TODO: csv_path를 읽어서 CenterPlotWidget의 ax_hist에 스펙트럼 플롯하도록 연결
        else:
            self.right_panel.lbl_ws_info.setText(f"Error: {result.get('error')}")


    # -------------------------------------------------------------------------
    # Data Caching & I/O Handlers
    # -------------------------------------------------------------------------
    def _on_scan_progress(self, pl_data_grid, extent):
        """스캔 진행 시 컨트롤러에 데이터를 캐싱하고 UI를 업데이트한다."""
        self._latest_pl_data = pl_data_grid
        self._latest_extent = extent
        self.center_panel.update_pl_plot(pl_data_grid, extent)

    def handle_export_data(self):
        """현재 캐싱된 PL 맵 데이터를 구형 호환 포맷([RANGE], [STEPS], [PL_DATA])으로 내보낸다."""
        if self._latest_pl_data is None or self._latest_extent is None:
            self.left_panel.lbl_image_info.setText("Error: 내보낼 데이터가 없음.")
            self.left_panel.lbl_image_info.setStyleSheet("color: red;")
            return

        from PyQt5.QtWidgets import QFileDialog
        import numpy as np

        options = QFileDialog.Options()
        filepath, _ = QFileDialog.getSaveFileName(
            self.main_window, 
            "Save PL Data", 
            "", 
            "Text Files (*.txt);;CSV Files (*.csv)", 
            options=options
        )

        if not filepath:
            return

        try:
            x_min, x_max, y_min, y_max = self._latest_extent
            y_steps, x_steps = self._latest_pl_data.shape

            # 좌표 배열 생성
            x_arr = np.linspace(x_min, x_max, x_steps)
            y_arr = np.linspace(y_min, y_max, y_steps)

            with open(filepath, 'w', encoding='utf-8') as f:
                # 1. 메타데이터 작성
                f.write("[RANGE]\n")
                f.write(f"X Range: {x_min:.3f} to {x_max:.3f} μm\n")
                f.write(f"Y Range: {y_min:.3f} to {y_max:.3f} μm\n\n")

                f.write("[STEPS]\n")
                f.write(f"X Steps: {x_steps}\n")
                f.write(f"Y Steps: {y_steps}\n\n")

                # 2. 데이터 라인 작성
                f.write("[PL_DATA]\n")
                f.write("X (μm), Y (μm), Count\n")
                
                for j, y_val in enumerate(y_arr):
                    for i, x_val in enumerate(x_arr):
                        pl_val = self._latest_pl_data[j, i]
                        # 결측치(NaN) 방어
                        if np.isnan(pl_val):
                            pl_val = 0.0
                        f.write(f"{x_val:.3f}, {y_val:.3f}, {pl_val:.3f}\n")

            self.left_panel.lbl_image_info.setText(f"Exported: {filepath}")
            self.left_panel.lbl_image_info.setStyleSheet("color: green;")
        except Exception as e:
            self.left_panel.lbl_image_info.setText(f"Export Error: {e}")
            self.left_panel.lbl_image_info.setStyleSheet("color: red;")

    def handle_save_image(self):
        """현재 CenterPlotWidget의 PL 맵(ax2) 플롯 레이블을 수정하고, PNG 이미지로 잘라서 저장한다."""
        if self._latest_pl_data is None:
            self.left_panel.lbl_image_info.setText("Error: 저장할 이미지 데이터가 없음.")
            self.left_panel.lbl_image_info.setStyleSheet("color: red;")
            return

        from PyQt5.QtWidgets import QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QFileDialog
        from matplotlib.transforms import Bbox
        import os
        
        # [타겟 수정] 하단 PL 맵 축인 ax2를 타겟으로 지정한다.
        target_ax = self.center_panel.ax2 

        # 1. 텍스트 입력을 위한 커스텀 다이얼로그 생성
        dialog = QDialog(self.main_window)
        dialog.setWindowTitle("Set PL Map Labels & Title")
        layout = QFormLayout(dialog)
        
        current_title = target_ax.get_title()
        current_xlabel = target_ax.get_xlabel()
        current_ylabel = target_ax.get_ylabel()
        
        le_title = QLineEdit(current_title if current_title else "PL Scanning Image")
        le_xlabel = QLineEdit(current_xlabel if current_xlabel else "X (μm)")
        le_ylabel = QLineEdit(current_ylabel if current_ylabel else "Y (μm)")
        
        layout.addRow("Plot Title:", le_title)
        layout.addRow("X-axis Label:", le_xlabel)
        layout.addRow("Y-axis Label:", le_ylabel)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        
        # 사용자가 취소하면 중단
        if dialog.exec_() != QDialog.Accepted:
            return 
            
        # 2. 입력받은 레이블로 PL 맵 업데이트
        target_ax.set_title(le_title.text(), fontsize=12)
        target_ax.set_xlabel(le_xlabel.text())
        target_ax.set_ylabel(le_ylabel.text())
        self.center_panel.canvas.draw()
        
        # 3. 파일 저장 팝업
    
        options = QFileDialog.Options()
        filepath, selected_filter = QFileDialog.getSaveFileName(
            self.main_window, 
            "Save PL Data Image", 
            "", 
            "PNG Images (*.png);;JPEG Images (*.jpg *.jpeg)", 
            options=options
        )
        
        if filepath:
            # [유령 파일 방지] selectedFilter + splitext 기반 확장자 정규화
            if "JPEG" in selected_filter:
                target_ext, fmt_default = ".jpg", "jpg"
            else:
                target_ext, fmt_default = ".png", "png"

            root, ext = os.path.splitext(filepath)
            ext_lower = ext.lower()

            if ext_lower not in (".png", ".jpg", ".jpeg"):
                filepath = filepath + target_ext
                fmt_final = fmt_default
            else:
                fmt_final = "jpg" if ext_lower in (".jpg", ".jpeg") else "png"

            try:
                # 4. 정밀 렌더링 로직
                
                # 상단의 불필요한 플롯들을 일시적으로 숨김 처리
                self.center_panel.ax1.set_visible(False)
                self.center_panel.ax_hist.set_visible(False)
                
                # 이 상태로 'tight'를 주면 화면에 살아남은 PL 맵(ax2)과 컬러바만 완벽하게 잘려서 저장됨
                self.center_panel.fig.savefig(
                    filepath, dpi=300, bbox_inches='tight', format=fmt_final
                )
                
                # 저장 직후 다시 화면 복구
                self.center_panel.ax1.set_visible(True)
                self.center_panel.ax_hist.set_visible(True)
                self.center_panel.canvas.draw()

                self.left_panel.lbl_image_info.setText(f"Image Saved: {os.path.basename(filepath)}")
                self.left_panel.lbl_image_info.setStyleSheet("color: green;")
                
            except Exception as e:
                # 에러가 났을 때도 화면이 꺼진 채로 멈추지 않도록 무조건 복구
                self.center_panel.ax1.set_visible(True)
                self.center_panel.ax_hist.set_visible(True)
                self.center_panel.canvas.draw()
                
                self.left_panel.lbl_image_info.setText(f"Save Image Error: {e}")
                self.left_panel.lbl_image_info.setStyleSheet("color: red;")
                print(f"[Save Image Error Traceback] {e}")
    
    def handle_import_data(self):
        """저장된 PL 맵 데이터(구형 메타데이터 포함)를 불러와서 화면에 플롯한다."""
        from PyQt5.QtWidgets import QFileDialog
        import numpy as np

        options = QFileDialog.Options()
        filepath, _ = QFileDialog.getOpenFileName(
            self.main_window, 
            "Load PL Data", 
            "", 
            "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)", 
            options=options
        )

        if not filepath:
            return

        in_section = None
        pl_data_list = []
        x_min, x_max, y_min, y_max = None, None, None, None
        x_steps, y_steps = None, None

        try:
            # 1. 인코딩 호환성 처리 (cp949, utf-8-sig 등)
            for enc in ("utf-8-sig", "cp949", "latin-1"):
                try:
                    with open(filepath, "r", encoding=enc) as file:
                        lines = file.readlines()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "파일 인코딩 감지 실패")

            # 2. 파일 파싱
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if line.startswith("[") and line.endswith("]"):
                    in_section = line
                    continue

                if in_section == "[RANGE]":
                    if "X Range" in line:
                        parts = line.split(":")[1].replace("μm", "").strip().split("to")
                        x_min, x_max = map(float, parts)
                    elif "Y Range" in line:
                        parts = line.split(":")[1].replace("μm", "").strip().split("to")
                        y_min, y_max = map(float, parts)

                elif in_section == "[STEPS]":
                    if "X Steps" in line:
                        x_steps = int(line.split(":")[1].strip())
                    elif "Y Steps" in line:
                        y_steps = int(line.split(":")[1].strip())

                elif in_section == "[PL_DATA]":
                    if "X (" in line or "Count" in line:
                        continue
                    try:
                        x, y, value = map(float, line.split(","))
                        pl_data_list.append([x, y, value])
                    except ValueError:
                        continue # 빈 줄이나 포맷 깨진 줄 무시

            if not pl_data_list:
                raise ValueError("PL 데이터가 비어있거나 파일이 손상됨.")

            # 3. 데이터 그리드 재조립 (네가 짰던 딕셔너리 매핑 방식 재활용)
            unique_x = np.unique([d[0] for d in pl_data_list])
            unique_y = np.unique([d[1] for d in pl_data_list])
            
            # 파라미터에서 step을 못 읽었다면 실제 데이터 길이로 덮어쓰기
            actual_x_steps = len(unique_x)
            actual_y_steps = len(unique_y)

            pl_data_grid = np.full((actual_y_steps, actual_x_steps), np.nan)
            x_map = {v: i for i, v in enumerate(unique_x)}
            y_map = {v: i for i, v in enumerate(unique_y)}

            for x, y, value in pl_data_list:
                pl_data_grid[y_map[y], x_map[x]] = value

            # 4. 캐싱 및 UI 업데이트
            self._latest_pl_data = pl_data_grid
            
            # 메타데이터에 min/max가 없었을 경우 실제 데이터 기준 산출
            if None in (x_min, x_max, y_min, y_max):
                self._latest_extent = (unique_x.min(), unique_x.max(), unique_y.min(), unique_y.max())
            else:
                self._latest_extent = (x_min, x_max, y_min, y_max)

            # 좌측 패널 입력창 파라미터 동기화
            self.left_panel.le_x_min.setText(f"{self._latest_extent[0]:.3f}")
            self.left_panel.le_x_max.setText(f"{self._latest_extent[1]:.3f}")
            self.left_panel.le_y_min.setText(f"{self._latest_extent[2]:.3f}")
            self.left_panel.le_y_max.setText(f"{self._latest_extent[3]:.3f}")
            self.left_panel.le_x_steps.setText(str(actual_x_steps))
            self.left_panel.le_y_steps.setText(str(actual_y_steps))

            self.center_panel.update_pl_plot(self._latest_pl_data, self._latest_extent)
            
            self.left_panel.lbl_image_info.setText(f"Imported: {filepath.split('/')[-1]}")
            self.left_panel.lbl_image_info.setStyleSheet("color: blue;")

        except Exception as e:
            self.left_panel.lbl_image_info.setText(f"Import Error: {e}")
            self.left_panel.lbl_image_info.setStyleSheet("color: red;")
            print(f"[Import Error Traceback] {e}")


    def _on_scan_finished(self, success, result_msg):
            """스캔 루프가 종료(정상 완료 또는 에러/중단)되었을 때 호출됨"""
            self.left_panel.btn_scan_start.setText("Scan Start")
            self.main_window.status_left_label.setText("State: default")
            
            if success:
                self.left_panel.lbl_scan_info.setText(f"Done: {result_msg}")
                self.left_panel.lbl_scan_info.setStyleSheet("color: green;")
                
                # 스캔 종료 후 WinSpec 자동 획득 로직 연동
                if self.right_panel.chk_ws_auto.isChecked():
                    self.handle_ws_acquire()
            else:
                self.left_panel.lbl_scan_info.setText("Scan aborted/failed.")
                self.left_panel.lbl_scan_info.setStyleSheet("color: red;")

    def _on_worker_message(self, level, msg):
        """워커에서 보내는 일반 상태 메시지 처리"""
        if level == "error":
            self.left_panel.lbl_scan_info.setText(f"Error: {msg}")
            self.left_panel.lbl_scan_info.setStyleSheet("color: red;")
        else:
            self.left_panel.lbl_scan_info.setText(msg)
            self.left_panel.lbl_scan_info.setStyleSheet("color: gray;")

    # -------------------------------------------------------------------------
    # PicoHarp Handlers
    # -------------------------------------------------------------------------
    def handle_ph_start_hist(self):
        """PicoHarp Histogram 측정 시작 명령을 내리고 UI를 잠근다."""
        params = {
            'acqtime_ms': self.right_panel.spin_ph_acqtime.value(),
            'binning': self.right_panel.spin_ph_binning.value(),
            'offset_ps': self.right_panel.spin_ph_offset.value(),
            'stop_overflow': self.right_panel.chk_ph_stop_ovf.isChecked()
        }
        
        # 버튼 상태 변경 (중복 실행 방지)
        self.right_panel.btn_ph_start_hist.setEnabled(False)
        self.right_panel.btn_ph_start_t2.setEnabled(False)
        self.right_panel.btn_ph_stop.setEnabled(True)
        
        QMetaObject.invokeMethod(self.ph_worker, "start_measurement", 
                                 Qt.QueuedConnection, Q_ARG(dict, params))

    def handle_ph_stop(self):
        """PicoHarp 측정 강제 중단 명령"""
        QMetaObject.invokeMethod(self.ph_worker, "stop_measurement", Qt.QueuedConnection)

    def _on_ph_finished(self, mode):
        """측정이 정상 완료되거나 중단되었을 때 버튼 상태를 복구한다."""
        self.right_panel.btn_ph_start_hist.setEnabled(True)
        self.right_panel.btn_ph_start_t2.setEnabled(True)
        self.right_panel.btn_ph_stop.setEnabled(False)

    # -------------------------------------------------------------------------
    # Galvo Move: 통합 진입점 (Single Source of Truth)
    # -------------------------------------------------------------------------
    def _commit_galvo_move(self, x_um, y_um):
        """
        Galvo 이동의 유일한 진입점.
        맵 클릭, 화살표 패드, Move 버튼, Zero 버튼 등 모든 경로가 여기로 모인다.
        """
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        
        # 1. UI 파라미터 강제 동기화 (입력창 갱신)
        self.left_panel.le_galvo_x.setText(f"{x_um:.3f}")
        self.left_panel.le_galvo_y.setText(f"{y_um:.3f}")
        
        # 2. 회색 점선 마커로 이동 '예정' 지점 즉시 표시 (Optimistic UI)
        self.center_panel.set_galvo_target(x_um, y_um)
        
        # 3. 데이터 Read-out: 현재 화면에 PL 데이터가 로드되어 있다면, 해당 좌표의 Count 추출
        if getattr(self, '_latest_pl_data', None) is not None and getattr(self, '_latest_extent', None) is not None:
            import numpy as np
            x_min, x_max, y_min, y_max = self._latest_extent
            y_steps, x_steps = self._latest_pl_data.shape
            
            # 물리적 좌표(um)를 배열의 인덱스(Pixel)로 역산출
            col = int(np.clip((x_um - x_min) / (x_max - x_min) * (x_steps - 1) if x_max != x_min else 0, 0, x_steps - 1))
            row = int(np.clip((y_um - y_min) / (y_max - y_min) * (y_steps - 1) if y_max != y_min else 0, 0, y_steps - 1))
            
            val = self._latest_pl_data[row, col]
            
            # Image 탭의 로그 라벨에 좌표와 카운트 수 렌더링
            self.left_panel.lbl_image_info.setText(f"[Point Read] X: {x_um:.3f}, Y: {y_um:.3f} | Count: {val:.1f}")
            self.left_panel.lbl_image_info.setStyleSheet("color: magenta; font-weight: bold;")
            
        # 4. 하드웨어 워커로 비동기 큐잉 (온/오프라인 판단은 Worker가 알아서 함)
        QMetaObject.invokeMethod(
            self.galvo_worker, "move_to", Qt.QueuedConnection,
            Q_ARG(float, x_um), Q_ARG(float, y_um)
        )

    # -------------------------------------------------------------------------
    # Manual Move Handlers (프록시 핸들러들)
    # -------------------------------------------------------------------------
    def handle_map_clicked(self, x, y):
        """PL 맵 클릭 이벤트"""
        self._commit_galvo_move(x, y)

    def handle_galvo_move(self):
        """UI Move 버튼 이벤트"""
        try:
            x_um = float(self.left_panel.le_galvo_x.text())
            y_um = float(self.left_panel.le_galvo_y.text())
            self._commit_galvo_move(x_um, y_um)
        except ValueError:
            self.left_panel.lbl_scan_info.setText("Error: 좌표는 숫자여야 함.")
            self.left_panel.lbl_scan_info.setStyleSheet("color: red;")

    def handle_galvo_set_zero(self):
        """UI Zero 버튼 이벤트"""
        self._commit_galvo_move(0.0, 0.0)

    def handle_galvo_arrow(self, direction):
        """화살표 키/버튼 이벤트"""
        try:
            x = float(self.left_panel.le_galvo_x.text())
            y = float(self.left_panel.le_galvo_y.text())
            
            try:
                step = float(self.left_panel.le_galvo_step.text())
            except ValueError:
                # 사용자가 빈칸으로 두거나 이상한 문자를 넣었을 경우의 방어 로직
                step = 0.5 
                self.left_panel.le_galvo_step.setText("0.5")
            
            if direction == 'up': y += step
            elif direction == 'down': y -= step
            elif direction == 'left': x -= step
            elif direction == 'right': x += step
            
            self._commit_galvo_move(x, y)
            
        except ValueError:
            self.left_panel.lbl_image_info.setText("Error: Galvo 수동 제어 전 좌표를 확인하라.")
            self.left_panel.lbl_image_info.setStyleSheet("color: red;")




    def shutdown(self):
        """애플리케이션 종료 시 호출되어 모든 스레드를 안전하게 정리한다."""

        # ---------------------------------------------------------------
        # 1. 진행 중인 작업 선제 중단 (blocking I/O 풀어주기)
        # ---------------------------------------------------------------
        # 1-1. APD 폴링 중단 + 창 닫기
        try:
            if getattr(self.apd_worker, '_is_running', False):
                # DirectConnection으로 즉시 플래그를 내려서 polling loop 탈출 유도
                QMetaObject.invokeMethod(self.apd_worker, "stop_counting",
                                        Qt.BlockingQueuedConnection)
        except Exception as e:
            print(f"[shutdown] apd stop error: {e}")

        try:
            if self.apd_window is not None:
                # sig_closed 재진입 방지를 위해 시그널 연결 끊고 닫기
                try:
                    self.apd_window.sig_closed.disconnect(self._on_apd_window_closed)
                except (TypeError, RuntimeError):
                    pass
                self.apd_window.close()
        except Exception as e:
            print(f"[shutdown] apd window close error: {e}")

        # 1-2. PL Scan 중단
        try:
            if getattr(self.scan_worker, '_is_scanning', False):
                QMetaObject.invokeMethod(self.scan_worker, "stop_scan",
                                        Qt.BlockingQueuedConnection)
        except Exception as e:
            print(f"[shutdown] scan stop error: {e}")

        # 1-3. WinSpec 소켓 disconnect (recv blocking 해제)
        try:
            QMetaObject.invokeMethod(self.ws_worker, "disconnect_device",
                                    Qt.BlockingQueuedConnection)
        except Exception as e:
            print(f"[shutdown] ws disconnect error: {e}")

        #1-4. PicoHarp (측정 중이면 stop 호출)
        try:
            if getattr(self.ph_worker, '_is_measuring', False):
                QMetaObject.invokeMethod(self.ph_worker, "stop_measurement",
                                         Qt.BlockingQueuedConnection)
                # DLL 메모리 누수 및 포트 Lock 방지를 위한 명시적 연결 해제
            QMetaObject.invokeMethod(self.ph_worker, "close_connection",
                                    Qt.BlockingQueuedConnection)
        except Exception as e:
            print(f"[shutdown] ph stop error: {e}")

        # 1-5. Piezo disconnect (시리얼 포트 안전 해제 및 폴링 타이머 중단)
        try:
            QMetaObject.invokeMethod(self.piezo_worker, "disconnect_device",
                                     Qt.BlockingQueuedConnection)
        except Exception as e:
            print(f"[shutdown] piezo disconnect error: {e}")

        # 1-6. OBIS Server disconnect
        try:
            QMetaObject.invokeMethod(self.obis_worker, "disconnect_server",
                                     Qt.BlockingQueuedConnection)
        except Exception as e:
            print(f"[shutdown] obis disconnect error: {e}")
        # ---------------------------------------------------------------
        # 2. 스레드 종료 (quit → wait, 타임아웃으로 데드락 방지)
        # ---------------------------------------------------------------
        WAIT_MS = 3000  # 3초 후에도 안 끝나면 강제 종료

        def _stop_thread(thread, name):
            if thread is None:
                return
            try:
                thread.quit()
                if not thread.wait(WAIT_MS):
                    print(f"[shutdown] {name} did not quit in {WAIT_MS}ms; terminating.")
                    thread.terminate()
                    thread.wait()
            except Exception as e:
                print(f"[shutdown] {name} cleanup error: {e}")

        _stop_thread(getattr(self, 'apd_thread',  None), "apd_thread")
        _stop_thread(getattr(self, 'galvo_thread', None), "galvo_thread")
        _stop_thread(getattr(self, 'scan_thread', None), "scan_thread")
        _stop_thread(getattr(self, 'ws_thread',   None), "ws_thread")
        _stop_thread(getattr(self, 'ph_thread', None), "ph_thread") 
        _stop_thread(getattr(self, 'piezo_thread', None), "piezo_thread")
        _stop_thread(getattr(self, 'obis_thread', None), "obis_thread")
    