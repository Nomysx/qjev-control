"""Equation pages rendered as Qt rich text. Every formula mirrors the code that computes it."""

import math

from app.config import RPM, Configuration
from app.simulation.room import RoomSettings

STYLE = """
h2 { color: #1c4265; font-size: 15px; margin-top: 18px; }
p { margin: 4px 0; }
.eq { font-family: 'Cambria Math', 'Cambria', serif; font-size: 16px; font-weight: normal; margin: 6px 0 6px 24px; }
.note { color: #626262; }
.code { font-family: 'Consolas'; color: #454545; }
th { background: #e9e9e9; text-align: left; }
"""


def _table(header: tuple[str, ...], rows: list[tuple]) -> str:
    head = "".join(f"<th>{cell}</th>" for cell in header)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table border='1' cellspacing='0' cellpadding='5' style='border-color:#c3c3c3'><tr>{head}</tr>{body}</table>"


def _eq(*lines: str) -> str:
    return "".join(f"<p class='eq'>{line}</p>" for line in lines)


def motor_equations(config: Configuration) -> str:
    p, g, t = config.plant, config.controller, config.timing
    w = config.target_rpm / RPM
    current = (p.friction * w + p.load_torque * math.tanh(w / 2)) / p.torque_constant
    voltage = p.resistance * current + p.back_emf * w
    return f"""
<h2>1&nbsp;&nbsp;Motor (plant) - two states: speed ω [rad/s] and current i [A]</h2>
{_eq("J · dω/dt = K<sub>t</sub> · i - (b + Δb) · ω - (T<sub>L</sub> + ΔT<sub>L</sub>) · tanh(ω / 2)",
     "L · di/dt = u<sub>a</sub> - R · k<sub>R</sub> · i - K<sub>e</sub> · ω")}
<p>First line: torque balance (motor torque minus friction minus load accelerates the rotor).
Second line: voltage balance of the winding (applied voltage minus resistive drop minus back-EMF changes the current).
tanh(ω/2) makes the load torque fade smoothly to zero at standstill. Without faults Δb = 0, ΔT<sub>L</sub> = 0, k<sub>R</sub> = 1.</p>
{_table(("Symbol", "Meaning", "Value"), [
    ("J", "rotor + load inertia", f"{p.inertia:g} kg·m²"), ("L", "winding inductance", f"{p.inductance:g} H"),
    ("R", "winding resistance", f"{p.resistance:g} Ω"), ("K<sub>t</sub>", "torque constant", f"{p.torque_constant:g} N·m/A"),
    ("K<sub>e</sub>", "back-EMF constant", f"{p.back_emf:g} V·s/rad"), ("b", "viscous friction", f"{p.friction:g} N·m·s/rad"),
    ("T<sub>L</sub>", "nominal load torque", f"{p.load_torque:g} N·m"), ("U<sub>max</sub>", "supply limit", f"±{p.supply_voltage:g} V")])}
<p>Useful derived numbers: electrical time constant L/R = {p.inductance / p.resistance:.3f} s;
mechanical time constant J·R/(K<sub>t</sub>·K<sub>e</sub>) = {p.inertia * p.resistance / (p.torque_constant * p.back_emf):.2f} s.
Steady state at the target {config.target_rpm:.0f} rpm: i = (b·ω + T<sub>L</sub>·tanh(ω/2)) / K<sub>t</sub> = {current:.2f} A,
u = R·i + K<sub>e</sub>·ω = {voltage:.1f} V.</p>

<h2>2&nbsp;&nbsp;Numerical integration - RK4, Δt = 1/{t.physics_hz} s</h2>
{_eq("x = (ω, i),&nbsp;&nbsp; dx/dt = f(x, u<sub>a</sub>)",
     "k<sub>1</sub> = f(x<sub>n</sub>),&nbsp; k<sub>2</sub> = f(x<sub>n</sub> + ½Δt·k<sub>1</sub>),&nbsp; "
     "k<sub>3</sub> = f(x<sub>n</sub> + ½Δt·k<sub>2</sub>),&nbsp; k<sub>4</sub> = f(x<sub>n</sub> + Δt·k<sub>3</sub>)",
     "x<sub>n+1</sub> = x<sub>n</sub> + Δt/6 · (k<sub>1</sub> + 2k<sub>2</sub> + 2k<sub>3</sub> + k<sub>4</sub>)")}
<p class='note'>The voltage is held constant during each step. Code: app/simulation/plant.py.</p>

<h2>3&nbsp;&nbsp;Speed controller - PI + feedforward, every {1000 / t.control_hz:g} ms</h2>
{_eq(f"ω<sub>ref</sub> ← ω<sub>ref</sub> + clamp(ω* - ω<sub>ref</sub>, ±r·Δt<sub>c</sub>),&nbsp;&nbsp; r = {g.reference_ramp_rpm_s:g} rpm/s",
     "e = ω<sub>ref</sub> - ω<sub>m</sub>",
     "u<sub>ff</sub> = K<sub>e</sub>·ω<sub>ref</sub> + R·(b·ω<sub>ref</sub> + T<sub>L</sub>) / K<sub>t</sub>",
     "u<sub>raw</sub> = u<sub>ff</sub> + K<sub>p</sub>·e + I,&nbsp;&nbsp; u<sub>cmd</sub> = clamp(u<sub>raw</sub>, ±U<sub>max</sub>)",
     "I ← I + (K<sub>i</sub>·e + K<sub>aw</sub>·(u<sub>cmd</sub> - u<sub>raw</sub>))·Δt<sub>c</sub>")}
<p>The reference ramps towards the target. Feedforward supplies the voltage the nominal motor needs at that speed;
PI corrects the rest. When the supply limit clips the command, the anti-windup term K<sub>aw</sub>·(u<sub>cmd</sub> - u<sub>raw</sub>)
stops the integral from growing. Gains: K<sub>p</sub> = {g.kp:g}, K<sub>i</sub> = {g.ki:g}, K<sub>aw</sub> = {g.antiwindup:g}.
The controller reads the <i>measured</i> speed, so sensor faults change the physical motion too.</p>

<h2>4&nbsp;&nbsp;Sensors - every {1000 / t.control_hz:g} ms</h2>
{_eq("ω<sub>m</sub> = ω + n<sub>ω</sub>,&nbsp;&nbsp; n<sub>ω</sub> ~ N(0, (2 rpm)²)",
     "i<sub>m</sub> = i + n<sub>i</sub>,&nbsp;&nbsp; n<sub>i</sub> ~ N(0, (0.025 A)²)")}

<h2>5&nbsp;&nbsp;Faults - severity s ∈ (0, 1], optional ramp</h2>
{_eq("s(t) = severity · min(1, (t - t<sub>on</sub>) / t<sub>ramp</sub>)")}
{_table(("Fault", "Where it acts", "Equation change"), [
    ("Encoder bias", "sensor", "ω<sub>m</sub> += 35·s rad/s"),
    ("Encoder noise", "sensor", "ω<sub>m</sub> += N(0, (70·s rpm)²)"),
    ("Actuator loss", "actuator", "u<sub>a</sub> = u<sub>cmd</sub> · (1 - 0.65·s)"),
    ("Actuator stuck", "actuator", "u<sub>a</sub> = u<sub>cmd</sub>(t<sub>on</sub>) · (1 - 0.65·s), held"),
    ("External load", "plant", "ΔT<sub>L</sub> = 1.1·s N·m"),
    ("Friction", "plant", "Δb = 0.015·s N·m·s/rad"),
    ("Resistance", "plant", "k<sub>R</sub> = 1 + 1.5·s"),
    ("Unknown combination", "sensors", "i<sub>m</sub> ×= (1 + 0.5·s); ω<sub>m</sub> ×= (1 - 0.55·s) in 1 of every 4 slots of 0.18 s")])}

<h2>6&nbsp;&nbsp;Nominal predictor and residuals</h2>
{_eq("dx̂/dt = f<sub>nominal</sub>(x̂, u<sub>cmd</sub>) + K·(y<sub>m</sub> - ŷ),&nbsp;&nbsp; with K = 0,&nbsp;&nbsp; x̂(0) = x(0) = 0",
     "r<sub>ω</sub> = ω<sub>m</sub> - ω̂ [rpm],&nbsp;&nbsp; r<sub>i</sub> = i<sub>m</sub> - î [A]")}
<p>The predictor is the same motor model fed with the <i>commanded</i> voltage and nominal parameters.
A Kalman filter would correct x̂ with the measurements through a gain K; here K = 0 on purpose, so a fault is not
absorbed into the estimate and stays visible in the residuals r. Healthy motor → r ≈ noise only.</p>

<h2>7&nbsp;&nbsp;Features over the last W = {t.feature_window:g} s (N samples at {t.feature_hz} Hz)</h2>
{_eq("mean r̄ = (1/N)·Σ r<sub>n</sub>,&nbsp;&nbsp; RMS = √((1/N)·Σ r<sub>n</sub>²),&nbsp;&nbsp; σ = √((1/N)·Σ (r<sub>n</sub> - r̄)²)",
     "trend β = Σ (t<sub>n</sub> - t̄)·r<sub>n</sub> / Σ (t<sub>n</sub> - t̄)²,&nbsp;&nbsp; "
     "detrended noise = std(r<sub>n</sub> - β·(t<sub>n</sub> - t̄))",
     "electrical mismatch E = L·β<sub>i</sub> + R·ī<sub>m</sub> + K<sub>e</sub>·ω̄<sub>m</sub> - ū<sub>cmd</sub>&nbsp;&nbsp; [V]&nbsp;&nbsp; (voltage deficit = -E)",
     "extra torque M = K<sub>t</sub>·ī<sub>m</sub> - b·ω̄<sub>m</sub> - J·β<sub>ω</sub> - T<sub>L</sub>·tanh(ω̄<sub>m</sub>/2)&nbsp;&nbsp; [N·m]")}
<p>E and M put the measured averages back into the nominal equations. If the motor were healthy both would be ≈ 0.
M &gt; 0 means something resists more than expected (load, friction). E &lt; 0 means less voltage reaches the winding
than was commanded (actuator loss/stuck) or the resistance grew. Code: app/diagnostics/features.py.</p>

<h2>8&nbsp;&nbsp;Anomaly detector</h2>
{_eq("S = max( RMS<sub>ω</sub> / 35 rpm,&nbsp; RMS<sub>i</sub> / 0.6 A,&nbsp; σ<sub>ω</sub> / 12 rpm )")}
{_table(("Condition", "Result"), [
    ("t &lt; 1.5 s", "normal (warm-up)"), ("S ≥ 1", "suspected anomaly"),
    ("S ≥ 1 for 0.3 s", "confirmed anomaly"), ("S &lt; 0.65 for 0.6 s", "back to normal")])}

<h2>9&nbsp;&nbsp;Model scores and the stable diagnosis</h2>
{_eq("m<sub>k</sub> = Σ exp(log p(token)) over returned tokens equal to option k's letter",
     "p<sub>k</sub> = ½ · ( m<sub>k</sub><sup>(1)</sup> / Σ<sub>j</sub> m<sub>j</sub><sup>(1)</sup> + "
     "m<sub>k</sub><sup>(2)</sup> / Σ<sub>j</sub> m<sub>j</sub><sup>(2)</sup> )&nbsp;&nbsp; (prompt 1 and reversed prompt 2)",
     "EMA:&nbsp; s<sub>k</sub> ← 0.5 · p<sub>k</sub> + 0.5 · s<sub>k</sub>")}
{_table(("Rule", "Value"), [
    ("winner EMA score ≥", f"{config.min_diagnosis_score:g}"), ("lead over second place ≥", "0.10"),
    ("to replace an accepted diagnosis: lead over it ≥", "0.12"),
    ("same winner in consecutive decisions ≥", "2"), ("persistence ≥", f"{config.diagnosis_persistence:g} s"),
    ("healthy accepted only when the detector is", "normal"), ("a fault accepted only when the detector is", "not normal"),
    ("dropped to unresolved when", f"score &lt; 0.7 × {config.min_diagnosis_score:g} twice, or no result for {t.result_max_age:g} s")])}
<p class='note'>Scores are normalized token masses - how strongly the model prefers each letter - not calibrated
probabilities of physical faults.</p>
"""


