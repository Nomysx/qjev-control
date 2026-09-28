from collections import deque
import math
import numpy as np

from app.config import PlantParameters, RPM


class FeatureExtractor:
    def __init__(self, window: float, rate: int, parameters: PlantParameters):
        self.window = window
        self.rows: deque[dict[str, float]] = deque(maxlen=int(window * rate) + 2)
        self.parameters = parameters
        self.balances: deque[dict[str, float]] = deque(maxlen=int(12 * rate) + 2)
        self.rise_times = {"load": float("nan"), "deficit": float("nan")}
        self.voltage_response: tuple[float, float, float] | None = None

    def update(self, row: dict[str, float]) -> dict[str, float]:
        self.rows.append(row.copy())
        while len(self.rows) > 2 and row["time"] - self.rows[0]["time"] > self.window:
            self.rows.popleft()
        times = np.array([r["time"] for r in self.rows])
        centered = times - times.mean()
        denominator = float(centered @ centered)

        def values(key: str) -> np.ndarray:
            return np.array([r[key] for r in self.rows])

        def slope(data: np.ndarray) -> float:
            return float(centered @ data / denominator) if denominator > 1e-12 else 0.0

        result: dict[str, float] = {}
        for key, prefix in (("speed_residual_rpm", "speed"), ("current_residual_a", "current")):
            data = values(key)
            trend = slope(data)
            result.update({f"{prefix}_mean": float(data.mean()),
                           f"{prefix}_rms": float(np.sqrt(np.mean(data**2))),
                           f"{prefix}_std": float(data.std()),
                           f"{prefix}_peak": float(np.abs(data).max()),
                           f"{prefix}_trend": trend,
                           f"{prefix}_noise": float(np.std(data - trend * centered))})
        speed = values("measured_speed_rpm") / RPM
        current = values("measured_current_a")
        command = values("command_v")
        p = self.parameters
        speed_trend, current_trend = slope(speed), slope(current)
        # balance residuals use measured signals and nominal physical parameters
        voltage_mismatch = p.inductance * current_trend + p.resistance * current.mean() + p.back_emf * speed.mean() - command.mean()
        load_mismatch = p.torque_constant * current.mean() - p.friction * speed.mean() - p.inertia * speed_trend - p.load_torque * np.tanh(speed.mean() / 2.0)
        result.update({"voltage_mismatch": float(voltage_mismatch), "load_mismatch": float(load_mismatch),
                       "measured_current_trend": current_trend, "measured_speed_trend": speed_trend * RPM,
                       "tracking_error": row["reference_rpm"] - row["measured_speed_rpm"],
                       "command_mean": float(command.mean()), "command_std": float(command.std()),
                       "saturation_ratio": float(values("saturated").mean()),
                       "window_seconds": float(times[-1] - times[0])})
        # a short electrical window preserves command changes during fault onset
        short = times >= times[-1] - 0.12 - 1e-9
        short_current, short_speed, short_command = current[short], speed[short], command[short]
        inferred_voltage = (p.inductance * self._trend(times[short], short_current)
                            + p.resistance * short_current.mean() + p.back_emf * short_speed.mean())
        self.balances.append({"time": row["time"], "load": float(load_mismatch),
                              "deficit": float(-voltage_mismatch),
                              "short_deficit": float(short_command.mean() - inferred_voltage),
                              "command": float(short_command.mean()), "voltage": float(inferred_voltage)})
        result.update(self._temporal_features())
        return result

    @staticmethod
    def _trend(times: np.ndarray, data: np.ndarray) -> float:
        centered = times - times.mean()
        denominator = float(centered @ centered)
        return float(centered @ data / denominator) if denominator > 1e-12 else 0.0

    def _temporal_features(self) -> dict[str, float]:
        history = list(self.balances)
        times = np.array([r["time"] for r in history])
        recent = times >= times[-1] - 1.0
        result = {}
        for key, tolerance in (("load", 0.15), ("deficit", 0.7)):
            data = np.array([r[key] for r in history])
            result[f"{key}_trend"] = self._trend(times[recent], data[recent])
            result[f"{key}_min"] = float(data[recent].min())
            result[f"{key}_max"] = float(data[recent].max())
            baseline = np.flatnonzero(data < tolerance * 0.5)
            if data[-1] < tolerance * 0.5:
                self.rise_times[key] = float("nan")
            elif data[-1] >= 3 * tolerance and len(baseline):
                start = baseline[-1]
                rising = data[start:]
                low = np.flatnonzero(rising >= max(tolerance, 0.1 * data[-1]))
                high = np.flatnonzero(rising >= 0.9 * data[-1])
                if len(low) and len(high):
                    self.rise_times[key] = float(times[start + high[0]] - times[start + low[0]])
            result[f"{key}_rise_seconds"] = self.rise_times[key]

        # fit voltage response only within the current negative-balance episode
        deficit = np.array([r["short_deficit"] for r in history])
        command = np.array([r["command"] for r in history])
        voltage = np.array([r["voltage"] for r in history])
        normal = np.flatnonzero(deficit <= 0.7)
        start = normal[-1] + 1 if len(normal) else 0
        if start < len(times):
            usable = times > times[start] + 0.14
            x, y = command[usable], voltage[usable]
            if len(x) >= 5 and np.ptp(x) > 2.0 and np.std(x) > 0.5:
                centered = x - x.mean()
                gain = float(centered @ (y - y.mean()) / (centered @ centered))
                intercept = float(y.mean() - gain * x.mean())
                error = float(np.sqrt(np.mean((y - gain * x - intercept)**2)))
                if error < 0.5:
                    self.voltage_response = (gain, intercept, float(np.ptp(x)))
        if self.voltage_response is not None:
            gain, intercept, span = self.voltage_response
            error = abs(voltage[-1] - gain * command[-1] - intercept)
            if deficit[-1] < 0.35 or error > 0.7:
                self.voltage_response = None
        result["voltage_response_gain"] = self.voltage_response[0] if self.voltage_response else float("nan")
        result["voltage_response_span"] = self.voltage_response[2] if self.voltage_response else 0.0
        return result


