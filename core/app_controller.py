import sys
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QMetaObject, Qt, Q_ARG

from ui.apd_count_window import APDCountWindow

# UI 위젯들
from ui.left_panel_widget import LeftPanelWidget
from ui.center_plot_widget import CenterPlotWidget
from ui.right_panel_widget import RightPanelWidget

# 하드웨어 워커들 (현재 WinSpec만 완성됨)
from core.winspec_worker import WinSpecWorker
from core.daq_workers import PLScanWorker, ContinuousAPDWorker         
# from core.picoharp_worker import PicoHarpWorker 

class AppController(QObject):
    """
    애플리케이션의 메인 컨트롤러.
    모든 UI 이벤트 수신, Worker 스레드 관리, 데이터 흐름 라우팅을 담당한다.
    """
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
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

        # 2. DAQ & Piezo Worker 초기화 
        self.scan_thread = QThread()
        self.scan_worker = PLScanWorker()
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.start()

        
        self.apd_thread = QThread()
        self.apd_worker = ContinuousAPDWorker()
        self.apd_worker.moveToThread(self.apd_thread)
        self.apd_thread.start()

        # 3. PicoHarp Worker 초기화 (예정)

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
        # Left Panel (Scan / APD / Move) -> Controller
        # ==========================================
        # -- Scan / APD (구현 완료) --
        self.left_panel.btn_scan_start.clicked.connect(self.handle_scan_toggle)
        self.left_panel.btn_apd_count.clicked.connect(self.handle_apd_count_toggle)

        # ── Move Control (Galvo / Piezo) 연결 ──
        self.left_panel.btn_galvo_move.clicked.connect(self.handle_galvo_move)
        self.left_panel.btn_set_zero.clicked.connect(self.handle_galvo_set_zero)
        
        self.left_panel.btn_piezo_move.clicked.connect(self.handle_piezo_move)
        # Sub-window (APD Count) -> Controller
        # ==========================================
        # 창 닫힘 → 폴링 중단 & UI 원복
        # (apd_window 인스턴스 생성은 _init_subwindows()로 분리 권장)
        self.apd_window.sig_closed.connect(self._on_apd_window_closed)

        # ==========================================
        # PicoHarp Panel -> Controller (예정)
        # ==========================================
        # self.right_panel.btn_ph_start.clicked.connect(self.handle_ph_start)
        

    def _connect_workers_to_ui(self):
        # WinSpec
        self.ws_worker.sig_connected.connect(self._on_ws_connected)
        self.ws_worker.sig_disconnected.connect(self._on_ws_disconnected)
        self.ws_worker.sig_acquired.connect(self._on_ws_acquired)
        self.ws_worker.sig_progress.connect(self.right_panel.lbl_ws_info.setText)

        # PL Scan
        self.scan_worker.sig_scan_progress.connect(self.center_panel.update_pl_plot)
        self.scan_worker.sig_scan_finished.connect(self._on_scan_finished)
        self.scan_worker.sig_message.connect(self._on_worker_message)

        # APD (데이터 스트림만)
        self.apd_worker.sig_counts_updated.connect(self.apd_window.update_plot)



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
    def handle_galvo_move(self):
        """Galvo X, Y 수동 이동 명령"""
        try:
            x_um = float(self.left_panel.le_galvo_x.text())
            y_um = float(self.left_panel.le_galvo_y.text())
            
            # TODO: 나중에 Main Thread에서 단발성 DAQ AO Task를 실행하거나, 
            # Galvo 전용 Worker를 만들어 invokeMethod로 넘길 것.
            print(f"[Move] Galvo 이동: X={x_um}μm, Y={y_um}μm")
        except ValueError:
            pass

    def handle_galvo_set_zero(self):
        self.left_panel.le_galvo_x.setText("0.0")
        self.left_panel.le_galvo_y.setText("0.0")
        self.handle_galvo_move()

    def handle_piezo_move(self):
        """Piezo Z 수동 이동 명령"""
        try:
            z_um = float(self.left_panel.le_piezo_z.text())
            # TODO: Piezo Worker 연동 예정
            print(f"[Move] Piezo 이동: Z={z_um}μm")
        except ValueError:
            pass

        
    def _on_apd_window_closed(self):
        """APD 창의 X 버튼을 누르거나 코드로 close() 했을 때 상태 복구 및 스레드 종료"""
       
        if getattr(self.apd_worker, '_is_running', False):
            QMetaObject.invokeMethod(self.apd_worker, "stop_counting", Qt.QueuedConnection)
            
        # UI 상태 원복
        self.left_panel.btn_apd_count.setText("APD Count")
        self.main_window.status_left_label.setText("State: default")

    def handle_apd_count_toggle(self):
            """APD Count 창을 띄우고 폴링 스레드를 제어한다."""
            
            if getattr(self.apd_worker, '_is_running', False):
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
                    
                self.left_panel.btn_apd_count.setText("Stop APD")
                self.main_window.status_left_label.setText("State: apd_counting")
                QMetaObject.invokeMethod(self.apd_worker, "start_counting", 
                                        Qt.QueuedConnection, Q_ARG(float, expo), Q_ARG(int, 50))

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

        # 1-4. PicoHarp (예정) — 측정 중이면 stop 호출
        # try:
        #     if getattr(self.ph_worker, '_is_measuring', False):
        #         QMetaObject.invokeMethod(self.ph_worker, "stop_measurement",
        #                                  Qt.BlockingQueuedConnection)
        # except Exception as e:
        #     print(f"[shutdown] ph stop error: {e}")

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
        _stop_thread(getattr(self, 'scan_thread', None), "scan_thread")
        _stop_thread(getattr(self, 'ws_thread',   None), "ws_thread")
        # _stop_thread(getattr(self, 'ph_thread', None), "ph_thread")  # 예정

    