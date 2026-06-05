"""
PID.py — Takahashi Type C (incremental / velocity form) PID controller.

Reference: Ulm-IQO/qudi  logic/software_pid_controller.py

Takahashi Type C (incremental form):
    e[k]   = setpoint - pv[k]
    Δu[k]  = Kp*(e[k] - e[k-1])
            + Ki*dt*e[k]
            + Kd/dt*(e[k] - 2*e[k-1] + e[k-2])
    u[k]   = u[k-1] + Δu[k]

장점:
  - 적분 windup이 자연스럽게 제한됨 (출력 clamp로 충분)
  - Setpoint 급변 시 proportional kick 없음
"""


class PID:
    def __init__(
        self,
        kp: float = 1.0,
        ki: float = 0.0,
        kd: float = 0.0,
        dt: float = 1.0,
        output_min: float = -float("inf"),
        output_max: float = float("inf"),
    ):
        """
        Parameters
        ----------
        kp, ki, kd : PID 게인
        dt         : 제어 주기 (초). 궤도 1사이클 시간으로 설정.
        output_min/max : 출력 클램프 (V 단위)
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.dt = dt
        self.output_min = output_min
        self.output_max = output_max

        self._e0 = 0.0   # e[k]
        self._e1 = 0.0   # e[k-1]
        self._e2 = 0.0   # e[k-2]
        self._u  = 0.0   # u[k-1]  (누적 출력)
        self._started = False

    def reset(self):
        self._e0 = self._e1 = self._e2 = 0.0
        self._u = 0.0
        self._started = False

    def step(self, error: float) -> float:
        """
        오차 하나를 받아 보정량(Δu)을 반환한다.

        Parameters
        ----------
        error : 현재 오차 (a1_norm 또는 b1_norm)

        Returns
        -------
        correction : 궤도 중심에 더할 전압 보정값 (V)
        """
        if not self._started:
            # 첫 스텝: 미분항 계산 불가 → P only
            self._e0 = error
            self._e1 = error
            self._e2 = error
            self._started = True
            delta_u = self.kp * error
        else:
            self._e2 = self._e1
            self._e1 = self._e0
            self._e0 = error

            delta_u = (
                self.kp * (self._e0 - self._e1)
                + self.ki * self.dt * self._e0
                + self.kd / self.dt * (self._e0 - 2 * self._e1 + self._e2)
            )

        self._u += delta_u
        self._u = max(self.output_min, min(self.output_max, self._u))
        return self._u
