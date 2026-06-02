# test/core/ObisClient.py
import socket
import json
import logging

class ObisClient:
    """
    세컨드 컴퓨터의 멀티 OBIS 레이저 디바이스 서버와 통신하는 TCP 클라이언트.
    GUI 스레드의 블로킹(Blocking)을 막기 위해 짧은 timeout을 가짐.
    """
    def __init__(self, host: str, port: int = 9000, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        # 로깅은 네 통합 프로그램의 기준에 맞춰서 나중에 수정해
        self.logger = logging.getLogger(__name__)

    def _send(self, payload: dict) -> dict:
        """내부 통신 메서드. 예외가 발생해도 GUI가 죽지 않도록 dict 형태로 에러를 반환함."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout)
            try:
                s.connect((self.host, self.port))
                s.sendall(json.dumps(payload).encode('utf-8'))
                
                response_data = s.recv(1024).decode('utf-8')
                if not response_data:
                    return {'status': 'error', 'message': 'Empty response from server'}
                
                return json.loads(response_data)
                
            except socket.timeout:
                self.logger.error(f"ObisClient Timeout: {self.host}:{self.port} 응답 없음.")
                return {'status': 'error', 'message': 'Timeout'}
            except ConnectionRefusedError:
                self.logger.error(f"ObisClient Connection Refused: 서버 프로그램이 켜져 있는지 확인.")
                return {'status': 'error', 'message': 'Connection Refused'}
            except Exception as e:
                self.logger.error(f"ObisClient Error: {str(e)}")
                return {'status': 'error', 'message': str(e)}

    def ping(self) -> bool:
        """서버가 살아있는지 네트워크 레벨에서만 확인"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(self.timeout)
            try:
                s.connect((self.host, self.port))
                return True
            except:
                return False

    # ---------------------------------------------------------
    # 외부(GUI/Main)에서 호출할 하이레벨(High-level) 제어 메서드들
    # ---------------------------------------------------------

    def get_status(self, target: str) -> dict:
        """특정 레이저의 현재 상태(Emission, Power) 조회"""
        return self._send({
            'target': target,
            'action': 'get_status'
        })

    def set_power(self, target: str, power_mw: float) -> dict:
        """특정 레이저의 출력 파워 변경 (단위: mW)"""
        return self._send({
            'target': target,
            'action': 'set_power',
            'value': float(power_mw)
        })

    def set_state(self, target: str, state: bool) -> dict:
        """특정 레이저의 Emission 상태 변경 (True=ON, False=OFF)"""
        return self._send({
            'target': target,
            'action': 'set_on',
            'value': bool(state)
        })
    
    def get_diagnostics(self, target: str) -> dict:
        """레이저 진단 정보(인터락/fault/온도 등) 조회"""
        return self._send({
            'target': target,
            'action': 'get_diagnostics'
        })


    def get_status_all(self):
        return self._send({'action': 'get_status_all'})