import numpy as np
import matplotlib
matplotlib.use('Qt5Agg')

from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtCore import pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt

class CenterPlotWidget(QWidget):
    """
    Matplotlib 기반의 데이터 시각화를 전담하는 독립 위젯.
    외부 컴포넌트는 axes에 직접 접근하지 않고, 제공되는 메서드를 통해서만 플롯을 업데이트해야 함.
    """

    sig_map_clicked = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._init_plots()

    def _setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        dpi = self.logicalDpiX()
        self.fig = Figure(figsize=(10, 9), dpi=dpi)
        
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.layout.addWidget(self.canvas)

    def _init_plots(self):
        """기존 2x2 gridspec 구조 복원 (상단 APD/Hist, 하단 PL Image)"""
        spec = self.fig.add_gridspec(2, 2, height_ratios=[1, 3], width_ratios=[1, 2])

        # 1. Z Scan / Auto-Focus (상단 좌측)
        self.ax1 = self.fig.add_subplot(spec[0, 0])
        self.ax1.set_title("Z Scan / Auto-Focus", fontsize=9)
        self.ax1.set_xlabel("Z (μm)", fontsize=8)
        self.ax1.set_ylabel("Count / s", fontsize=8)
        self.ax1.tick_params(labelsize=7)

        # 2. PicoHarp Histogram (상단 우측)
        self.ax_hist = self.fig.add_subplot(spec[0, 1])
        self.ax_hist.set_title("PicoHarp Histogram", fontsize=9)
        self.ax_hist.set_xlabel("Time (ns)", fontsize=8)
        self.ax_hist.set_ylabel("Counts", fontsize=8)
        self.ax_hist.tick_params(labelsize=7)
        self.ax_hist.set_yscale("log")
        self.ax_hist.set_xlim(0, 100)
        self.ax_hist.set_ylim(0.5, 1e5)
        self._hist_line, = self.ax_hist.plot([0], [1], color='steelblue', lw=1)

        # 3. PL Scanning Image (하단 전체)
        self.ax2 = self.fig.add_subplot(spec[1, :])
        self.ax2.set_box_aspect(1)
        self.ax2.set_title("PL Scanning Image")
        self.ax2.set_xlabel("X (μm)")
        self.ax2.set_ylabel("Y (μm)")
        
        #========================================================
        # Galvo Indicator
        #========================================================
        # 현재 물리적 위치 (청록색 실선 원)
        self.galvo_indicator = plt.Circle(
            (0, 0), 1.0, color='cyan', fill=False, lw=2, zorder=10
        )
        self.ax2.add_patch(self.galvo_indicator)
        # 이동 예정인 타겟 위치 (회색 점선 원 - 초기엔 숨김)
        self.galvo_target_indicator = plt.Circle(
            (0, 0), 1.0, color='gray', linestyle='--', fill=False, lw=1, zorder=9
        )
        self.ax2.add_patch(self.galvo_target_indicator)
        self.galvo_target_indicator.set_visible(False)
        
        self.canvas.mpl_connect('button_press_event', self._on_canvas_clicked)

        # Colorbar 초기화 (Dummy 데이터)
        dummy = plt.cm.ScalarMappable(cmap='gist_heat')
        self.cbar = self.fig.colorbar(dummy, ax=self.ax2, fraction=0.046, pad=0.04)

        # 객체 상태 변수
        self._pl_img = None
        self._pl_img_extent = None
        
        self.fig.tight_layout(pad=1.5)

    def update_pl_plot(self, pl_data_grid, extent, cmap_name='gist_heat', norm=None, vmin=None, vmax=None):
        """
        PL Image 업데이트 함수. 
        이전 코드의 복잡한 조건문(need_rebuild) 로직을 이곳에 캡슐화(Encapsulation)함.
        """
        if pl_data_grid is None:
            return

        cmap = plt.get_cmap(cmap_name)
        
        if self._pl_img is None or self._pl_img_extent != extent:
            self.ax2.clear()
            self._pl_img = self.ax2.imshow(
                pl_data_grid, cmap=cmap, origin='lower', extent=extent,
                norm=norm, vmin=vmin, vmax=vmax, interpolation='nearest'
            )
            self._pl_img_extent = extent
            self.cbar.update_normal(self._pl_img)
            self.ax2.set_xlabel("X (μm)")
            self.ax2.set_ylabel("Y (μm)")
            self.ax2.set_title("PL Scanning Image")
            self.ax2.add_patch(self.galvo_indicator)
            self.ax2.add_patch(self.galvo_target_indicator)
        else:
            self._pl_img.set_data(pl_data_grid)
            if norm is None:
                if vmin is not None and vmax is not None:
                    self._pl_img.set_clim(vmin, vmax)
                else:
                    self._pl_img.autoscale()
            self._pl_img.set_cmap(cmap)
        
        self.canvas.draw_idle()

    # -------------------------------------------------------------------------
    # Z Scan / Auto Focus 플롯
    # -------------------------------------------------------------------------
    def update_zscan_plot(self, data):
        """
        1D Z-Scan 그래프 렌더링.
        data: list of (z_um, counts_per_sec)
        """
        if not data:
            return
            
        z_arr = [d[0] for d in data]
        cps_arr = [d[1] for d in data]
        
        self.ax1.clear()
        self.ax1.plot(z_arr, cps_arr, "o-", markersize=3, color="steelblue")
        self.ax1.set_title("1D Z Scan", fontsize=9)
        self.ax1.set_xlabel("Z (μm)", fontsize=8)
        self.ax1.set_ylabel("Count / s", fontsize=8)
        self.ax1.tick_params(labelsize=7)
        self.canvas.draw_idle()

    def update_autofocus_plot(self, result):
        """
        Auto-Focus 2-Pass 스캔 및 타겟 Z 위치 결과 렌더링.
        result: z_autofocus.run_autofocus()가 반환한 딕셔너리
        """
        if not result:
            return
            
        self.ax1.clear()
        
        mode = result.get("focus_mode", "plateau_center")
        
        # Fine 데이터만 우선 표출 (혹은 Coarse + Fine)
        # 겹쳐 그릴 경우 범위 차이가 너무 클 수 있어 주로 Fine Scan 영역 확대 표시
        fz = [d[0] for d in result.get("fine_data", [])]
        fc = [d[1] for d in result.get("fine_data", [])]
        self.ax1.plot(fz, fc, "o-", markersize=3, color="steelblue", label="PL counts")
        
        center_z = result.get("center_z")
        max_z = result.get("max_z")
        
        if mode == "plateau_center":
            p_start = result.get("plateau_start")
            p_end = result.get("plateau_end")
            if center_z is not None:
                self.ax1.axvline(center_z, color="g", linestyle="-", linewidth=2, label="Center")
            if max_z is not None:
                self.ax1.axvline(max_z, color="r", linestyle="--", alpha=0.5, label="Max")
            if p_start is not None and p_end is not None:
                self.ax1.axvspan(p_start, p_end, alpha=0.15, color="green", label="Plateau")
        
        elif mode == "max_slope":
            slope_z = result.get("slope_z")
            if slope_z is not None:
                self.ax1.axvline(slope_z, color="darkorange", linestyle="-", linewidth=2, label="Max Slope")
            if max_z is not None:
                self.ax1.axvline(max_z, color="r", linestyle="--", alpha=0.5, label="Max")
                
        elif mode == "rising_edge":
            edge_z = result.get("edge_z")
            if edge_z is not None:
                self.ax1.axvline(edge_z, color="purple", linestyle="-", linewidth=2, label="Rising Edge")
            if max_z is not None:
                self.ax1.axvline(max_z, color="r", linestyle="--", alpha=0.5, label="Max")
                
        self.ax1.set_title(f"Auto-Focus: {mode}", fontsize=9)
        self.ax1.set_xlabel("Z (μm)", fontsize=8)
        self.ax1.set_ylabel("Count / s", fontsize=8)
        self.ax1.tick_params(labelsize=7)
        self.ax1.legend(fontsize=6, loc="best")
        
        self.canvas.draw_idle()
    
    def update_spectrum_plot(self, x_data, y_data, title="WinSpec Spectrum"):
        """
        WinSpec 스펙트럼 데이터를 우측 상단 플롯에 업데이트하는 메서드.
        히스토그램과 축을 공유하므로 스케일과 라벨을 재설정해야 함.
        """
        self.ax_hist.clear()
        self.ax_hist.set_title(title, fontsize=9)
        self.ax_hist.set_xlabel("Wavelength / Pixel", fontsize=8)
        self.ax_hist.set_ylabel("Intensity", fontsize=8)
        self.ax_hist.tick_params(labelsize=7)
        
        # 스펙트럼은 일반적으로 선형(linear) 스케일을 사용함
        self.ax_hist.set_yscale("linear")
        
        if len(x_data) > 0 and len(y_data) > 0:
            self.ax_hist.plot(x_data, y_data, color='crimson', lw=1)
            self.ax_hist.set_xlim(min(x_data), max(x_data))
            
            # y축 상단 여백 확보
            y_max = max(y_data)
            self.ax_hist.set_ylim(min(y_data), y_max + (y_max * 0.1) if y_max != 0 else 1)
        else:
            # 데이터가 비어있을 경우의 기본 화면
            self.ax_hist.plot([0], [0], color='crimson', lw=1)
            
        self.canvas.draw_idle()

    def _on_canvas_clicked(self, event):
        """ax2(PL 맵) 영역 내부를 '좌클릭(button 1)' 했을 때만 좌표를 방출한다."""
        if event.inaxes == self.ax2 and event.button == 1:
            if event.xdata is not None and event.ydata is not None:
                self.sig_map_clicked.emit(event.xdata, event.ydata)

    def set_galvo_target(self, x_um, y_um):
        """UI에서 이동을 요청했을 때 즉시 표시되는 가상의 타겟 마커 (Optimistic)"""
        self.galvo_target_indicator.center = (x_um, y_um)
        self.galvo_target_indicator.set_visible(True)
        self.canvas.draw_idle()

    def update_galvo_indicator(self, x_um, y_um):
        """하드웨어가 이동을 완료(Ack)했을 때 갱신되는 실제 마커"""
        self.galvo_indicator.center = (x_um, y_um)
        self.galvo_target_indicator.set_visible(False) # 도착했으니 타겟 마커 숨김
        self.canvas.draw_idle()

    def update_histogram(self, time_bins, counts):
        """
        PicoHarp TCSPC 데이터를 우측 상단 플롯에 업데이트하는 메서드.
        """
        self.ax_hist.clear()
        self.ax_hist.set_title("PicoHarp Histogram", fontsize=9)
        self.ax_hist.set_xlabel("Time (ns)", fontsize=8)
        self.ax_hist.set_ylabel("Counts", fontsize=8)
        self.ax_hist.tick_params(labelsize=7)
        self.ax_hist.set_yscale("log")
        
        if len(time_bins) > 0 and len(counts) > 0:
            self.ax_hist.plot(time_bins, counts, color='steelblue', lw=1)
            self.ax_hist.set_xlim(min(time_bins), max(time_bins))
            
            # log scale에서 0이 들어가면 깨지므로 최소값을 0.5로 설정
            y_max = max(counts)
            self.ax_hist.set_ylim(0.5, y_max * 1.5 if y_max > 0 else 1e5)
        else:
            self.ax_hist.plot([0], [1], color='steelblue', lw=1)
            
        self.canvas.draw_idle()