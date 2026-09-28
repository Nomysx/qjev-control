"""How it works: signal-flow diagrams, equations and the exact model requests of both use cases."""

from dataclasses import asdict
from html import escape
import json
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGroupBox, QLabel, QPlainTextEdit, QScrollArea, QTabWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from app.config import Configuration
from app.diagnostics.features import diagnostic_context
from app.diagnostics.qjev_client import (HYPOTHESES, LETTER_TOP_LOGPROBS, QUESTION, SYSTEM_INSTRUCTION,
                                         YES_NO_TOP_LOGPROBS, QJevOllamaClient, option_letters)
from app.simulation.faults import FAULT_NAMES
from app.simulation.room import HEATER_OPTIONS, HEATER_QUESTION, RoomSettings
from app.ui.diagrams import BlockDiagram, diagnostic_chain, motor_loop, readout, room_loop
from app.ui.equations import STYLE, motor_equations, room_equations

# plain-language meaning of every request field sent to Ollama
REQUEST_MEANINGS = {
    "raw": "Sent verbatim, no chat template added",
    "top_logprobs": "Alternative tokens returned",
    "num_predict": "One answer token",
    "temperature": "Deterministic",
}


def _text(html: str = "") -> QLabel:
    label = QLabel(html)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _note(text: str) -> QLabel:
    label = _text(text)
    label.setObjectName("muted")
    return label


def _table(header: tuple[str, ...], rows: list[tuple]) -> str:
    head = "".join(f"<th align='left' style='background:#e9e9e9'>{cell}</th>" for cell in header)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return (f"<table width='100%' border='1' cellspacing='0' cellpadding='5' style='border-color:#c3c3c3'>"
            f"<tr>{head}</tr>{body}</table>")


def _sections(sections: list[tuple[str, list[QWidget]]]) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(8, 4, 8, 8)
    for title, widgets in sections:
        box = QGroupBox(title)
        box_layout = QVBoxLayout(box)
        for widget in widgets:
            box_layout.addWidget(widget)
        layout.addWidget(box)
    layout.addStretch()
    return page


def _identifier(key: str) -> str:
    return f"<span style='font-family:Consolas'>{escape(key)}</span>"


def _page(sections: list[tuple[str, list[QWidget]]]) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(_sections(sections))
    return scroll


def _browser() -> QTextBrowser:
    browser = QTextBrowser()
    browser.document().setDefaultStyleSheet(STYLE)
    return browser


class PromptView(QScrollArea):
    """Everything one model decision sends, split into numbered sections in request order."""

    def __init__(self, client: QJevOllamaClient, question: str, options: list[dict[str, str]],
                 purpose: str, answer_use: str):
        super().__init__()
        self.client, self.question, self.options = client, question, options
        self.state = None
        letters = client.readout == "letters"
        top = LETTER_TOP_LOGPROBS if letters else YES_NO_TOP_LOGPROBS
        requests = 2 if letters else len(options)

        settings = [("endpoint", f"POST {escape(client.endpoint)}", ""),
                    ("timeout", f"{client.timeout:g} s", "No reply in time: no decision")]
        for key, value in client.payload("", top).items():
            for name, item in (value.items() if isinstance(value, dict) else [(key, value)]):
                if name != "prompt":
                    settings.append((name, escape(item if isinstance(item, str) else json.dumps(item)),
                                     REQUEST_MEANINGS.get(name, "")))
        settings.append(("requests per decision", str(requests),
                         "Given and reversed option order" if letters else "One Yes/No question per option"))

        if letters:
            first, second = (option_letters(ordering) for ordering in client.orderings(options))
            by_id = ({key: letter for letter, key in first.items()}, {key: letter for letter, key in second.items()})
            option_rows = [(f"<b>{by_id[0][o['id']]}</b>", f"<b>{by_id[1][o['id']]}</b>", _identifier(o["id"]),
                            escape(o["description"])) for o in options]
            option_table = _table(("Prompt 1", "Prompt 2", "Id", "Text"),
                                  option_rows)
            instruction = _text(f"<i>{escape(SYSTEM_INSTRUCTION)}</i>")
        else:
            option_table = _table(("Id", "Text"), [(_identifier(o["id"]), escape(o["description"]))
                                                                     for o in options])
            instruction = _text("None")

        self.state_text = QPlainTextEdit()
        self.state_text.setReadOnly(True)
        self.state_text.setFixedHeight(130)
        self.state_source = _note("")
        self.prompt_tabs = QTabWidget()
        self.prompt_tabs.setMinimumHeight(360)
        self.prompt_views = []
        for title, _ in client.prompts("", question, options):
            view = QPlainTextEdit()
            view.setReadOnly(True)
            view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            self.prompt_tabs.addTab(view, title)
            self.prompt_views.append(view)

        if letters:
            steps = ["Prompt 2 reverses the option order to cancel letter-position bias.",
                     "A missing letter, HTTP error or timeout gives no decision.", answer_use]
        else:
            steps = [f"One prompt per option; score = mass of Yes/True tokens in the top {top}, normalized over options.",
                     "A missing Yes/True token, HTTP error or timeout gives no decision.", answer_use]
        how = [_text("<ul>" + "".join(f"<li>{step}</li>" for step in steps) + "</ul>")]
        if letters:
            how.insert(0, BlockDiagram(*readout(top)))

        page = _sections([
            ("1  PURPOSE", [_text(purpose)]),
            ("2  REQUEST SETTINGS", [_text(_table(("Setting", "Value", "Meaning"), settings))]),
            ("3  SYSTEM INSTRUCTION", [instruction]),
            ("4  QUESTION", [_text(f"<i>{escape(question)}</i>")]),
            ("5  OPTIONS", [_text(option_table)]),
            ("6  STATE", [self.state_source, self.state_text]),
            ("7  READOUT", how),
            ("8  PROMPT TEXT", [self.prompt_tabs]),
        ])
        self.setWidgetResizable(True)
        self.setWidget(page)

    def show_state(self, state: str, source: str) -> None:
        self.state_source.setText(source)
        if state == self.state:
            return
        self.state = state
        self.state_text.setPlainText(state)
        for view, (_, prompt) in zip(self.prompt_views, self.client.prompts(state, self.question, self.options)):
            view.setPlainText(prompt)


