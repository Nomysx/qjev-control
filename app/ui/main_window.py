from copy import deepcopy
from time import monotonic

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QTabWidget, QVBoxLayout, QWidget)

from app.config import Configuration
from app.diagnostics.qjev_client import QJevOllamaClient
from app.diagnostics.service import DiagnosticService
from app.experiments.scenarios import SCENARIOS
from app.simulation.engine import Simulation
from app.simulation.faults import FAULT_NAMES, Fault
from app.ui.diagnostics_panel import DiagnosticsPanel
from app.ui.explain_panel import ExplainPanel
from app.ui.plots import SignalPlots
from app.ui.room_panel import RoomPanel


class _ModelCheckSignals(QObject):
    completed = Signal(bool, str)


class _ModelCheckWorker(QRunnable):
    def __init__(self, client: QJevOllamaClient):
        super().__init__()
        self.client = client
        self.signals = _ModelCheckSignals()

    def run(self) -> None:
        try:
            detail = self.client.check_model_available()
        except Exception as error:
            self.signals.completed.emit(False, str(error))
        else:
            self.signals.completed.emit(True, detail)


STYLE = """
QMainWindow, QWidget { background: #f3f3f3; color: #222222; font-family: 'Segoe UI'; font-size: 12px; }
QFrame#commandBar { background: #fafafa; border: 1px solid #b6b6b6; }
QGroupBox { background: #fafafa; border: 1px solid #a5a5a5; border-radius: 0; margin-top: 0; padding: 26px 8px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: padding; subcontrol-position: top left; left: 9px; top: 7px; color: #454545; background: transparent; padding: 0; }
QLabel#muted { color: #626262; font-size: 11px; }
QLabel#readout { font-size: 17px; font-weight: 600; color: #252525; }
QLabel#modelName { color: #555555; font-size: 11px; }
QLabel#modelHealth { border: 1px solid #999999; padding: 3px 6px; min-width: 30px; font-weight: 700; }
QLabel#modelHealth[health="checking"] { background: #eeeeee; border-color: #aaaaaa; color: #555555; }
QLabel#modelHealth[health="ok"] { background: #e7f3e9; border-color: #78a184; color: #24633a; }
QLabel#modelHealth[health="nok"] { background: #fff0ed; border-color: #b77b70; color: #842a20; }
QLabel#modelHealth[health="off"] { background: #eeeeee; border-color: #aaaaaa; color: #666666; }
QPushButton { background: #f7f7f7; border: 1px solid #858585; border-radius: 0; padding: 5px 10px; min-height: 21px; }
QPushButton:hover { background: #e7eef5; border-color: #526f8d; }
QPushButton:pressed { background: #d7e4f0; }
QPushButton:disabled { color: #888888; background: #ededed; border-color: #bcbcbc; }
QPushButton#primary { background: #e4edf6; border: 1px solid #647f9a; color: #1c4265; font-weight: 600; }
QPushButton#primary:hover { background: #d5e4f1; }
QPushButton#fault { background: #fff4f1; border: 1px solid #b77b70; color: #762c21; }
QPushButton#fault:hover { background: #f9e4df; }
QDoubleSpinBox, QSpinBox, QComboBox { background: #ffffff; border: 1px solid #888888; border-radius: 0; padding: 4px; min-height: 20px; selection-background-color: #c8dced; }
QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #c8dced; selection-color: #222222; border: 1px solid #888888; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; }
QTabWidget::pane { background: #ffffff; border: 1px solid #a0a0a0; top: -1px; }
QTabBar::tab { background: #e9e9e9; border: 1px solid #b3b3b3; padding: 6px 11px; color: #333333; }
QTabBar::tab:selected { background: #ffffff; border-bottom-color: #ffffff; }
QTabBar::tab:hover:!selected { background: #f5f5f5; }
QTextBrowser { background: #ffffff; border: 1px solid #a0a0a0; padding: 6px 10px; }
QPlainTextEdit, QTableWidget { background: #ffffff; border: 1px solid #a0a0a0; selection-background-color: #c8dced; selection-color: #222222; font-family: 'Consolas'; font-size: 11px; }
QTableWidget { gridline-color: #dedede; alternate-background-color: #f7f7f7; font-family: 'Segoe UI'; }
QHeaderView::section { background: #e9e9e9; color: #333333; border: 0; border-right: 1px solid #c3c3c3; border-bottom: 1px solid #a0a0a0; padding: 5px 4px; font-weight: 600; }
QProgressBar { border: 1px solid #b1b1b1; background: #eeeeee; text-align: center; color: #222222; font-size: 10px; margin: 3px 2px; min-height: 13px; }
QProgressBar::chunk { background: #6488a8; }
QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical, QScrollBar:horizontal { background: #eeeeee; border: 0; }
QScrollBar:vertical { width: 12px; }
QScrollBar:horizontal { height: 12px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #c4c4c4; border: 1px solid #aaaaaa; min-height: 24px; min-width: 24px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #adadad; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QStatusBar { background: #ededed; color: #444444; border-top: 1px solid #c5c5c5; }
QSplitter::handle { background: #d2d2d2; }
"""


