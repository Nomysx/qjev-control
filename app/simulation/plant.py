from dataclasses import dataclass
from math import tanh

from app.config import PlantParameters


@dataclass
class MotorState:
    speed: float = 0.0
    current: float = 0.0


class Motor:
    def __init__(self, parameters: PlantParameters):
        self.parameters = parameters
        self.state = MotorState()

    def step(self, voltage: float, dt: float, load_extra: float = 0.0,
             friction_extra: float = 0.0, resistance_factor: float = 1.0) -> MotorState:
        p = self.parameters

        def derivative(w: float, i: float) -> tuple[float, float]:
            # a smooth resisting load avoids a discontinuity at standstill
            load = (p.load_torque + load_extra) * tanh(w / 2.0)
            return ((p.torque_constant * i - (p.friction + friction_extra) * w - load) / p.inertia,
                    (voltage - p.resistance * resistance_factor * i - p.back_emf * w) / p.inductance)

        w, i = self.state.speed, self.state.current
        a = derivative(w, i)
        b = derivative(w + dt * a[0] / 2, i + dt * a[1] / 2)
        c = derivative(w + dt * b[0] / 2, i + dt * b[1] / 2)
        d = derivative(w + dt * c[0], i + dt * c[1])
        self.state = MotorState(w + dt * (a[0] + 2*b[0] + 2*c[0] + d[0]) / 6,
                                i + dt * (a[1] + 2*b[1] + 2*c[1] + d[1]) / 6)
        return self.state
