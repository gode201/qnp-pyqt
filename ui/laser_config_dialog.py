from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton
from PyQt5.QtCore import Qt

class LaserConfigDialog(QDialog):
    """
    OBIS 레이저 파워를 정밀 조절하기 위한 미니 팝업 윈도우.
    UI 스레드를 블로킹하지 않도록 모달리스(Modeless)로 띄우거나 모달(Modal)로 제어한다.
    """
    def __init__(self, target_name, current_power=0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{target_name} Setting")
        self.setFixedSize(220, 100)
        
        
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        
        self._setup_ui(current_power)

    def _setup_ui(self, current_power):
        layout = QVBoxLayout(self)
        
        # 파워 입력부
        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel("Power (mW):"))
        
        self.spin_power = QDoubleSpinBox()
        # OBIS 장비 스펙에 맞춰 상한선 설정 (필요시 Default.py에서 끌어오도록 수정할 것)
        self.spin_power.setRange(0.0, 150.0) 
        self.spin_power.setDecimals(1)
        self.spin_power.setSingleStep(0.5)
        self.spin_power.setValue(current_power)
        
        h_layout.addWidget(self.spin_power)
        layout.addLayout(h_layout)
        
        # 적용 / 취소 버튼
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton("Apply")
        self.btn_cancel = QPushButton("Cancel")
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)
        
        # 시그널 연결 (버튼 자체 처리)
        self.btn_apply.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def get_power(self):
        """팝업이 Accepted로 닫혔을 때 컨트롤러가 이 값을 읽어간다."""
        return self.spin_power.value()