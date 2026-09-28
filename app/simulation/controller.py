from app.config import ControllerParameters, PlantParameters, RPM


class SpeedController:
    def __init__(self, gains: ControllerParameters, plant: PlantParameters):
        self.gains, self.plant = gains, plant
        self.integral = 0.0
        self.reference = 0.0
        self.command = 0.0
        self.saturated = False

    def step(self, target_rpm: float, measured_speed: float, dt: float) -> float:
        g, p = self.gains, self.plant
        target = target_rpm / RPM
        limit = g.reference_ramp_rpm_s / RPM * dt
        self.reference += max(-limit, min(limit, target - self.reference))
        error = self.reference - measured_speed
        feedforward = p.back_emf * self.reference + p.resistance * (
            p.friction * self.reference + p.load_torque) / p.torque_constant
        raw = feedforward + g.kp * error + self.integral
        self.command = max(-p.supply_voltage, min(p.supply_voltage, raw))
        self.saturated = abs(raw) >= p.supply_voltage
        self.integral += (g.ki * error + g.antiwindup * (self.command - raw)) * dt
        self.integral = max(-2*p.supply_voltage, min(2*p.supply_voltage, self.integral))
        return self.command
