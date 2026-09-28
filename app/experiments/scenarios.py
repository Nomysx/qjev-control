from copy import deepcopy
from dataclasses import dataclass

from app.simulation.faults import Fault


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    faults: tuple[Fault, ...] = ()
    seed: int = 42

    def instantiate(self) -> list[Fault]:
        return deepcopy(list(self.faults))


SCENARIOS = {
    "healthy": Scenario("Healthy baseline", "Nominal motor and measurement noise. Use this to inspect false alarms."),
    "sensor_bias": Scenario("01 | Encoder bias", "A 250 rpm encoder offset develops over 0.4 s; the controller reacts to an incorrect measurement.",
                            (Fault("sensor_bias", severity=0.75, ramp=0.4),)),
    "sensor_noise": Scenario("02 | Noisy encoder", "Encoder noise rises for 5 s, then recovers.",
                             (Fault("sensor_noise", severity=0.75, duration=5.0),)),
    "load": Scenario("03 | Load step", "An extra 0.88 N m resisting load is applied at 6 s.",
                     (Fault("load", severity=0.8),)),
    "actuator_loss": Scenario("04 | Voltage loss", "The actuator delivers 51% of requested voltage for 6 s.",
                              (Fault("actuator_loss", severity=0.75, duration=6.0),)),
    "actuator_stuck": Scenario("05 | Stuck actuator", "The actuator freezes below its pre-fault voltage while the command continues changing.",
                               (Fault("actuator_stuck", severity=0.8),)),
    "friction": Scenario("06 | Friction ramp", "Viscous friction grows over 5 s. Steady-state load and friction may be difficult to distinguish.",
                         (Fault("friction", severity=0.7, ramp=5.0),)),
    "resistance": Scenario("07 | Resistance drift", "Winding resistance rises over 3 s, increasing the electrical balance residual.",
                           (Fault("resistance", severity=0.8, ramp=3.0),)),
    "unknown": Scenario("08 | Unmodeled sensor combination", "Intermittent encoder dropouts plus current-sensor gain error. No single known hypothesis describes both.",
                        (Fault("unknown", severity=0.7),), seed=73),
}
