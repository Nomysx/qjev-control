from time import monotonic

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from app.config import Configuration
from app.diagnostics.qjev_client import QJevOllamaClient
from app.diagnostics.service import DiagnosticRequest, DiagnosticService
from app.simulation.room import HEATER_OPTIONS, HEATER_QUESTION, RoomSettings, RoomSimulation
from app.ui.autoscale import YAutoRange, plot_at
from app.ui.axes import bracket_axes


def number(value, low, high, suffix="", step=1, decimals=1):
    widget = QDoubleSpinBox()
    widget.setRange(low, high)
    widget.setDecimals(decimals)
    widget.setSingleStep(step)
    widget.setSuffix(suffix)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


class RoomPanel(QWidget):
    model_health = Signal(str, str)

    def __init__(self, config: Configuration, model_enabled: bool):
        super().__init__()
        self.model_enabled = model_enabled
        self.service = DiagnosticService(
            QJevOllamaClient(config.ollama_url, config.model, config.request_timeout, config.readout),
            HEATER_QUESTION, HEATER_OPTIONS)
        self.engine = RoomSimulation(RoomSettings())
        self.running = False
        self.pending = False
        self.generation = 0
        self.next_decision = 0.0
        self.last_tick = monotonic()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 6)

        bar = QFrame()
        bar.setObjectName("commandBar")
        commands = QHBoxLayout(bar)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primary")
        self.pause_button = QPushButton("Pause")
        reset = QPushButton("Reset")
        self.target = number(22, 5, 35, " °C", 0.5)
        self.speed = number(60, 1, 600, " x", 10, 0)
        for widget in (self.start_button, self.pause_button, reset, QLabel("Desired temperature"),
                       self.target, QLabel("Speed"), self.speed):
            commands.addWidget(widget)
        commands.addStretch()
        commands.addWidget(QLabel(f"Model: {config.model}"))
        self.health = QLabel("CHECKING" if model_enabled else "OFF")
        self.health.setObjectName("modelHealth")
        commands.addWidget(self.health)
        root.addWidget(bar)

        readouts = QHBoxLayout()
        self.readouts = {}
        for key, title in (("time", "TIME"), ("room", "ROOM TEMPERATURE"),
                           ("heater", "HEATER"), ("state", "CONTROL")):
            box = QGroupBox(title)
            layout = QVBoxLayout(box)
            label = QLabel()
            label.setObjectName("readout")
            layout.addWidget(label)
            readouts.addWidget(box)
            self.readouts[key] = label
        root.addLayout(readouts)

        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)
        controls = QWidget()
        controls.setMinimumWidth(265)
        sidebar = QVBoxLayout(controls)
        sidebar.setContentsMargins(0, 0, 8, 0)
        settings = QGroupBox("ROOM")
        form = QFormLayout(settings)
        self.initial = number(18, -10, 40, " °C", 0.5)
        self.initial.setToolTip("Starting room temperature; applied when Reset is clicked.")
        self.outside = number(5, -30, 40, " °C", 0.5)
        self.power = number(3, 0.5, 10, " kW", 0.5)
        self.band = number(0.3, 0.1, 3, " °C", 0.1)
        self.band.setToolTip("Switch ON below desired minus band; OFF above desired plus band.")
        self.interval = number(30, 5, 120, " s", 5, 0)
        self.interval.setToolTip("Simulated time between model decisions. Time waits during inference.")
        for label, widget in (("Initial (on reset)", self.initial), ("Outside", self.outside),
                              ("Heater power", self.power), ("Switching band ±", self.band),
                              ("Control interval", self.interval)):
            form.addRow(label, widget)
        sidebar.addWidget(settings)

        faults = QGroupBox("DISTURBANCE")
        fault_form = QFormLayout(faults)
        self.fault = QComboBox()
        for label, kind in (("Temperature spike", "spike"), ("Heat step (Heaviside)", "step"),
                             ("Heat pulse", "pulse"), ("Open window", "window")):
            self.fault.addItem(label, kind)
        self.amount = number(-3, -15, 15, " °C", 0.5)
        self.amount.setToolTip("Positive adds heat; negative cools the room.")
        self.duration = number(5, 0.5, 60, " min", 0.5)
        self.amount_label = QLabel("Temperature change")
        fault_form.addRow("Type", self.fault)
        fault_form.addRow(self.amount_label, self.amount)
        fault_form.addRow("Pulse duration", self.duration)
        inject = QPushButton("Inject now")
        inject.setObjectName("fault")
        clear = QPushButton("Clear / close window")
        fault_form.addRow(inject)
        fault_form.addRow(clear)
        self.fault_status = QLabel("None")
        self.fault_status.setWordWrap(True)
        fault_form.addRow("Active", self.fault_status)
        sidebar.addWidget(faults)
        sidebar.addWidget(QLabel("EVENT LOG"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        sidebar.addWidget(self.log, 1)
        split.addWidget(controls)

        charts = QWidget()
        chart_layout = QVBoxLayout(charts)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("Plot view"))
        self.view = QComboBox()
        self.view.addItems(["All plots", "Temperature", "Heater ON / OFF", "Heat flow"])
        view_row.addWidget(self.view)
        view_row.addStretch()
        hint = QLabel("Double-click a plot to refit its Y axis.")
        hint.setObjectName("muted")
        view_row.addWidget(hint)
        chart_layout.addLayout(view_row)
        self.canvas = pg.GraphicsLayoutWidget()
        self.canvas.setBackground("#ffffff")
        chart_layout.addWidget(self.canvas, 1)
        self.plots = []
        self.curves = {}
        for index, (title, label, units) in enumerate((
                ("01 ROOM TEMPERATURE", "Temperature", "°C"),
                ("02 HEATER ON / OFF", "Heater", ""),
                ("03 HEAT FLOW", "Power", "W"))):
            plot = self.canvas.addPlot(row=index, col=0, title=title, axisItems=bracket_axes())
            plot.setLabel("left", label, units=units)
            plot.setLabel("bottom", "Simulation time", units="min")
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.addLegend(offset=(10, 10))
            self.plots.append(plot)
        self.plots[1].setYRange(-0.1, 1.1, padding=0)
        self.plots[1].getAxis("left").setTicks([[(0, "OFF"), (1, "ON")]])
        for plot_index, key, label, color in (
                (0, "temperature", "Room", "#176bb0"), (0, "target", "Desired", "#555555"),
                (0, "outside", "Outside", "#a97835"), (0, "lower", "Lower threshold", "#909090"),
                (0, "upper", "Upper threshold", "#909090"),
                (1, "heater", "Model command", "#26743c"),
                (2, "power", "Heater", "#26743c"), (2, "loss", "Heat loss", "#b16016"),
                (2, "disturbance", "Disturbance", "#8b438c")):
            pen = pg.mkPen(color, width=1.5 if key == "temperature" else 1)
            if key in ("target", "lower", "upper"):
                pen.setStyle(Qt.PenStyle.DashLine)
            self.curves[key] = self.plots[plot_index].plot(
                pen=pen, name=label,
                **({"stepMode": "left"} if key in ("heater", "power", "disturbance") else {}))
        # the outside temperature is excluded so the switching band stays readable; the title reports it
        self.scalers = [YAutoRange(self.plots[0], ("temperature", "target", "lower", "upper"), min_span=1.0),
                        YAutoRange(self.plots[2], ("power", "loss", "disturbance"), include=(0,), min_span=500)]
        self.plots[1].hideButtons()
        self.temperature_title = ""
        self.canvas.scene().sigMouseClicked.connect(self._double_clicked)
        split.addWidget(charts)
        split.setSizes([295, 1100])
        split.setStretchFactor(1, 1)

        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        reset.clicked.connect(self.reset)
        self.fault.currentIndexChanged.connect(self._fault_changed)
        inject.clicked.connect(self.inject)
        clear.clicked.connect(self.clear)
        self.view.currentIndexChanged.connect(self._plot_view)
        for control in (self.target, self.outside, self.power, self.band, self.interval):
            control.valueChanged.connect(self._settings_changed)
        self._fault_changed()
        self.state = "Ready" if model_enabled else "Model disabled at launch"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.refresh()

    def set_model_health(self, state: str, detail: str) -> None:
        self.health.setText(state)
        self.health.setProperty("health", state.lower())
        self.health.setToolTip(detail)
        self.health.style().unpolish(self.health)
        self.health.style().polish(self.health)

    def _event(self, text: str) -> None:
        self.log.appendPlainText(f"{self.engine.time / 60:7.2f} min  {text}")

    def _invalidate(self) -> None:
        self.generation += 1
        self.service.invalidate()
        self.pending = False
        self.next_decision = self.engine.time

    def _settings_changed(self) -> None:
        settings = self.engine.settings
        settings.target = self.target.value()
        settings.outside = self.outside.value()
        settings.heater_watts = self.power.value() * 1000
        settings.deadband = self.band.value()
        self.engine.record()
        self._invalidate()
        self.refresh()

    def start(self) -> None:
        if not self.model_enabled:
            return
        self.running = True
        self.next_decision = self.engine.time
        self.last_tick = monotonic()
        self.state = "Starting"
        self._event("Started")
        self.refresh()

    def pause(self) -> None:
        was_running = self.running
        self.running = False
        self._invalidate()
        if was_running:
            self.state = "Paused"
            self._event("Paused")
        self.refresh()

    def reset(self) -> None:
        self.pause()
        self.engine = RoomSimulation(RoomSettings(
            initial=self.initial.value(), target=self.target.value(), outside=self.outside.value(),
            heater_watts=self.power.value() * 1000, deadband=self.band.value()))
        self.next_decision = 0.0
        self.state = "Ready" if self.model_enabled else "Model disabled at launch"
        self.log.clear()
        for scaler in self.scalers:
            scaler.restore()
        self._event("Reset")
        self.refresh()

    def _fault_changed(self) -> None:
        kind = self.fault.currentData()
        self.amount.setEnabled(kind != "window")
        self.duration.setEnabled(kind == "pulse")
        self.amount_label.setText("Temperature change" if kind == "spike" else "Extra heat (+/-)")
        self.amount.setRange(-15 if kind == "spike" else -5, 15 if kind == "spike" else 5)
        self.amount.setSuffix(" °C" if kind == "spike" else " kW")
        self.amount.setValue(-3 if kind == "spike" else -1)

    def inject(self) -> None:
        kind = self.fault.currentData()
        amount = self.amount.value() * (1000 if kind in ("step", "pulse") else 1)
        self.engine.inject(kind, amount, self.duration.value() * 60)
        self._invalidate()
        detail = "" if kind == "window" else f" {self.amount.text()}"
        if kind == "pulse":
            detail += f" for {self.duration.text()}"
        self._event(self.fault.currentText() + detail)
        self.refresh()

    def clear(self) -> None:
        self.engine.clear_disturbances()
        self._invalidate()
        self._event("Disturbances cleared; window closed")
        self.refresh()

    def _double_clicked(self, event) -> None:
        if not event.double():
            return
        plot = plot_at(self.plots, event.scenePos())
        for scaler in self.scalers:
            if scaler.plot is plot:
                scaler.restore()
                event.accept()

    def _plot_view(self, index: int) -> None:
        for plot in self.plots:
            if plot in self.canvas.ci.items:
                self.canvas.ci.removeItem(plot)
        for row, plot in enumerate(self.plots if index == 0 else [self.plots[index - 1]]):
            self.canvas.addItem(plot, row=row, col=0)

    def tick(self) -> None:
        now = monotonic()
        elapsed = min(0.2, now - self.last_tick)
        self.last_tick = now
        reply = self.service.poll()
        if reply is not None and reply.request.generation == self.generation and self.running:
            self.pending = False
            if reply.error or reply.decision is None:
                self.running = False
                self.engine.command("off")
                self.state = "Model error - paused"
                self._event(reply.error or "No model decision")
                self.model_health.emit("NOK", reply.error or "No model decision")
            else:
                self.engine.command(reply.decision.selected)
                self.next_decision = self.engine.time + self.interval.value()
                self.state = "Running"
                self.model_health.emit("OK", "Model returned a heater command.")
                self._event(f"Heater {reply.decision.selected.upper()} | "
                            f"ON score {reply.decision.scores['on']:.1%} | {reply.latency:.2f} s")
        if self.running and not self.pending:
            remaining = self.next_decision - self.engine.time
            if remaining > 1e-9:
                self.engine.advance(min(elapsed * self.speed.value(), remaining))
            if self.engine.time >= self.next_decision - 1e-9:
                request = DiagnosticRequest(self.generation, self.engine.time, self.engine.context(), "", "")
                self.pending = self.service.submit(request)
                self.state = "Model deciding…" if self.pending else "Waiting for model…"
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        s = self.engine
        self.start_button.setEnabled(not self.running and self.model_enabled)
        self.pause_button.setEnabled(self.running)
        self.readouts["time"].setText(f"{s.time / 60:.2f} min")
        self.readouts["room"].setText(f"{s.temperature:.2f} °C")
        self.readouts["heater"].setText("ON" if s.heater else "OFF")
        self.readouts["state"].setText(self.state)
        active = []
        if s.step_watts:
            active.append(f"Step {s.step_watts / 1000:+.1f} kW")
        if s.time < s.pulse_end:
            active.append(f"Pulse ({(s.pulse_end - s.time) / 60:.1f} min left)")
        if s.window_open:
            active.append("Window open")
        self.fault_status.setText(", ".join(active) or "None")
        rows = list(s.rows)
        times = np.array([row["time"] / 60 for row in rows])
        columns = {key: np.array([row[key] for row in rows], dtype=float) for key in self.curves}
        for key, curve in self.curves.items():
            curve.setData(times, columns[key])
        for plot in self.plots:
            plot.setXRange(max(0, s.time / 60 - 60), max(1, s.time / 60), padding=0.02)
        for scaler in self.scalers:
            scaler.fit(times, columns)
        low, high = self.plots[0].vb.viewRange()[1]
        title = "01 ROOM TEMPERATURE" + ("" if low <= s.settings.outside <= high else
                                         f"   (outside {s.settings.outside:.1f} °C, off scale)")
        if title != self.temperature_title:
            self.plots[0].setTitle(title)
            self.temperature_title = title

    def shutdown(self) -> None:
        self.timer.stop()
        self.running = False
        self.generation += 1
        self.service.invalidate()