def spin(value: float, low: float, high: float, step: float = 1.0, decimals: int = 2,
         suffix: str = "") -> QDoubleSpinBox:
    widget = QDoubleSpinBox()
    widget.setRange(low, high)
    widget.setDecimals(decimals)
    widget.setSingleStep(step)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setKeyboardTracking(False)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, config: Configuration | None = None, scenario: str = "sensor_bias", model_enabled: bool = True):
        super().__init__()
        self.config = deepcopy(config or Configuration())
        self.engine = Simulation(self.config, scenario)
        self.service = DiagnosticService(QJevOllamaClient(self.config.ollama_url, self.config.model,
                                                       self.config.request_timeout, self.config.readout))
        self.running = False
        self.generation = 0
        self.last_tick = monotonic()
        self.last_submit_wall = float("-inf")
        self.last_submit_sim = float("-inf")
        self.retry_after = 0.0
        self.normal_budget = 2
        self.previous_detector_state = "normal"
        self.model_enabled = model_enabled
        self._model_check_pending = False
        self._model_check_worker = None
        self._model_check_pool = QThreadPool.globalInstance()
        self.event_count = 0
        self.setWindowTitle("Control Lab | Motor and Room Temperature")
        self.resize(1680, 1000)
        self.setMinimumSize(1200, 760)
        self.setStyleSheet(STYLE)
        central = QWidget()
        self.sections = QTabWidget()
        self.setCentralWidget(self.sections)
        self.sections.addTab(central, "Motor")
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 6)
        root.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(7, 5, 7, 5)
        toolbar.setSpacing(8)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primary")
        self.pause_button = QPushButton("Pause")
        self.reset_button = QPushButton("Reset and apply settings")
        for button in (self.start_button, self.pause_button, self.reset_button):
            toolbar.addWidget(button)
        toolbar.addWidget(self._toolbar_divider())
        self.speed = spin(1, 0.1, 10, 0.5, 1, " x")
        self.target = spin(self.config.target_rpm, 0, 3500, 100, 0, " rpm")
        self.interval = spin(self.config.timing.qjev_interval, 0.1, 10, 0.1, 1, " s")
        for label, widget in (("Speed", self.speed), ("Target", self.target)):
            toolbar.addWidget(QLabel(label))
            toolbar.addWidget(widget)
        toolbar.addWidget(QLabel("Interval"))
        toolbar.addWidget(self.interval)
        self.diagnose_button = QPushButton("Run detector model")
        toolbar.addWidget(self.diagnose_button)
        toolbar.addStretch()
        root.addWidget(self._command_bar(toolbar))

        use_case = QHBoxLayout()
        use_case.setContentsMargins(7, 5, 7, 5)
        use_case.setSpacing(8)
        use_case.addWidget(QLabel("Use case"))
        self.scenario = QComboBox()
        for key, item in SCENARIOS.items():
            self.scenario.addItem(item.name, key)
        self.scenario.setMinimumWidth(235)
        self.scenario.setCurrentIndex(self.scenario.findData(scenario))
        use_case.addWidget(self.scenario)
        load = QPushButton("Load use case")
        use_case.addWidget(load)
        use_case.addWidget(self._toolbar_divider())
        use_case.addWidget(QLabel("Plot window"))
        self.window = spin(20, 5, 120, 5, 0, " s")
        self.window.setMaximumWidth(95)
        use_case.addWidget(self.window)
        self.follow = QCheckBox("Follow live")
        self.follow.setChecked(True)
        self.follow.setToolTip("Scroll with the latest data and restore automatic y scaling.")
        use_case.addWidget(self.follow)
        export = QPushButton("Export run")
        use_case.addWidget(export)
        use_case.addWidget(self._toolbar_divider())
        self.model_name_label = QLabel(f"Ollama: {self.config.ollama_url}  |  Model: {self.config.model}")
        self.model_name_label.setObjectName("modelName")
        self.model_name_label.setToolTip(f"Ollama endpoint: {self.config.ollama_url}")
        use_case.addWidget(self.model_name_label)
        self.model_health_indicator = QLabel()
        self.model_health_indicator.setObjectName("modelHealth")
        self.model_health_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.model_health_indicator.setMinimumWidth(54)
        use_case.addWidget(self.model_health_indicator)
        self._set_model_health("CHECKING" if self.model_enabled else "OFF",
                               "Checking whether the configured model is available." if self.model_enabled
                               else "Model inference is disabled by the startup option.")
        use_case.addStretch()
        root.addWidget(self._command_bar(use_case))

        self.readouts = {}
        status_row = QHBoxLayout()
        status_row.setSpacing(7)
        for key, caption in (("time", "TIME"), ("mode", "MODE"),
                             ("speed", "ENCODER / PREDICTED"), ("current", "CURRENT / COMMAND"),
                             ("truth", "FAULT TYPE")):
            box = QGroupBox(caption)
            line = QVBoxLayout(box)
            label = QLabel("--")
            label.setObjectName("readout")
            line.addWidget(label)
            self.readouts[key] = label
            status_row.addWidget(box)
        root.addLayout(status_row)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        split.addWidget(self._controls())
        self.plots = SignalPlots()
        split.addWidget(self.plots)
        self.diagnostics = DiagnosticsPanel()
        self.log = self.diagnostics.log
        self.diagnostics.setMinimumWidth(320)
        split.addWidget(self.diagnostics)
        split.setSizes([300, 880, 420])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        self.reset_button.clicked.connect(self.reset)
        load.clicked.connect(lambda: self.reset(use_scenario_seed=True))
        export.clicked.connect(self.export_dialog)
        self.target.valueChanged.connect(self._target_changed)
        self.interval.valueChanged.connect(self._interval_changed)
        self.diagnose_button.clicked.connect(lambda: self._submit(force=True))
        self.plots.inspected.connect(self.statusBar().showMessage)
        self.follow.toggled.connect(lambda checked: checked and self.plots.restore_scaling())
        self.room = RoomPanel(self.config, self.model_enabled)
        self.room.model_health.connect(self._set_model_health)
        self.room.set_model_health(self.model_health_indicator.text(), self.model_health_indicator.toolTip())
        self.sections.addTab(self.room, "Room temperature - Bang-bang")
        self.explain = ExplainPanel(self.service.client, self.room.service.client, self.config)
        self.sections.addTab(self.explain, "How it works")
        self.sections.currentChanged.connect(self._section_changed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(round(1000 / self.config.timing.ui_hz))
        self.model_check_timer = QTimer(self)
        self.model_check_timer.setInterval(30000)
        self.model_check_timer.timeout.connect(self._check_model_availability)
        if self.model_enabled:
            self.model_check_timer.start()
            self._check_model_availability()
        self._refresh()

    def _section_changed(self, index: int) -> None:
        if index != 0:
            self.pause()
        if index != 1:
            self.room.pause()
        if index == 0:
            self._refresh()
        elif index == 1:
            self.room.refresh()
        else:
            self._refresh_explanation()
        self.statusBar().clearMessage()

    def _refresh_explanation(self) -> None:
        self.explain.refresh(self.engine, self.room.engine, self.room.interval.value())

    @staticmethod
    def _toolbar_divider() -> QFrame:
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        divider.setFixedHeight(24)
        return divider

    @staticmethod
    def _command_bar(layout: QHBoxLayout) -> QFrame:
        bar = QFrame()
        bar.setObjectName("commandBar")
        bar.setLayout(layout)
        return bar

    def _set_model_health(self, state: str, detail: str) -> None:
        self.model_health_indicator.setText(state)
        self.model_health_indicator.setProperty("health", state.lower())
        self.model_health_indicator.setToolTip(detail)
        self.model_health_indicator.style().unpolish(self.model_health_indicator)
        self.model_health_indicator.style().polish(self.model_health_indicator)
        if hasattr(self, "room"):
            self.room.set_model_health(state, detail)

    def _check_model_availability(self) -> None:
        if not self.model_enabled or self._model_check_pending:
            return
        self._model_check_pending = True
        self._set_model_health("CHECKING", "Checking the Ollama server and configured model.")
        worker = _ModelCheckWorker(self.service.client)
        worker.signals.completed.connect(self._model_check_finished)
        self._model_check_worker = worker
        self._model_check_pool.start(worker)

    def _model_check_finished(self, available: bool, detail: str) -> None:
        self._model_check_pending = False
        self._model_check_worker = None
        self._set_model_health("OK" if available else "NOK", detail)

    def _controls(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(250)
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(2, 0, 8, 0)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        fault_page = QWidget()
        fault_form = QFormLayout(fault_page)
        self.fault_type = QComboBox()
        for key, label in FAULT_NAMES.items():
            if key != "healthy":
                self.fault_type.addItem(label, key)
        self.severity = spin(0.7, 0.05, 1, 0.05, 2)
        self.delay = spin(3, 0, 3600, 1, 1, " s")
        self.duration = spin(5, 0.1, 3600, 1, 1, " s")
        self.ramp = spin(0, 0, 60, 0.5, 1, " s")
        self.persistent = QCheckBox("Persistent")
        self.persistent.setChecked(True)
        self.duration.setEnabled(False)
        self.persistent.toggled.connect(lambda value: self.duration.setEnabled(not value))
        for label, control in (("Fault", self.fault_type), ("Severity [0-1]", self.severity),
                               ("Schedule delay", self.delay), ("Duration", self.duration),
                               ("Ramp", self.ramp), ("", self.persistent)):
            fault_form.addRow(label, control)
        inject = QPushButton("Inject now")
        inject.setObjectName("fault")
        schedule = QPushButton("Schedule fault")
        clear = QPushButton("Clear faults / schedules")
        for button in (inject, schedule, clear):
            fault_form.addRow(button)
        inject.clicked.connect(lambda: self.inject(False))
        schedule.clicked.connect(lambda: self.inject(True))
        clear.clicked.connect(self.clear_faults)
        tabs.addTab(fault_page, "Faults")
        plant_page = QWidget()
        plant_form = QFormLayout(plant_page)
        self.parameters = {}
        entries = [("inertia", "J [kg m2]", 0.005, 0.2, 0.005, 3),
                   ("inductance", "L [H]", 0.01, 0.5, 0.01, 3),
                   ("resistance", "R [ohm]", 0.1, 3, 0.1, 2),
                   ("torque_constant", "Kt [N m/A]", 0.02, 0.5, 0.01, 3),
                   ("back_emf", "Ke [V s/rad]", 0.02, 0.5, 0.01, 3),
                   ("friction", "b [N m s/rad]", 0.0001, 0.04, 0.001, 4),
                   ("load_torque", "Load [N m]", 0.01, 3, 0.05, 2),
                   ("supply_voltage", "Supply [V]", 12, 96, 1, 1)]
        for key, label, low, high, step, decimals in entries:
            control = spin(getattr(self.config.plant, key), low, high, step, decimals)
            self.parameters[key] = control
            plant_form.addRow(label, control)
        self.kp = spin(self.config.controller.kp, 0, 3, 0.01, 3)
        self.ki = spin(self.config.controller.ki, 0, 10, 0.1, 3)
        plant_form.addRow("PI Kp [V s/rad]", self.kp)
        plant_form.addRow("PI Ki [V/rad]", self.ki)
        self.apply_gains = QPushButton("Apply gains")
        self.apply_gains.clicked.connect(self._apply_gains)
        plant_form.addRow(self.apply_gains)
        tabs.addTab(plant_page, "Plant")
        timing_page = QWidget()
        timing_form = QFormLayout(timing_page)
        self.rates = {}
        for key, caption, choices in (("physics_hz", "Physics Hz", (100, 200, 500, 1000)),
                                      ("control_hz", "Control Hz", (20, 50, 100)),
                                      ("feature_hz", "Features Hz", (20, 50, 100)),
                                      ("ui_hz", "UI Hz", (10, 20, 30))):
            control = QComboBox()
            for choice in choices:
                control.addItem(str(choice), choice)
            control.setCurrentIndex(control.findData(getattr(self.config.timing, key)))
            self.rates[key] = control
            timing_form.addRow(caption, control)
        self.feature_window = spin(self.config.timing.feature_window, 0.2, 2, 0.1, 1, " s")
        self.result_age = spin(self.config.timing.result_max_age, 1, 30, 1, 1, " s")
        self.score_floor = spin(self.config.min_diagnosis_score, 0.2, 0.95, 0.05, 2)
        self.persistence = spin(self.config.diagnosis_persistence, 0.1, 10, 0.5, 1, " s")
        self.seed = QSpinBox()
        self.seed.setRange(0, 1000000)
        self.seed.setValue(self.config.seed)
        for label, control in (("Feature window", self.feature_window), ("Max result age", self.result_age),
                               ("Acceptance score", self.score_floor), ("Persistence", self.persistence), ("Random seed", self.seed)):
            timing_form.addRow(label, control)
        tabs.addTab(timing_page, "Timing")
        scroll.setWidget(wrapper)
        return scroll

    def start(self) -> None:
        self.running = True
        self.last_tick = monotonic()
        self.follow.setChecked(True)

    def pause(self) -> None:
        self.running = False
        self.follow.setChecked(False)

    def _target_changed(self, value: float) -> None:
        self.engine.config.target_rpm = value
        self.engine.event("target", "target changed", target_rpm=value)

    def _interval_changed(self, value: float) -> None:
        self.engine.config.timing.qjev_interval = value
        self.engine.event("settings", "diagnostic interval", interval=value)

    def _apply_gains(self) -> None:
        if self.running:
            return
        self.engine.config.controller.kp = self.kp.value()
        self.engine.config.controller.ki = self.ki.value()
        self.engine.event("controller", "gains changed", kp=self.kp.value(), ki=self.ki.value())

    def reset(self, checked: bool = False, use_scenario_seed: bool = False) -> None:
        config = deepcopy(self.engine.config)
        for key, widget in self.parameters.items():
            setattr(config.plant, key, widget.value())
        for key, widget in self.rates.items():
            setattr(config.timing, key, widget.currentData())
        config.controller.kp, config.controller.ki = self.kp.value(), self.ki.value()
        config.timing.feature_window, config.timing.result_max_age = self.feature_window.value(), self.result_age.value()
        config.min_diagnosis_score, config.diagnosis_persistence = self.score_floor.value(), self.persistence.value()
        config.seed = SCENARIOS[self.scenario.currentData()].seed if use_scenario_seed else self.seed.value()
        config.timing.plot_capacity = config.timing.feature_hz * 120
        try:
            replacement = Simulation(config, self.scenario.currentData())
        except ValueError as error:
            QMessageBox.warning(self, "Invalid configuration", str(error))
            return
        self.running = False
        self.generation += 1
        self.service.invalidate()
        self.engine.close()
        self.engine = replacement
        self.seed.setValue(config.seed)
        self.timer.setInterval(round(1000 / config.timing.ui_hz))
        self.last_submit_wall = self.last_submit_sim = float("-inf")
        self.retry_after = 0
        self.normal_budget = 2
        self.previous_detector_state = "normal"
        self.event_count = 0
        self.plots.reset()
        self.log.clear()
        self.follow.setChecked(True)
        self._refresh()

    def inject(self, scheduled: bool) -> None:
        self.engine.inject(Fault(self.fault_type.currentData(), self.engine.time + (self.delay.value() if scheduled else 0),
                                 self.severity.value(), None if self.persistent.isChecked() else self.duration.value(),
                                 self.ramp.value()))
        self._refresh()

    def clear_faults(self) -> None:
        self.engine.clear_faults()
        self._refresh()

    def _submit(self, force: bool = False) -> None:
        now, s = monotonic(), self.engine
        if not self.model_enabled or self.service.busy or not s.last_row or now < self.retry_after:
            return
        interval = s.config.timing.qjev_interval
        if s.detector.state == "normal" and not force and self.normal_budget <= 0:
            return
        if not force and (s.time < 3 or now - self.last_submit_wall < interval or s.time - self.last_submit_sim < interval):
            return
        request = s.make_request(self.generation)
        if self.service.submit(request):
            self.last_submit_wall, self.last_submit_sim = now, s.time
            if s.detector.state == "normal":
                self.normal_budget -= 1

    def tick(self) -> None:
        now = monotonic()
        elapsed = min(0.1, now - self.last_tick)
        self.last_tick = now
        if self.running:
            try:
                self.engine.advance(elapsed * self.speed.value())
            except (ValueError, FloatingPointError):
                self.pause()
        reply = self.service.poll()
        if reply is not None and reply.request.generation == self.generation:
            if reply.error:
                self._check_model_availability()
                self.retry_after = now + 5
                self.engine.last_latency = reply.latency
                self.engine.metrics.failures += 1
                if reply.request.anomaly == "normal":
                    self.normal_budget = min(2, self.normal_budget + 1)
                self.engine.history.diagnostic({"sample_time": reply.request.time, "received_time": self.engine.time,
                                                "error": reply.error, "latency": reply.latency, "context": reply.request.context})
                self.engine.event("model error", reply.error)
            elif reply.decision is not None:
                self.engine.accept(reply.request, reply.decision)
                self._set_model_health("OK", "The configured model returned a diagnostic result.")
        if self.engine.detector.state == "normal" and self.previous_detector_state != "normal":
            self.normal_budget = 2
        self.previous_detector_state = self.engine.detector.state
        if self.running:
            self._submit()
        if self.sections.currentIndex() == 0:
            self._refresh()
        elif self.sections.currentIndex() == 2:
            self._refresh_explanation()

    def _refresh(self) -> None:
        s, row = self.engine, self.engine.last_row
        self.start_button.setEnabled(not self.running)
        self.pause_button.setEnabled(self.running)
        self.apply_gains.setEnabled(not self.running)
        self.diagnose_button.setEnabled(self.model_enabled and not self.service.busy and bool(row))
        self.readouts["time"].setText(f"{s.time:7.2f} s")
        self.readouts["mode"].setText(s.mode)
        self.readouts["truth"].setText(FAULT_NAMES[s.truth])
        if row:
            self.readouts["speed"].setText(f"{row['measured_speed_rpm']:.0f} / {row['expected_speed_rpm']:.0f} rpm")
            self.readouts["current"].setText(f"{row['measured_current_a']:.2f} A / {row['command_v']:.1f} V")
        else:
            self.readouts["speed"].setText("0 / 0 rpm")
            self.readouts["current"].setText("0 A / 0 V")
        self.plots.update_signals(s, self.window.value(), self.follow.isChecked())
        self.diagnostics.refresh(s)
        for event in s.events[self.event_count:]:
            self.log.appendPlainText(f"{event['time']:7.2f}  {event['kind']}: {event['label']}")
        self.event_count = len(s.events)

    def export_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export full simulation history", "motor_run.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            outputs = self.engine.export(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Export failed", str(error))
            return
        self.statusBar().showMessage("Exported: " + ", ".join(p.name for p in outputs), 10000)

    def closeEvent(self, event) -> None:
        self.room.shutdown()
        self.timer.stop()
        self.model_check_timer.stop()
        self.running = False
        self.service.invalidate()
        self.engine.close()
        event.accept()
