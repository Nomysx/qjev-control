# QJev Control Lab

Desktop lab for two control use cases that use the QJev language model through a local Ollama server:

- **Motor:** a simulated DC motor speed loop with injectable faults. A deterministic residual detector finds faults; QJev chooses which of nine fault hypotheses explains them. QJev never acts on the motor.
- **Room temperature:** a simulated room where QJev is the controller and switches the heater ON or OFF (bang-bang with hysteresis).

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally, with the model installed (check with `ollama list`). Default recomended model: `qjev-0.8b:latest`. Model card: [QJev3.5-0.8B-GGUF](https://huggingface.co/ZY-Lee4/QJev3.5-0.8B-GGUF).

The simulations run without Ollama; only model decisions need it.

## Install and run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Command-line options

| Option | Default | Meaning |
| --- | --- | --- |
| `--scenario` | `sensor_bias` | Motor use case loaded at start |
| `--ollama-url` | `http://127.0.0.1:11434` | Ollama server |
| `--model` | `qjev-0.8b:latest` | Ollama model tag |
| `--readout` | `letters` | `letters`: one prompt with lettered options, asked in given and reversed order. `legacy_yes_no`: one Yes/No prompt per option |
| `--no-qjev` | off | Run without model inference |
| `--headless` | off | Run the motor simulation without a window or model and print the evaluation summary |
| `--duration` | `20` | Headless run length in simulated seconds |
| `--export` | none | Headless: write CSV, JSON and diagnostic JSONL files |
| `--seed` | per scenario | Random seed |

Scenarios: `healthy`, `sensor_bias`, `sensor_noise`, `load`, `actuator_loss`, `actuator_stuck`, `friction`, `resistance`, `unknown`. Scenario faults start at 6 s.

```powershell
python main.py --headless --scenario load --duration 20 --export load_run.csv
```

## Exports

**Export run** in the Motor tab (or `--export` in headless mode) writes:

- `<name>.csv`: the full signal history: measurements, predictions, commands, residuals, detector state and diagnosis.
- `<name>.json`: configuration, seed, events and evaluation summary.
- `<name>_diagnostics.jsonl`: every model request, with its context, raw and normalized scores, latency and errors.

Export before Reset or closing; the run history is discarded then.

## Project layout

```text
main.py              entry point and command-line options
app/config.py        plant, controller and timing defaults
app/simulation/      motor (RK4), PI controller, predictor, faults, room, simulation engine
app/diagnostics/     features, anomaly detector, Ollama client, diagnosis filter
app/experiments/     scenarios, metrics, run history and export
app/ui/              PySide6 windows, plots, How it works tab
```

## Limitations

- Model scores are normalized token probabilities.
- The model is small and sensitive to wording; it can misclassify, especially early in a transient. Its answers are shown and logged as they are; nothing replaces a wrong answer.
- Load and friction at a single steady speed are hard to tell apart. Change the target speed to add information.
- Detector thresholds are tuned for the default plant and noise; retune them if those change substantially.
