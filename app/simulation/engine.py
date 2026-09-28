from collections import deque
from copy import deepcopy
from dataclasses import asdict
import math
from pathlib import Path

import numpy as np

from app.config import Configuration, RPM
from app.diagnostics.detector import AnomalyDetector
from app.diagnostics.diagnosis_filter import DiagnosisFilter
from app.diagnostics.features import FeatureExtractor, diagnostic_context
from app.diagnostics.qjev_client import ModelDecision
from app.diagnostics.service import DiagnosticRequest
from app.experiments.history import RunHistory
from app.experiments.metrics import ExperimentMetrics
from app.experiments.scenarios import SCENARIOS
from app.simulation.controller import SpeedController
from app.simulation.faults import Fault, FaultManager
from app.simulation.observer import NominalPredictor
from app.simulation.plant import Motor


class Simulation:
    def __init__(self, config: Configuration | None = None, scenario: str = "healthy"):
        self.config = deepcopy(config or Configuration())
        self.config.validate()
        self.initial_config = asdict(self.config)
        self.scenario = scenario
        self.time, self.tick, self._remainder = 0.0, 0, 0.0
        self.motor = Motor(self.config.plant)
        self.observer = NominalPredictor(self.config.plant)
        self.controller = SpeedController(self.config.controller, self.config.plant)
        self.faults = FaultManager(SCENARIOS[scenario].instantiate())
        self.physical_rng = np.random.default_rng(self.config.seed)
        self.fault_rng = np.random.default_rng(self.config.seed + 10000)
        self.features = FeatureExtractor(self.config.timing.feature_window, self.config.timing.feature_hz, self.config.plant)
        self.detector = AnomalyDetector()
        self.diagnosis = DiagnosisFilter(self.config.min_diagnosis_score, self.config.diagnosis_persistence)
        self.metrics, self.history = ExperimentMetrics(), RunHistory()
        self.live: deque[dict] = deque(maxlen=self.config.timing.plot_capacity)
        self.events: list[dict] = []
        self.last_features: dict = {}
        self.last_row: dict = {}
        self.last_decision: ModelDecision | None = None
        self.last_context = "No diagnostic request yet."
        self.last_request_time: float | None = None
        self.last_model_time: float | None = None
        self.last_latency: float | None = None
        self.measured_speed, self.measured_current = 0.0, 0.0
        self.applied_voltage = 0.0
        self.closed = False

    def event(self, kind: str, label: str, **extra) -> None:
        event = {"time": self.time, "kind": kind, "label": label, **extra}
        self.events.append(event)
        self.metrics.fault_event(event)

    def inject(self, fault: Fault) -> None:
        self.faults.faults.append(fault)
        self.event("scheduled", fault.kind, start=fault.start, severity=fault.severity,
                   duration=fault.duration, ramp=fault.ramp)

    def clear_faults(self) -> None:
        self.faults.clear(self.time)
        self.event("clear", "all")

    @property
    def truth(self) -> str:
        return self.faults.truth(self.time)

    @property
    def mode(self) -> str:
        if self.detector.state == "normal":
            return "NORMAL"
        if self.detector.state == "confirmed anomaly":
            if self.detector.score >= 8 or self.diagnosis.active == "unknown":
                return "SAFE ADVISORY"
            if self.diagnosis.active in ("sensor_bias", "sensor_noise"):
                return "SENSOR UNRELIABLE"
            return "DEGRADED"
        return "WATCH"

    def advance(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Advance duration must be finite and nonnegative.")
        timing = self.config.timing
        dt = 1.0 / timing.physics_hz
        self._remainder += seconds
        steps = int((self._remainder + 1e-12) / dt)
        self._remainder -= steps * dt
        for _ in range(steps):
            self.tick += 1
            self.time = self.tick * dt
            command = self.controller.command
            for event in self.faults.update(self.time, command):
                self.events.append(event)
                self.metrics.fault_event(event)
            active = self.faults.active(self.time)
            load, friction, resistance, voltage = 0.0, 0.0, 1.0, command
            for fault, amount in active:
                if fault.kind == "load":
                    load += 1.1 * amount
                elif fault.kind == "friction":
                    friction += 0.015 * amount
                elif fault.kind == "resistance":
                    resistance += 1.5 * amount
                elif fault.kind == "actuator_loss":
                    voltage *= 1.0 - 0.65 * amount
                elif fault.kind == "actuator_stuck":
                    voltage = fault.stuck_voltage if fault.stuck_voltage is not None else 0.0
            self.applied_voltage = voltage
            self.motor.step(voltage, dt, load, friction, resistance)
            self.observer.step(command, dt)
            if not all(math.isfinite(x) for x in (self.motor.state.speed, self.motor.state.current,
                                                 self.observer.state.speed, self.observer.state.current)):
                raise FloatingPointError("Nonfinite plant state. Check plant parameters and physics rate.")
            if self.tick % (timing.physics_hz // timing.control_hz) == 0:
                self.measured_speed = self.motor.state.speed + self.physical_rng.normal(0, 2.0 / RPM)
                self.measured_current = self.motor.state.current + self.physical_rng.normal(0, 0.025)
                for fault, amount in active:
                    if fault.kind == "sensor_bias":
                        self.measured_speed += 35.0 * amount
                    elif fault.kind == "sensor_noise":
                        self.measured_speed += self.fault_rng.normal(0, 70.0 * amount / RPM)
                    elif fault.kind == "unknown":
                        self.measured_current *= 1.0 + 0.5 * amount
                        if int((self.time - fault.start) / 0.18) % 4 == 0:
                            self.measured_speed *= 1.0 - 0.55 * amount
                self.controller.step(self.config.target_rpm, self.measured_speed, 1.0 / timing.control_hz)
            if self.tick % (timing.physics_hz // timing.feature_hz) == 0:
                self._sample(command)

    def _sample(self, previous_command: float) -> None:
        state, expected = self.motor.state, self.observer.state
        row = {"time": self.time, "target_rpm": self.config.target_rpm,
               "reference_rpm": self.controller.reference * RPM,
               "true_speed_rpm": state.speed * RPM, "measured_speed_rpm": self.measured_speed * RPM,
               "expected_speed_rpm": expected.speed * RPM, "measured_current_a": self.measured_current,
               "true_current_a": state.current, "expected_current_a": expected.current,
               "command_v": previous_command, "applied_v": self.applied_voltage,
               "speed_residual_rpm": (self.measured_speed - expected.speed) * RPM,
               "current_residual_a": self.measured_current - expected.current,
               "saturated": float(self.controller.saturated)}
        self.last_features = self.features.update(row)
        self.detector.update(self.last_features, self.time, 1.0 / self.config.timing.feature_hz)
        if self.diagnosis.expire(self.time, self.config.timing.result_max_age):
            self.event("diagnosis", "unresolved (stale)")
        row.update({"voltage_balance_residual_v": self.last_features["voltage_mismatch"],
                    "load_mismatch_nm": self.last_features["load_mismatch"],
                    "anomaly_score": self.detector.score, "anomaly": self.detector.state,
                    "above_threshold_s": self.detector.above_duration, "mode": self.mode,
                    "truth": self.truth, "diagnosis": self.diagnosis.active,
                    "diagnosis_score": self.diagnosis.stable_score,
                    "model_top_score": max(self.last_decision.scores.values()) if self.last_decision else float("nan"),
                    "model_sample_time": self.last_model_time if self.last_model_time is not None else float("nan"),
                    "qjev_latency_s": self.last_latency if self.last_latency is not None else float("nan")})
        self.last_row = row
        self.metrics.observe(row)
        self.live.append(row)
        self.history.append(row)

    def make_request(self, generation: int) -> DiagnosticRequest:
        if not self.last_row:
            raise ValueError("No diagnostic features yet.")
        self.last_context = diagnostic_context(self.last_features)
        self.last_request_time = self.time
        return DiagnosticRequest(generation, self.time, self.last_context, self.truth, self.detector.state)

    def accept(self, request: DiagnosticRequest, decision: ModelDecision) -> bool:
        stale = self.time - request.time > self.config.timing.result_max_age
        self.history.diagnostic({"sample_time": request.time, "received_time": self.time,
                                 "context": request.context, "truth_for_evaluation_only": request.truth,
                                 "stale": stale, **asdict(decision)})
        if stale:
            self.metrics.stale_results += 1
            return False
        self.last_decision, self.last_model_time, self.last_latency = decision, request.time, decision.latency
        self.metrics.inference(request.truth, decision.selected, decision.latency, request.time, self.time)
        if self.diagnosis.update(decision.scores, request.time, self.detector.state):
            self.event("diagnosis", self.diagnosis.active, sample_time=request.time)
            self.metrics.transition(self.diagnosis.active, self.truth, self.time)
        return True

    def export(self, path: str | Path) -> list[Path]:
        return self.history.export(path, {"format_version": 1, "scenario": self.scenario,
                                          "initial_configuration": self.initial_config,
                                          "final_configuration": asdict(self.config),
                                          "events": self.events, "samples": self.history.count,
                                          "summary": self.metrics.summary(self.diagnosis.active, self.truth),
                                          "score_semantics": "Normalized option-token scores, not calibrated fault probabilities. Smoothed scores use EMA."})

    def close(self) -> None:
        if not self.closed:
            self.history.close()
            self.closed = True
