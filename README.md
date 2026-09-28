# QJev Motor Lab

A Python desktop workstation for residual-based fault detection and QJev fault isolation in a DC motor speed loop. The motor, controller, nominal predictor and anomaly detector run independently of model inference.

## Install and launch

Python 3.11 or later is recommended. From this directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

The application opens paused. Select an experiment, choose **Load experiment**, then **Start**. Faults in the predefined experiments begin at simulated time 6 s. **Reset / apply settings** resets the selected experiment using the current parameter controls and random seed. Reset discards the current unexported run.

## Room temperature experiment

Open **Room temperature — Bang-bang**, set **Desired temperature**, and click **Start**. The configured local model selects heater ON or OFF at each control interval. The prompt supplies the current room temperature, setpoint, switching thresholds and previous heater command. Below the lower threshold it is asked to switch ON, above the upper threshold OFF, and inside the band to keep its previous state. The application applies the model's actual selected command, including incorrect decisions; it does not substitute a conventional thermostat.

- Defaults: initial room temperature 18 °C, target 22 °C, outside 5 °C, heater 3 kW, switching band ±0.3 °C, decisions every 30 simulated seconds, speed 60×.
- **Temperature spike** instantly changes room temperature by the signed amount. **Heat step (Heaviside)** adds a persistent signed heat input. **Heat pulse** adds that input for the selected duration. Positive power heats; negative power cools. **Open window** increases heat transfer to outside fourfold. Disturbance types can overlap; reinjecting a step or pulse replaces that type's previous value. **Clear / close window** ends ongoing disturbances; it does not undo accumulated temperature changes.
- Three plots show temperature and thresholds, the model's binary heater command, and heater/loss/disturbance power. **Plot view** expands any one chart to the whole plot area. The charts retain up to 18,000 samples and follow the latest hour of simulated time.
- The room follows `C dT/dt = heater + disturbance − G(T − outside)`, with effective thermal capacity 300 kJ/K and closed-window conductance 80 W/K. Each constant-input segment is integrated analytically, including pulse expiry boundaries. This is a simplified, well-mixed room experiment.
- Room settings apply live except **Initial (on reset)**. Changing settings or disturbances discards a pending decision and requests a fresh one. Simulated time waits during inference; speed controls time advancement between decisions. On a model error the run pauses, the heater switches OFF, and the event log records the error. Click Start to retry.
- Switching tabs pauses the experiment being left. The model name and OK/NOK status use the same connection as the motor experiment. `--no-qjev` disables starting this model-controlled experiment.

## How it works tab

The third tab explains both experiments inside the application. Each experiment has three pages:

- **Signal flow:** block diagrams of the control loop and, for the motor, the diagnostic chain beside it. Dashed red arrows show where injected faults act. Blue numbers on the arrows show the last simulated values.
- **Equations:** the plant, integration, controller, sensor, fault, predictor, feature, detector and scoring formulas. They are written as the code computes them and filled with the current parameters, plus derived time constants and steady-state values.
- **Model prompt:** the model request in eight numbered sections: purpose, request settings with the meaning of each field, system instruction, question, the option table with its letters in both orders, the state text, a diagram and steps showing how token log-probabilities become scores, and the exact raw prompt text of every request.

The prompt pages call the same functions (`letter_prompt`, `yes_no_prompt`, `QJevOllamaClient.payload/prompts`) that build the real requests, so the displayed text is exactly what is sent. For the motor, the state shown is the last one sent to the model, or a labelled preview if nothing has been sent yet. For the room, it is the text the next decision will send. Opening this tab pauses the experiment being left, like any other tab switch.

For deterministic control and anomaly detection without Ollama:

```powershell
python main.py --no-qjev
```

QJev uses the existing local configuration:

```text
Ollama URL: http://127.0.0.1:11434
Endpoint: POST /api/generate
Model: qjev-0.8b:latest
Raw prompt, non-streaming response, one generated token, token logprobs
```

The new workstation uses explicit IPv4 loopback to avoid the measured `localhost` connection fallback delay on this Windows installation. It reaches the same local Ollama service. The legacy client retains its original `localhost` default.

Ollama must be running and the model must already be installed. This project does not download weights or install Ollama. Check the local model with `ollama list`. Connection settings can be changed at launch:

```powershell
python main.py --ollama-url http://127.0.0.1:11434 --model qjev-0.8b:latest
```

The existing editable-example application remains available with `python qjev_test.py`. Its client now imports the reusable implementation from `app/diagnostics/qjev_client.py`.

## Reused integration and the necessary prompt correction

The original experiment used one raw Yes/No prompt per option, requested the top ten token logprobs, added the observed `Yes`/`True` token masses, and normalized those masses. That exact readout remains available:

```powershell
python main.py --readout legacy_yes_no
```

