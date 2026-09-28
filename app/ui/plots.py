from collections import deque
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.autoscale import YAutoRange, plot_at

COLORS = {"cyan": "#2878b5", "blue": "#687b91", "amber": "#b66a08", "green": "#2d7c4b", "muted": "#747474"}
# y fitting per plot: (minimum visible span, values kept in view); the model score keeps a fixed 0-1 axis
SCALING = {"speed": (50, ()), "current": (0.5, ()), "voltage": (2, ()),
           "speed_residual": (30, (0,)), "current_residual": (0.2, (0,)), "anomaly": (1.2, (0, 1.2))}


class SignalPlots(QWidget):
    inspected = Signal(str)

    def __init__(self):
        super().__init__()
        pg.setConfigOptions(antialias=False, background="#ffffff", foreground="#454545")
        self.canvas = pg.GraphicsLayoutWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("Plot view"))
        self.view_selector = QComboBox()
        self.view_selector.setMinimumWidth(200)
        self.view_selector.setToolTip("Choose a plot to fill this area, or select All plots to restore the dashboard.")
        self.view_selector.addItem("All plots", None)
        view_row.addWidget(self.view_selector)
        view_row.addStretch()
        hint = QLabel("Y axes fit the visible window. Zoom a plot to hold its scale; double-click to fit again.")
        hint.setObjectName("muted")
        view_row.addWidget(hint)
        layout.addLayout(view_row)
        layout.addWidget(self.canvas)
        self.plots, self.curves, self.scalers = {}, {}, {}
        self.plot_positions = {}
        self.expanded_plot = None
        specifications = [
            ("speed", "01  SPEED RESPONSE", "Speed", "rpm", 0, 0, 2,
             [("target_rpm", "Target", "muted"), ("measured_speed_rpm", "Encoder", "cyan"), ("expected_speed_rpm", "Nominal predictor", "amber"), ("true_speed_rpm", "Truth (evaluation)", "green")]),
            ("current", "02  ARMATURE CURRENT", "Current", "A", 1, 0, 1,
             [("measured_current_a", "Measured", "cyan"), ("expected_current_a", "Predicted", "amber")]),
            ("voltage", "03  ACTUATOR", "Voltage", "V", 1, 1, 1,
             [("command_v", "Command", "blue"), ("applied_v", "Applied (truth)", "green")]),
            ("speed_residual", "04  ENCODER RESIDUAL", "Residual", "rpm", 2, 0, 1,
             [("speed_residual_rpm", "Measured - predicted", "cyan")]),
            ("current_residual", "05  CURRENT RESIDUAL", "Residual", "A", 2, 1, 1,
             [("current_residual_a", "Measured - predicted", "amber")]),
            ("anomaly", "06  DETERMINISTIC DETECTOR", "Score", "", 3, 0, 1,
             [("anomaly_score", "Residual threshold score", "amber")]),
            ("diagnosis", "07  MODEL SCORE HISTORY", "Score", "", 3, 1, 1,
             [("model_top_score", "Latest model top score", "muted"), ("diagnosis_score", "Accepted EMA score", "green")]),
        ]
        for key, title, label, units, row, col, span, lines in specifications:
            plot = self.canvas.addPlot(row=row, col=col, colspan=span, title=title)
            self.plot_positions[key] = (row, col, 1, span)
            self.view_selector.addItem(title.split("  ", 1)[1].title(), key)
            plot.setLabel("left", label, units=units)
            plot.setLabel("bottom", "Simulation time", units="s")
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.addLegend(offset=(8, 4), labelTextSize="9pt",
                           brush=pg.mkBrush(255, 255, 255, 235), pen=pg.mkPen("#bdbdbd"))
            plot.setMenuEnabled(False)
            plot.setMouseEnabled(x=True, y=True)
            if key != "speed":
                plot.setXLink(self.plots["speed"])
            self.plots[key] = plot
            if key in SCALING:
                min_span, include = SCALING[key]
                self.scalers[key] = YAutoRange(plot, [field for field, _, _ in lines], include, min_span)
            else:
                plot.hideButtons()
            for field, name, color in lines:
                curve = plot.plot(name=name, pen=pg.mkPen(COLORS[color], width=1.5))
                curve.setClipToView(True)
                curve.setDownsampling(auto=True, method="peak")
                self.curves[field] = curve
        self.plots["anomaly"].addItem(pg.InfiniteLine(pos=1, angle=0, pen=pg.mkPen("#bd4a3b", width=1)))
        self.plots["diagnosis"].setYRange(0, 1, padding=0.02)
        self.markers: deque[tuple] = deque()
        self.event_count = 0
        self.rows = []
        self.canvas.scene().sigMouseMoved.connect(self._inspect)
        self.canvas.scene().sigMouseClicked.connect(self._double_clicked)
        self.view_selector.currentIndexChanged.connect(self._change_plot_view)

    def _change_plot_view(self, index: int) -> None:
        selected = self.view_selector.itemData(index)
        grid = self.canvas.ci
        if selected is None:
            if self.expanded_plot is None:
                return
            grid.removeItem(self.plots[self.expanded_plot])
            for key, plot in self.plots.items():
                row, col, rowspan, colspan = self.plot_positions[key]
                grid.addItem(plot, row=row, col=col, rowspan=rowspan, colspan=colspan)
            self.expanded_plot = None
            return

        if self.expanded_plot == selected:
            return
        if self.expanded_plot is not None:
            grid.removeItem(self.plots[self.expanded_plot])
        else:
            for plot in self.plots.values():
                grid.removeItem(plot)
        grid.addItem(self.plots[selected], row=0, col=0)
        self.expanded_plot = selected

    def restore_scaling(self) -> None:
        for scaler in self.scalers.values():
            scaler.restore()

    def _double_clicked(self, event) -> None:
        if not event.double():
            return
        plot = plot_at(self.plots.values(), event.scenePos())
        scaler = next((s for s in self.scalers.values() if s.plot is plot), None)
        if scaler is not None:
            scaler.restore()
            event.accept()

    def reset(self) -> None:
        for plot, marker in self.markers:
            plot.removeItem(marker)
        self.markers.clear()
        for curve in self.curves.values():
            curve.setData([], [])
        self.event_count = 0
        self.rows = []
        self.restore_scaling()

    def update_signals(self, simulation, window: float, follow: bool) -> None:
        self.rows = list(simulation.live)
        if not self.rows:
            return
        times = np.array([r["time"] for r in self.rows])
        columns = {key: np.array([r[key] for r in self.rows], dtype=float) for key in self.curves}
        for key, curve in self.curves.items():
            curve.setData(times, columns[key])
        if follow:
            self.plots["speed"].setXRange(max(0, simulation.time - window), max(window, simulation.time), padding=0)
        for scaler in self.scalers.values():
            scaler.fit(times, columns)
        for event in simulation.events[self.event_count:]:
            if event["kind"] not in ("fault", "clear", "diagnosis"):
                continue
            color = COLORS["green"] if event["kind"] == "diagnosis" else COLORS["amber"]
            for key in ("speed", "speed_residual", "diagnosis"):
                marker = pg.InfiniteLine(pos=event["time"], angle=90,
                                         pen=pg.mkPen(color, width=1),
                                         label=event["label"] if key == "speed" else None,
                                         labelOpts={"position": 0.9, "color": color, "rotateAxis": (1, 0)})
                self.plots[key].addItem(marker)
                self.markers.append((self.plots[key], marker))
        self.event_count = len(simulation.events)
        while len(self.markers) > 180:
            plot, marker = self.markers.popleft()
            plot.removeItem(marker)

    def _inspect(self, position) -> None:
        if not self.rows:
            return
        for plot in self.plots.values():
            if plot.sceneBoundingRect().contains(position):
                point = plot.vb.mapSceneToView(position)
                times = np.array([r["time"] for r in self.rows])
                row = self.rows[int(np.argmin(abs(times - point.x())))]
                self.inspected.emit(f"Inspect t={row['time']:.2f} s | encoder {row['measured_speed_rpm']:.1f} rpm | "
                                    f"current {row['measured_current_a']:.2f} A | residual {row['speed_residual_rpm']:+.1f} rpm | "
                                    f"{row['anomaly']} | diagnosis {row['diagnosis']}")
                break