def room_equations(settings: RoomSettings, interval: float) -> str:
    s = settings
    tau = s.capacity / s.conductance
    heat_rate = (s.heater_watts - s.conductance * (s.target - s.outside)) / s.capacity * 60
    cool_rate = s.conductance * (s.target - s.outside) / s.capacity * 60
    return f"""
<h2>1&nbsp;&nbsp;Room (plant) - one state: temperature T [°C]</h2>
{_eq("C · dT/dt = u·P<sub>h</sub> + P<sub>d</sub> - k<sub>w</sub>·G·(T - T<sub>out</sub>)",
     "u ∈ {0 = OFF, 1 = ON},&nbsp;&nbsp; k<sub>w</sub> = 4 if the window is open, else 1")}
<p>Heat stored in the room changes with heater power, plus any disturbance, minus the heat lost to outside.</p>
{_table(("Symbol", "Meaning", "Value"), [
    ("C", "effective thermal capacity", f"{s.capacity / 1000:g} kJ/K"), ("G", "heat transfer to outside (window closed)", f"{s.conductance:g} W/K"),
    ("P<sub>h</sub>", "heater power when ON", f"{s.heater_watts:g} W"), ("T<sub>out</sub>", "outside temperature", f"{s.outside:g} °C"),
    ("T*", "desired temperature", f"{s.target:g} °C"), ("δ", "switching band", f"±{s.deadband:g} °C")])}

<h2>2&nbsp;&nbsp;Exact solution between events</h2>
{_eq("T<sub>eq</sub> = T<sub>out</sub> + (u·P<sub>h</sub> + P<sub>d</sub>) / (k<sub>w</sub>·G)",
     "T(t + Δ) = T<sub>eq</sub> + (T(t) - T<sub>eq</sub>) · e<sup>-k<sub>w</sub>·G·Δ / C</sup>")}
<p>With constant inputs the temperature moves exponentially towards T<sub>eq</sub>. The code applies this exactly
in steps of at most 1 s, and splits steps where a heat pulse ends.
Time constant C/G = {tau:.0f} s = {tau / 60:.1f} min. With the heater always ON the room would settle at
{s.outside + s.heater_watts / s.conductance:.1f} °C. Near the target, heating ON raises T by about {heat_rate:.2f} °C/min
and OFF lowers it by about {cool_rate:.2f} °C/min.</p>

<h2>3&nbsp;&nbsp;Control rule the model is asked to follow (bang-bang with hysteresis)</h2>
{_eq(f"T ≤ T* - δ = {s.target - s.deadband:g} °C&nbsp;&nbsp; ⇒&nbsp;&nbsp; u = ON",
     f"T ≥ T* + δ = {s.target + s.deadband:g} °C&nbsp;&nbsp; ⇒&nbsp;&nbsp; u = OFF",
     "otherwise&nbsp;&nbsp; ⇒&nbsp;&nbsp; u = previous u")}
<p>The model decides every {interval:g} simulated seconds; the command is held in between (zero-order hold),
so the temperature can pass a threshold by up to about {max(heat_rate, cool_rate) * interval / 60:.2f} °C before the next decision.
Whatever the model answers is applied, even when it breaks this rule - no thermostat takes over.</p>

<h2>4&nbsp;&nbsp;Disturbances</h2>
{_table(("Type", "Effect"), [
    ("Temperature spike", "T ← T + ΔT, instantly"), ("Heat step (Heaviside)", "P<sub>d</sub> = P until cleared"),
    ("Heat pulse", "P<sub>d</sub> = P for the chosen duration"), ("Open window", "k<sub>w</sub> = 4 until closed")])}
"""
