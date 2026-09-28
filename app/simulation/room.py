"""Single-room thermal plant. Heater commands are supplied by the model caller."""

from collections import deque
from dataclasses import dataclass
import math


HEATER_OPTIONS = [
    {"id": "on", "description": "Turn the room heater ON at full power."},
    {"id": "off", "description": "Turn the room heater OFF (zero heating power)."},
]
HEATER_QUESTION = (
    "You control a room heater using bang-bang control with hysteresis. "
    "Choose ON when room temperature is at or below the lower threshold. "
    "Choose OFF when room temperature is at or above the upper threshold. "
    "Between the thresholds, keep the current heater state. "
    "Which heater command should be applied now?"
)


@dataclass
class RoomSettings:
    initial: float = 18.0
    target: float = 22.0
    outside: float = 5.0
    heater_watts: float = 3000.0
    deadband: float = 0.3
    capacity: float = 300000.0  # Effective room thermal capacity, J/K.
    conductance: float = 80.0  # Closed-window heat transfer, W/K.


class RoomSimulation:
    def __init__(self, settings: RoomSettings):
        self.settings = settings
        self.time = 0.0
        self.temperature = settings.initial
        self.heater = False
        self.step_watts = 0.0
        self.pulse_watts = 0.0
        self.pulse_end = 0.0
        self.window_open = False
        self.rows = deque(maxlen=18000)
        self.record()

    @property
    def loss_watts(self) -> float:
        return self.settings.conductance * (4.0 if self.window_open else 1.0) * (
            self.temperature - self.settings.outside)

    @property
    def disturbance_watts(self) -> float:
        return self.step_watts + (self.pulse_watts if self.time < self.pulse_end else 0.0)

    def record(self) -> None:
        self.rows.append({
            "time": self.time, "temperature": self.temperature,
            "target": self.settings.target, "outside": self.settings.outside,
            "lower": self.settings.target - self.settings.deadband,
            "upper": self.settings.target + self.settings.deadband,
            "heater": float(self.heater),
            "power": self.settings.heater_watts if self.heater else 0.0,
            "loss": self.loss_watts, "disturbance": self.disturbance_watts,
        })

    def advance(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Room time step must be finite and nonnegative.")
        end = self.time + seconds
        while self.time < end - 1e-9:
            dt = min(1.0, end - self.time)
            if self.time < self.pulse_end:
                dt = min(dt, self.pulse_end - self.time)
            transfer = self.settings.conductance * (4.0 if self.window_open else 1.0)
            power = (self.settings.heater_watts if self.heater else 0.0) + self.disturbance_watts
            equilibrium = self.settings.outside + power / transfer
            self.temperature = equilibrium + (self.temperature - equilibrium) * math.exp(
                -transfer * dt / self.settings.capacity)
            self.time += dt
            self.record()

    def command(self, selected: str) -> None:
        if selected not in ("on", "off"):
            raise ValueError(f"Invalid heater command: {selected}")
        self.heater = selected == "on"
        self.record()

    def inject(self, kind: str, amount: float, duration: float) -> None:
        if kind == "spike":
            self.temperature += amount
        elif kind == "step":
            self.step_watts = amount
        elif kind == "pulse":
            self.pulse_watts = amount
            self.pulse_end = self.time + duration
        elif kind == "window":
            self.window_open = True
        else:
            raise ValueError(f"Unknown room disturbance: {kind}")
        self.record()

    def clear_disturbances(self) -> None:
        self.step_watts = self.pulse_watts = 0.0
        self.pulse_end = self.time
        self.window_open = False
        self.record()

    def context(self) -> str:
        s = self.settings
        return (
            f"Room temperature: {self.temperature:.3f} degrees C.\n"
            f"Desired temperature: {s.target:.3f} degrees C.\n"
            f"Lower switching threshold: {s.target - s.deadband:.3f} degrees C.\n"
            f"Upper switching threshold: {s.target + s.deadband:.3f} degrees C.\n"
            f"Current heater state: {'ON' if self.heater else 'OFF'}.\n"
            f"Outside temperature: {s.outside:.3f} degrees C.\n"
            f"Heater power when ON: {s.heater_watts:.0f} W.\n"
            f"Simulation time: {self.time:.1f} seconds."
        )
