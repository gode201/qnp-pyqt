import matplotlib
matplotlib.use('Qt5Agg')

from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class APDCountWindow(QWidget):
    """
    실시간 APD Count를 플롯하는 독립 윈도우.
    AppController에서 이 클래스를 인스턴스화하여 .show()로 띄운다.
    """
    # 사용자가 창의 X 버튼을 눌러서 닫을 때 메인 컨트롤러로 알림을 보내는 시그널
    sig_closed = pyqtSignal()

    def __init__(self, parent=None):
        # Qt.Window 플래그를 주면 parent가 있어도 독립된 팝업 창으로 동작함
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("APD Count — Real-Time")
        self.resize(520, 360)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.fig = Figure(figsize=(5.2, 3.6))
        self.fig.tight_layout(pad=2.0)
        
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Real-Time Photon Count", fontsize=10)
        self.ax.set_xlabel("Time (s)", fontsize=9)
        self.ax.set_ylabel("Count / s", fontsize=9)
        self.ax.tick_params(labelsize=8)
        
        # 빈 데이터로 초기 라인 객체 생성
        self._line, = self.ax.plot([], [], color='blue', marker='o', markersize=3)

    def update_plot(self, apd_data):
        """
        Worker가 던져주는 데이터를 받아 플롯을 갱신한다.
        apd_data format: [[elapsed_s, cps], ...]
        """
        if not apd_data:
            return
        
        elapsed_times = [pt[0] for pt in apd_data]
        counts = [pt[1] for pt in apd_data]

        self._line.set_xdata(elapsed_times)
        self._line.set_ydata(counts)
        
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()

    def closeEvent(self, event):
        """
        PyQt5 내장 이벤트 오버라이드.
        창이 닫힐 때 sig_closed 시그널을 방출하여 Worker 스레드를 멈추게 유도함.
        """
        self.sig_closed.emit()
        super().closeEvent(event)