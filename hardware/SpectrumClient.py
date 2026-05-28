# SpectrumClient.py
# WinSpec32 서버(Win7 VM)와 통신하는 클라이언트 클래스
# GUI.py에서 import하여 사용

import socket
import json
import os
from datetime import datetime


class SpecClient:
    """WinSpec32 TCP 소켓 클라이언트"""

    def __init__(self, host, port=8765, timeout=120):
        self.host = host
        self.port = port
        self.timeout = timeout

    def _send(self, cmd: dict) -> dict:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            s.sendall(json.dumps(cmd).encode('utf-8'))
            chunks = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b''.join(chunks).decode('utf-8')
        return json.loads(raw)

    def ping(self) -> bool:
        try:
            r = self._send({'action': 'status'})
            return r.get('status') == 'ok'
        except Exception:
            return False

    def status(self) -> dict:
        return self._send({'action': 'status'})

    def set_exposure(self, value: float) -> dict:
        return self._send({'action': 'set_exposure', 'value': value})

    def set_accumulations(self, value: int) -> dict:
        return self._send({'action': 'set_accumulations', 'value': value})

    def acquire(self, exposure: float = 1.0,
                accumulations: int = 1,
                savepath: str = 'C:/winspec_data/latest.spe') -> dict:
        """
        스펙트럼 획득.
        Returns: {'status': 'done', 'path': '...', 'data': [...]}
        """
        cmd = {
            'action': 'acquire',
            'exposure': exposure,
            'accumulations': accumulations,
            'savepath': savepath,
        }
        result = self._send(cmd)
        if result.get('status') != 'done':
            raise RuntimeError("Acquisition failed: {0}".format(result))
        return result

    def acquire_and_save_csv(self,
                              exposure: float = 1.0,
                              accumulations: int = 1,
                              spe_savepath: str = 'C:/winspec_data/latest.spe',
                              csv_savepath: str = None) -> str:
        """
        스펙트럼 획득 후 CSV로 저장.
        csv_savepath가 None이면 spe_savepath와 같은 위치에 저장.
        Returns: 저장된 CSV 경로 (없으면 None)
        """
        result = self.acquire(exposure=exposure, accumulations=accumulations,
                              savepath=spe_savepath)
        data = result.get('data')
        if not data:
            return None

        if csv_savepath is None:
            csv_savepath = spe_savepath.replace('.spe', '.csv')

        wavelengths = result.get('wavelength', [])

        os.makedirs(os.path.dirname(csv_savepath), exist_ok=True)
        with open(csv_savepath, 'w') as f:
            if wavelengths and len(wavelengths) == len(data):
                f.write('lambda,spectrum\n')
                for wl, v in zip(wavelengths, data):
                    f.write('{0:.4f},{1}\n'.format(wl, v))
            else:
                f.write('pixel,spectrum\n')
                for i, v in enumerate(data):
                    f.write('{0},{1}\n'.format(i, v))
        return csv_savepath