A real call to the installed model during implementation returned `A` to the original Yes/No prompt, without an affirmative token in the returned alternatives. Treating that as a zero score would hide a protocol mismatch. The legacy readout now raises an explicit error when required logprobs are absent; it never fabricates a fallback distribution.

The new workstation defaults to QJev's documented option-letter readout, using the same native Ollama transport. It supplies all nine hypotheses in a Qwen chat-formatted raw prompt with thinking closed, requests the top 20 logprobs, and extracts the observed single-letter token masses. It scores the normal and reversed option order and averages their normalized distributions. These are two requests for one diagnostic decision. Any missing option label, malformed logprob, HTTP error, cancellation or timeout invalidates the decision. A run of all eight known/unknown faults is not guaranteed to be correctly classified by this small model.

Primary reference: [QJev model card](https://huggingface.co/ZY-Lee4/QJev3.5-0.8B-GGUF). The locally installed tag is user-managed; the application does not assert its source or checkpoint version.

### Meaning of the displayed values

- **Raw output:** measured next-token mass from returned logprobs, grouped by option and prompt order. These are language-model token statistics, not measured frequencies of physical faults. Other spelling variants outside the returned top tokens are not included.
- **Model bars:** raw masses normalized across the available hypotheses; the letter readout averages two option orders. These are model scores, not calibrated fault probabilities. Expired snapshots remain visible in gray as historical scores, with no current winner highlight.
- **EMA:** an exponential moving average with weight 0.5 on each new decision. It is a stabilization statistic.
- **Stable diagnosis:** requires a minimum EMA score (default 0.42), a 0.10 lead, at least two supporting decisions, and one simulated second of persistence. Changing a diagnosis also requires a 0.12 lead over the old class. A healthy detector prevents accepting a fault label, and an abnormal detector prevents accepting healthy. Sustained weak support or stale evidence removes an accepted diagnosis.
- **Entropy:** normalized entropy of the model scores. It describes how spread out the scores are, not the probability of being wrong.

The `unknown` hypothesis is a real option presented to QJev. The application never silently substitutes it for invalid output. Low separation leaves the diagnosis unresolved. All errors are shown as **QJev unavailable**, while the deterministic simulation continues.

## Engineering model

The two physical states are angular velocity `omega` in rad/s and armature current `i` in A:

```text
J * domega/dt = Kt * i - b * omega - load * tanh(omega / 2)
L * di/dt     = applied_voltage - R * i - Ke * omega
```

The smooth resisting-load term avoids an artificial acceleration through zero at standstill. At operating speed it is effectively a constant load torque. Dynamics are integrated by fixed-step RK4.

| Parameter | Default |
| --- | --- |
| Rotor/load inertia J | 0.025 kg m2 |
| Armature inductance L | 0.04 H |
| Armature resistance R | 0.6 ohm |
| Torque constant Kt | 0.12 N m/A |
| Back-EMF constant Ke | 0.12 V s/rad |
| Viscous friction b | 0.003 N m s/rad |
| Nominal resisting load | 0.25 N m |
| Bipolar supply limit | +/-48 V |
| Initial target | 1800 rpm |
| PI gains Kp / Ki | 0.24 / 0.9 |

The speed controller uses a 900 rpm/s reference ramp, nominal steady-state voltage feedforward, PI feedback and back-calculation anti-windup. It reads the faulty encoder, so sensor faults affect the physical response. Requested voltage is limited by the supply, then actuator faults modify the voltage delivered to the plant. QJev never enters this control path.

The observer is a **parallel nominal predictor** initialized at rest. It integrates the nominal equations using requested voltage. It does not use injected fault labels, true speed, true current, or actual faulty actuator voltage. It deliberately does not correct its states with faulty measurements. This preserves residual signatures but makes parameter mismatch and initial-state mismatch relevant: the simulator starts plant and predictor in the same known state.

Base measurement noise is independent Gaussian encoder noise of 2 rpm standard deviation and current noise of 0.025 A. Injected noise has a separate random generator, so switching a fault does not change the base noise sequence.

### Residual processing

Every feature update computes speed/current residual mean, RMS, standard deviation, peak and least-squares trend over a trailing 0.6 s window. It also computes tracking error, current trend, command mean/variation and controller saturation fraction. Detrended residual standard deviations separate irregular fluctuations from a smooth ramp; a large slope alone is not described to QJev as sensor noise.

Two additional physical balances use measured signals and nominal parameters:

```text
electrical mismatch = L * current_trend + R * mean_current
                      + Ke * mean_speed - mean_command_voltage
extra resisting torque = Kt * mean_current - b * mean_speed
                         - J * speed_trend - nominal_load
```

The electrical mismatch is negative for both reduced actuator voltage and increased winding resistance. Its sign alone cannot separate them. A positive voltage deficit in the context means the negative of this mismatch.

A bounded 12 s balance history supplies one-second trends, sign ranges and approximate rise durations. Rise duration measures the observed transition from the larger of the detection tolerance or 10% of the present magnitude to 90%. Mechanical rises of at least 1 s and electrical rises of at least 1.2 s are described as gradual. An onset summary is retained while the mismatch persists and cleared when it returns near zero.

A short 0.12 s electrical window also estimates motor voltage from measured speed/current and nominal parameters. Within an ongoing voltage-deficit episode, a linear fit measures how that voltage responds to changing commands. It requires more than 2 V of command variation and less than 0.5 V fit error. A valid response estimate can be retained after command saturation, and is discarded when the deficit clears or new observations disagree with it. This gives the model evidence about proportional voltage loss versus fixed voltage delivery. The estimate assumes nominal winding parameters; changing resistance and inadequate excitation can still cause ambiguity.

The anomaly score is the maximum of speed RMS / 35 rpm, current RMS / 0.6 A, and speed residual standard deviation / 12 rpm. Detection has three states. A score above 1 starts suspicion and confirms after 0.3 s. A score below 0.65 for 0.6 s clears detection. There is a 1.5 s startup warmup. These are explicit illustrative engineering thresholds and should be retuned if plant parameters or noise levels change substantially.

The QJev context is a compact numerical evidence summary. It emphasizes offsets, detrended fluctuations, the direction of current mismatch, and relevant temporal or command-response evidence. Speed/current mean tolerances are 35 rpm and 0.6 A; detrended fluctuation tolerances are 12 rpm and 0.3 A. Balance estimates that inherit encoder error are omitted for isolated sensor evidence. These rules describe measured features; they do not assign fault scores. Every displayed model score still comes from real QJev token logprobs. The context function receives features only, and the true fault is stored separately for evaluation.

## Faults and experiments

Severity ranges from 0.05 to 1. Each injected fault can have an onset delay, duration or persistence, and a ramp where applicable. Manual faults can overlap; overlapping truth is recorded as `unknown`. Clear removes active faults and pending schedules. Actuator-stuck onset is instantaneous even when a ramp is entered.

| Fault | Physical or measurement change at severity s |
| --- | --- |
| Encoder bias | Adds `35*s` rad/s to measured speed |
| Encoder noise | Adds Gaussian encoder noise with `70*s` rpm standard deviation |
| Actuator loss | Delivered voltage is command times `(1 - 0.65*s)` |
| Actuator stuck | Holds onset command times `(1 - 0.65*s)` |
| External load | Adds `1.1*s` N m resisting torque |
| Friction | Adds `0.015*s` N m s/rad viscous friction |
| Resistance | Multiplies winding resistance by `(1 + 1.5*s)` |
| Unknown combination | Current-sensor gain error plus intermittent encoder dropouts |

The predefined experiments distinguish offsets, noise, abrupt disturbances, gradual degradation and compound faults. Load and friction at one steady operating speed are not always identifiable from these signals. Change the speed setpoint to provide more information; `unknown` or an unresolved diagnosis is a valid result. The simulator does not encode the correct diagnosis into QJev's score.

Supervisory modes are advisory. The detector enters WATCH on suspicion and DEGRADED on confirmation. Confirmed sensor diagnoses flag SENSOR UNRELIABLE. An anomaly score of at least 8, or a confirmed anomaly with an accepted unknown diagnosis, produces SAFE ADVISORY. These labels never modify actuator output.

## Timing, responsiveness and inspection

| Loop | Default |
| --- | --- |
| Physics | 500 Hz simulated |
| Encoder sampling / PI control | 100 Hz simulated |
| Features / deterministic detector | 50 Hz simulated |
| QJev request eligibility | 1 s minimum, both wall and simulated time |
| UI / live plotting | 20 Hz wall time |

The Timing tab configures these rates at reset. Control and feature rates must divide physics rate, and features cannot exceed sensor rate. Numerically unsafe electrical parameter/rate combinations are rejected. Simulation speed is 0.1x to 10x. The UI bounds catch-up work to 0.1 wall seconds per tick, so a heavily overloaded computer may run slower than the requested speed without changing the integration step.

One background inference worker can be active at a time. There is no pending inference backlog. Automatic inference performs two baseline decisions, then operates on anomalies and performs two recovery checks. **Diagnose now** requests a fresh snapshot even while paused. Failed requests retry after a five-wall-second backoff. Pausing stops physical time but permits the current diagnostic request to complete. Reset invalidates results from the previous run. Inference does not block close.

Results older than eight simulated seconds are logged but rejected from stabilization. High simulation speeds can make inference stale; reduce speed or inspect a paused snapshot. The live panel shows measured latency and sample age. The requested interval is an upper bound on call frequency, not a promised model throughput.

Plots show speed, current, requested/applied voltage, both residuals, detector score and QJev score history. Fault onsets/clears and diagnosis transitions are marked. Pause and disable **Follow live** to pan/zoom; move the pointer over a plot to inspect nearby sampled values in the status bar. Live plot memory is bounded to 120 s at the configured feature rate. At startup the default is 6000 points per signal. The event log holds 200 entries and plot markers are bounded.

## Exports and evaluation

**Export run** writes three files:

- `motor_run.csv`: complete feature-rate numerical history, including simulation truth, measurements, nominal estimates, commands, residuals, detector states and held diagnostic scores with their source timestamp.
- `motor_run.json`: initial/final configuration, seed, event history, score semantics and evaluation summary.
- `motor_run_diagnostics.jsonl`: each real inference context, raw model scores, normalized scores, latency, capture/receipt time, error or stale-result flag. Ground truth here is explicitly evaluation-only.

Full signal and diagnostic histories are spooled to temporary disk files during a run; they are independent of the live plot buffer and are removed on reset/close. Export before resetting or closing. Model scores in CSV are sample-and-hold values, not additional model decisions. Raw and smoothed values are not converted into calibration claims.

Evaluation records per-fault detection and isolation delays, first valid model receipt, prediction-versus-truth confusion counts, false-positive detection episodes, incorrect accepted transitions, maximum residuals, mean inference latency and final diagnosis correctness. Delays use simulated time; inference latency uses wall time. Unresolved/unavailable diagnoses do not count as successful isolation. A restored healthy plant can retain residuals during predictor settling, which may affect recovery metrics. Controlled classification accuracy requires many runs and varied seeds; these illustrative experiments do not establish production accuracy.

A numerical run needs no Qt window or Ollama:

```powershell
python main.py --headless --scenario load --duration 20 --export load_run.csv
python main.py --headless --scenario unknown --duration 20 --seed 73
```

Headless mode intentionally runs deterministic physics and detection only. It reports the diagnosis as unresolved instead of creating model output.

## Source layout

```text
main.py                         command-line entry point
app/config.py                   physical, controller and timing defaults
app/simulation/                 RK4 motor, PI, predictor, faults, engine
app/diagnostics/                features, detector, Ollama client, worker, stabilization
app/experiments/                scenarios, metrics, spooled history/export
app/ui/                         PySide6 workstation, pyqtgraph signals, score inspection
app/ui/explain_panel.py         How it works tab; diagrams.py and equations.py supply its content
qjev_test.py                    original example launcher using the shared legacy client
qjev_examples.py / .json        original editable example storage
qjev_results.py                original Tkinter example viewer
```

The application has no mock inference mode. Python-level verification can inject test doubles without exposing fabricated results to application users. Visual review is left to the user.

## Verification and model limitations

Numerical checks verified the constant-voltage analytical equilibrium, RK4 step convergence, seeded trajectories independent of UI stepping, all eight injectable faults, absence of baseline false alarms in the predefined runs, bounded plot buffers and full-history exports. In the default experiments, deterministic detection delays were approximately 0.28-1.16 simulated seconds. Qt construction, timers, reset and responsiveness during real inference were checked without visual automation.

The previous dense numerical prompt made the installed `qjev-0.8b:latest` select `load` for every scenario. Its hypothesis descriptions also had the wrong electrical-residual sign for resistance drift. The revised context uses the compact evidence summary and temporal features described above, with corrected hypothesis descriptions. Transport, real token extraction and score normalization are preserved.

Real Ollama verification of the revised code produced:

| Check | Result |
| --- | --- |
| All nine scenarios, seed 42, t=9 s | 9/9 correct model winners |
| All nine scenarios, seed 137, fault severities multiplied by 0.8, t=9.5 s | 9/9 correct model winners |
| Sequential requests at t=8, 9 and 10 s, seed 42 | Eight correct accepted diagnoses by t=10 s; resistance remained unresolved |
| Additional resistance request at t=11 s | Correct resistance diagnosis accepted; the earlier incorrect t=8 s reading was never accepted |

Complete two-order decisions took approximately 0.86-1.06 wall seconds in the frozen-snapshot checks. Numerical regression checks confirmed that hidden truth, true plant states and actual actuator voltage do not affect extracted features or the context. Recovery clears cached onset/response evidence, reset starts empty, and temporal buffers remain bounded. Expired results are rejected from diagnosis acceptance.

These are small simulation checks, not a general accuracy benchmark. The model remains sensitive to wording and can misclassify early transients, including the observed resistance ramp. Other severities, simultaneous faults, changed plant/controller parameters and insufficient excitation need separate validation. The application preserves real model outputs and records mistakes rather than replacing them with the injected fault label. The conventional detector remains functional when the diagnostic classifier is wrong or unavailable. Visual review is left to the user.