class ExplainPanel(QWidget):
    def __init__(self, motor_client: QJevOllamaClient, room_client: QJevOllamaClient, config: Configuration):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 6)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.config_key = self.room_key = None

        self.motor_loop = BlockDiagram(*motor_loop(config))
        self.motor_chain = BlockDiagram(*diagnostic_chain(config))
        self.motor_timing = _text()
        self.tabs.addTab(_page([
            ("1  CONTROL LOOP", [self.motor_loop]),
            ("2  DIAGNOSTIC CHAIN", [self.motor_chain]),
            ("3  TIMING", [self.motor_timing]),
        ]), "Motor: signal flow")
        self.motor_formulas = _browser()
        self.tabs.addTab(self.motor_formulas, "Motor: equations")
        self.motor_prompt = PromptView(
            motor_client, QUESTION, HYPOTHESES,
            "Fault isolation: picks the fault hypothesis that best explains the residual features. Requested on "
            "detector anomalies and twice while healthy. Does not act on the motor.",
            "Scores go to the diagnosis filter.")
        self.tabs.addTab(self.motor_prompt, "Motor: model prompt")

        self.room_loop = BlockDiagram(*room_loop(RoomSettings(), 30))
        self.tabs.addTab(_page([
            ("1  CONTROL LOOP", [self.room_loop]),
        ]), "Room: signal flow")
        self.room_formulas = _browser()
        self.tabs.addTab(self.room_formulas, "Room: equations")
        self.room_prompt = PromptView(
            room_client, HEATER_QUESTION, HEATER_OPTIONS,
            "Bang-bang controller: chooses heater ON or OFF every control interval.",
            "The highest score is applied to the heater, even if it breaks the rule.")
        self.tabs.addTab(self.room_prompt, "Room: model prompt")

    def refresh(self, motor, room, room_interval: float) -> None:
        config = motor.config
        key = json.dumps(asdict(config), sort_keys=True)
        if key != self.config_key:
            self.config_key = key
            self.motor_loop.set_diagram(*motor_loop(config)[1:])
            self.motor_chain.set_diagram(*diagnostic_chain(config)[1:])
            self.motor_formulas.setHtml(motor_equations(config))
            t = config.timing
            self.motor_timing.setText(_table(("Loop", "Rate", "Clock"), [
                ("Physics (RK4)", f"{t.physics_hz} Hz", "simulated"), ("Sensors and PI control", f"{t.control_hz} Hz", "simulated"),
                ("Features and detector", f"{t.feature_hz} Hz", "simulated"),
                ("Model request", f"at most every {t.qjev_interval:g} s", "simulated and wall"),
                ("Plots and panels", f"{t.ui_hz} Hz", "wall")]))
        room_key = (json.dumps(asdict(room.settings), sort_keys=True), room_interval)
        if room_key != self.room_key:
            self.room_key = room_key
            self.room_loop.set_diagram(*room_loop(room.settings, room_interval)[1:])
            self.room_formulas.setHtml(room_equations(room.settings, room_interval))

        row = motor.last_row
        if row:
            top = max(motor.last_decision.scores.values()) if motor.last_decision else float("nan")
            self.motor_loop.set_values({
                "target": f"{row['target_rpm']:.0f} rpm", "command": f"{row['command_v']:.1f} V",
                "applied": f"{row['applied_v']:.1f} V", "true_speed": f"{row['true_speed_rpm']:.0f} rpm",
                "measured_speed": f"{row['measured_speed_rpm']:.0f} rpm"})
            self.motor_chain.set_values({
                "command": f"{row['command_v']:.1f} V", "residual": f"{row['speed_residual_rpm']:+.0f} rpm",
                "score": f"{motor.detector.score:.2f}", "top_score": f"top {top:.0%}" if math.isfinite(top) else "",
                "diagnosis": FAULT_NAMES.get(motor.diagnosis.active, "unresolved")})
        if motor.last_request_time is not None:
            self.motor_prompt.show_state(motor.last_context, f"Sent at t = {motor.last_request_time:.2f} s")
        elif motor.last_features:
            self.motor_prompt.show_state(diagnostic_context(motor.last_features),
                                         f"Preview at t = {motor.time:.2f} s, not sent yet")
        else:
            self.motor_prompt.show_state("", "Start the motor use case")

        self.room_loop.set_values({
            "target": f"{room.settings.target:.1f} °C", "heater": "ON" if room.heater else "OFF",
            "power": f"{room.settings.heater_watts if room.heater else 0:.0f} W",
            "disturbance": f"{room.disturbance_watts:+.0f} W" if room.disturbance_watts else "",
            "loss": f"{room.loss_watts:.0f} W", "temperature": f"{room.temperature:.2f} °C"})
        self.room_prompt.show_state(room.context(), f"At t = {room.time / 60:.2f} min, sent at the next decision")
