from dataclasses import dataclass
import math

FAULT_NAMES = {
    "healthy": "Healthy operation",
    "sensor_bias": "Speed sensor bias",
    "sensor_noise": "Speed sensor noise",
    "actuator_loss": "Actuator effectiveness loss",
    "actuator_stuck": "Actuator stuck",
    "load": "External load disturbance",
    "friction": "Mechanical friction increase",
    "resistance": "Electrical resistance drift",
    "unknown": "Unknown / compound fault",
}


@dataclass
class Fault:
    kind: str
    start: float = 6.0
    severity: float = 0.7
    duration: float | None = None
    ramp: float = 0.0
    stuck_voltage: float | None = None
    started: bool = False
    ended: bool = False

    def __post_init__(self) -> None:
        if self.kind not in FAULT_NAMES or self.kind == "healthy":
            raise ValueError("Select an injectable fault.")
        values = [self.start, self.severity, self.ramp]
        if self.duration is not None:
            values.append(self.duration)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Fault parameters must be finite.")
        if self.start < 0 or not 0 < self.severity <= 1 or self.ramp < 0:
            raise ValueError("Fault start/ramp must be nonnegative and severity in (0, 1].")
        if self.duration is not None and self.duration <= 0:
            raise ValueError("Fault duration must be positive or persistent.")

    def amount(self, time: float) -> float:
        if time < self.start or self.ended:
            return 0.0
        if self.duration is not None and time >= self.start + self.duration:
            return 0.0
        fraction = min(1.0, (time - self.start) / self.ramp) if self.ramp else 1.0
        return self.severity * fraction


class FaultManager:
    def __init__(self, faults: list[Fault] | None = None):
        self.faults = faults or []

    def update(self, time: float, command: float) -> list[dict]:
        events = []
        for fault in self.faults:
            if not fault.started and not fault.ended and time >= fault.start:
                fault.started = True
                fault.stuck_voltage = command * (1.0 - 0.65 * fault.severity)
                events.append({"time": time, "kind": "fault", "label": fault.kind,
                               "severity": fault.severity})
            if fault.started and not fault.ended and fault.duration is not None and time >= fault.start + fault.duration:
                fault.ended = True
                events.append({"time": time, "kind": "clear", "label": fault.kind})
        return events

    def clear(self, time: float) -> None:
        for fault in self.faults:
            fault.ended = True

    def active(self, time: float) -> list[tuple[Fault, float]]:
        return [(f, f.amount(time)) for f in self.faults if f.amount(time) > 0]

    def truth(self, time: float) -> str:
        active = self.active(time)
        return active[0][0].kind if len(active) == 1 else ("unknown" if active else "healthy")
