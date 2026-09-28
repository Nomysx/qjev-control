import argparse
import json
import sys

from app.config import Configuration
from app.experiments.scenarios import SCENARIOS


def main() -> int:
    parser = argparse.ArgumentParser(description="DC motor control and QJev fault isolation workstation")
    parser.add_argument("--scenario", choices=SCENARIOS, default="sensor_bias")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qjev-0.8b:latest")
    parser.add_argument("--readout", choices=("letters", "legacy_yes_no"), default="letters")
    parser.add_argument("--no-qjev", action="store_true", help="Start with deterministic diagnostics only")
    parser.add_argument("--headless", action="store_true", help="Run a numerical use case without Qt or inference")
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--export", help="Export CSV, metadata JSON and diagnostic JSONL")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    config = Configuration(ollama_url=args.ollama_url, model=args.model, readout=args.readout,
                           seed=args.seed if args.seed is not None else SCENARIOS[args.scenario].seed)
    if args.headless:
        from app.simulation.engine import Simulation
        simulation = Simulation(config, args.scenario)
        try:
            simulation.advance(args.duration)
            if args.export:
                simulation.export(args.export)
            print(json.dumps(simulation.metrics.summary(simulation.diagnosis.active, simulation.truth), indent=2))
        finally:
            simulation.close()
        return 0
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    application = QApplication(sys.argv[:1])
    application.setApplicationName("QJEV CONTROL")
    window = MainWindow(config, args.scenario, model_enabled=not args.no_qjev)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