def diagnostic_context(features: dict[str, float]) -> str:
    """Only observable signals enter the model context; simulation truth is excluded."""
    f = features
    noisy_speed, noisy_current = f["speed_noise"] > 12, f["current_noise"] > 0.3
    current_matches = abs(f["current_mean"]) < 0.6 and not noisy_current
    if noisy_speed and noisy_current:
        lines = ["The speed and current measurements BOTH disagree with the nominal model.",
                 f"Current residuals are irregular and large (std {f['current_noise']:.2f} A), not near zero.",
                 f"Speed residual fluctuations are also large (detrended std {f['speed_noise']:.0f} rpm)."]
    elif noisy_speed and current_matches:
        return (f"The speed measurement fluctuates strongly and randomly (jitter {f['speed_noise']:.0f} rpm).\n"
                f"Its mean residual is {f['speed_mean']:+.0f} rpm.\n"
                f"The motor current still agrees with the nominal model ({f['current_mean']:+.3f} A residual).")
    elif abs(f["speed_mean"]) >= 35 and current_matches and not noisy_speed:
        return (f"The speed measurement has a persistent offset from the nominal model ({f['speed_mean']:+.0f} rpm), "
                f"with small fluctuations ({f['speed_noise']:.0f} rpm).\n"
                f"The motor current still agrees with the nominal model ({f['current_mean']:+.3f} A residual).")
    else:
        speed = "matches nominal" if abs(f["speed_mean"]) < 35 else ("is above nominal" if f["speed_mean"] > 0 else "is below nominal")
        current = "matches nominal" if current_matches else ("is above nominal" if f["current_mean"] > 0 else "is below nominal")
        lines = [f"Speed {speed} (mean residual {f['speed_mean']:+.0f} rpm).",
                 f"Motor current {current} (mean residual {f['current_mean']:+.2f} A)."]
        if current_matches or noisy_speed:
            lines.insert(1, f"Speed fluctuations are {'strong' if noisy_speed else 'small'} (detrended std {f['speed_noise']:.0f} rpm).")
        if noisy_current:
            lines.append(f"Current residual fluctuations are large (detrended std {f['current_noise']:.2f} A).")

    # balance estimates inherit encoder noise, so omit them for isolated sensor evidence
    if current_matches:
        if abs(f["load_mismatch"]) < 0.15:
            lines.append("No significant extra resisting torque.")
        return "\n".join(lines)

    if f["load_min"] < -0.15 and f["load_max"] > 0.15:
        lines.append(f"Mechanical balance repeatedly changes sign ({f['load_min']:+.2f} to {f['load_max']:+.2f} N m), "
                     "without a stable extra resisting torque.")
    elif f["load_mismatch"] > 0.15:
        rise = f["load_rise_seconds"]
        shape = ("grew gradually" if rise >= 1.0 else
                 "appeared abruptly and then stayed constant" if math.isfinite(rise) and abs(f["load_trend"]) < 0.15 else
                 "is rising" if f["load_trend"] > 0.15 else "is elevated")
        timing = f" (rise time {rise:.2f} s)" if math.isfinite(rise) else ""
        lines.append(f"Extra resisting torque {shape}{timing}, now {f['load_mismatch']:.2f} N m.")
    elif f["load_mismatch"] < -0.15:
        lines.append(f"Mechanical balance is negative ({f['load_mismatch']:.2f} N m).")

    if f["deficit_min"] < -0.7 and f["deficit_max"] > 0.7:
        lines.append(f"Electrical balance also changes sign ({-f['deficit_max']:+.2f} to {-f['deficit_min']:+.2f} V).")
    elif f["voltage_mismatch"] < -0.7:
        lines.append(f"Electrical voltage deficit {-f['voltage_mismatch']:.2f} V.")
        rise, gain = f["deficit_rise_seconds"], f["voltage_response_gain"]
        if rise >= 1.2:
            lines.append(f"The voltage deficit grew gradually (rise time {rise:.2f} s).")
        elif math.isfinite(gain):
            response = ("stays fixed despite changing command" if abs(gain) < 0.15 else
                        "changes with command at reduced gain" if 0.15 <= gain < 0.85 else
                        "changes with command")
            lines.append(f"Inferred motor voltage {response} (response gain {gain:.2f}, "
                         f"command span {f['voltage_response_span']:.1f} V).")
    elif f["voltage_mismatch"] > 0.7:
        lines.append(f"Electrical balance is positive ({f['voltage_mismatch']:.2f} V).")
    return "\n".join(lines)
