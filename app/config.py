from dataclasses import asdict, dataclass, field
import math

RPM = 60.0 / (2.0 * math.pi)


@dataclass
class PlantParameters:
    inertia: float = 0.025
    inductance: float = 0.04
    resistance: float = 0.6
    torque_constant: float = 0.12
    back_emf: float = 0.12
    friction: float = 0.003
    load_torque: float = 0.25
    supply_voltage: float = 48.0

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")


@dataclass
class ControllerParameters:
    kp: float = 0.24
    ki: float = 0.9
    antiwindup: float = 5.0
    reference_ramp_rpm_s: float = 900.0


@dataclass
class Timing:
    physics_hz: int = 500
    control_hz: int = 100
    feature_hz: int = 50
    ui_hz: int = 20
    qjev_interval: float = 1.0
    feature_window: float = 0.6
    result_max_age: float = 8.0
    plot_capacity: int = 6000

    def validate(self) -> None:
        for rate in (self.control_hz, self.feature_hz):
            if rate <= 0 or self.physics_hz % rate:
                raise ValueError("Control and diagnostic rates must divide the physics rate.")
        if self.physics_hz < 100 or self.feature_hz < 10 or self.ui_hz < 1:
            raise ValueError("Use physics >= 100 Hz, diagnostics >= 10 Hz and UI >= 1 Hz.")
        if self.feature_hz > self.control_hz:
            raise ValueError("Diagnostic frequency cannot exceed the sensor/control frequency.")
        if not all(math.isfinite(x) and x > 0 for x in (self.qjev_interval, self.feature_window, self.result_max_age)):
            raise ValueError("Timing intervals must be finite and positive.")


@dataclass
class Configuration:
    plant: PlantParameters = field(default_factory=PlantParameters)
    controller: ControllerParameters = field(default_factory=ControllerParameters)
    timing: Timing = field(default_factory=Timing)
    target_rpm: float = 1800.0
    seed: int = 42
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qjev-0.8b:latest"
    readout: str = "letters"
    request_timeout: float = 15.0
    min_diagnosis_score: float = 0.42
    diagnosis_persistence: float = 1.0

    def validate(self) -> None:
        self.plant.validate()
        self.timing.validate()
        g = self.controller
        if not all(math.isfinite(value) and value >= 0 for value in (g.kp, g.ki)):
            raise ValueError("PI gains must be finite and nonnegative.")
        if not all(math.isfinite(value) and value > 0 for value in (g.antiwindup, g.reference_ramp_rpm_s)):
            raise ValueError("Anti-windup and reference ramp must be finite and positive.")
        if not 0 < self.min_diagnosis_score <= 1 or not math.isfinite(self.diagnosis_persistence) or self.diagnosis_persistence <= 0:
            raise ValueError("Diagnosis thresholds and persistence are invalid.")
        p = self.plant
        fastest_rate = p.resistance / p.inductance + p.friction / p.inertia
        if fastest_rate / self.timing.physics_hz > 0.25:
            raise ValueError("Increase physics frequency for these electrical/mechanical parameters.")
        if not 0 <= self.target_rpm <= 3500:
            raise ValueError("Target speed must be between 0 and 3500 rpm.")
