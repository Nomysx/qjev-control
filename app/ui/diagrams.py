"""Signal-flow block diagrams drawn from plain data and scaled to the widget.

Blocks and links use logical coordinates. A link point is an (x, y) tuple or a "block.side"
anchor with side n/e/s/w. Link labels can carry a live value shown under the label.
"""

from dataclasses import dataclass
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QAbstractTextDocumentLayout, QColor, QFont, QPainter, QPalette, QPen, QPolygonF,
                           QTextDocument, QTextOption)
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.config import RPM, Configuration
from app.simulation.room import RoomSettings

# fill and border per block kind; model and fault blocks reuse the primary and fault button colors
KINDS = {"process": ("#fafafa", "#333333"), "sensor": ("#eef2f5", "#333333"), "model": ("#e4edf6", "#647f9a"),
         "fault": ("#fff4f1", "#b77b70"), "sum": ("#ffffff", "#333333"), "text": (None, None)}
LINE, FAULT_LINE, VALUE = "#333333", "#b77b70", "#1c4265"


@dataclass
class Block:
    key: str
    text: str
    x: float
    y: float
    w: float
    h: float
    kind: str = "process"


@dataclass
class Link:
    points: tuple
    label: str = ""
    at: tuple[float, float] = (0.0, 0.0)
    anchor: str = "above"
    value: str | None = None
    sign: str = ""
    dashed: bool = False
    junction: bool = False


def _document(html: str, pixels: int, width: float | None = None) -> QTextDocument:
    document = QTextDocument()
    font = QFont("Segoe UI")
    font.setPixelSize(pixels)
    document.setDefaultFont(font)
    document.setDocumentMargin(1)
    document.setDefaultTextOption(QTextOption(Qt.AlignmentFlag.AlignHCenter))
    document.setHtml(html)
    document.setTextWidth(width if width else document.idealWidth())
    return document


def _draw_text(painter: QPainter, document: QTextDocument) -> None:
    # an explicit text color: the system palette is light text on a dark Windows theme
    context = QAbstractTextDocumentLayout.PaintContext()
    context.palette.setColor(QPalette.ColorRole.Text, QColor(LINE))
    document.documentLayout().draw(painter, context)


class BlockDiagram(QWidget):
    def __init__(self, size: tuple[float, float], blocks: list[Block], links: list[Link]):
        super().__init__()
        self.logical_width, self.logical_height = size
        self.values: dict[str, str] = {}
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_diagram(blocks, links)

    def set_diagram(self, blocks: list[Block], links: list[Link]) -> None:
        self.blocks = {block.key: block for block in blocks}
        self.links = links
        self.block_text = {block.key: _document(block.text, 13, block.w - 8) for block in blocks}
        self._layout_labels()

    def set_values(self, values: dict[str, str]) -> None:
        if values != self.values:
            self.values = values
            self._layout_labels()

    def _layout_labels(self) -> None:
        self.label_text = []
        for link in self.links:
            text = link.label
            if link.value and self.values.get(link.value):
                text += f"<br><span style='color:{VALUE}; font-family:Consolas'>{self.values[link.value]}</span>"
            self.label_text.append(_document(text, 12) if text else None)
        self.update()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return round(width * self.logical_height / self.logical_width)

    def sizeHint(self) -> QSize:
        return QSize(round(self.logical_width * 0.85), round(self.logical_height * 0.85))

    def minimumSizeHint(self) -> QSize:
        return QSize(round(self.logical_width * 0.6), round(self.logical_height * 0.6))

    def _point(self, point) -> QPointF:
        if not isinstance(point, str):
            return QPointF(*point)
        key, side = point.split(".")
        b = self.blocks[key]
        return QPointF(*{"n": (b.x + b.w / 2, b.y), "s": (b.x + b.w / 2, b.y + b.h),
                         "e": (b.x + b.w, b.y + b.h / 2), "w": (b.x, b.y + b.h / 2)}[side])

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        scale = min(self.width() / self.logical_width, self.height() / self.logical_height)
        painter.translate((self.width() - self.logical_width * scale) / 2,
                          (self.height() - self.logical_height * scale) / 2)
        painter.scale(scale, scale)
        for link, label in zip(self.links, self.label_text):
            self._draw_link(painter, link, label)
        for block in self.blocks.values():
            self._draw_block(painter, block)
        painter.end()

    def _draw_link(self, painter: QPainter, link: Link, label: QTextDocument | None) -> None:
        points = [self._point(point) for point in link.points]
        color = QColor(FAULT_LINE if link.dashed else LINE)
        pen = QPen(color, 1.6 if link.dashed else 2.0)
        if link.dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))
        end, before = points[-1], points[-2]
        dx, dy = end.x() - before.x(), end.y() - before.y()
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([end, QPointF(end.x() - 11 * ux - 5 * uy, end.y() - 11 * uy + 5 * ux),
                                       QPointF(end.x() - 11 * ux + 5 * uy, end.y() - 11 * uy - 5 * ux)]))
        if link.junction:
            painter.drawEllipse(points[0], 4, 4)
        if link.sign:
            painter.setPen(QPen(color))
            font = QFont("Segoe UI")
            font.setPixelSize(16)
            font.setBold(True)
            painter.setFont(font)
            # the sign sits beside the arrow tip, clockwise of it, away from labels placed above or to the right
            x, y = end.x() - 20 * ux - 12 * uy, end.y() - 20 * uy + 12 * ux
            painter.drawText(QRectF(x - 9, y - 10, 18, 20), Qt.AlignmentFlag.AlignCenter, link.sign)
        if label is not None:
            w, h = label.size().width(), label.size().height()
            ox, oy = {"above": (-w / 2, -h), "below": (-w / 2, 0), "left": (-w, -h / 2), "right": (0, -h / 2)}[link.anchor]
            painter.save()
            painter.translate(link.at[0] + ox, link.at[1] + oy)
            _draw_text(painter, label)
            painter.restore()

    def _draw_block(self, painter: QPainter, block: Block) -> None:
        fill, border = KINDS[block.kind]
        rect = QRectF(block.x, block.y, block.w, block.h)
        if fill:
            painter.setPen(QPen(QColor(border), 2.0))
            painter.setBrush(QColor(fill))
            painter.drawEllipse(rect) if block.kind == "sum" else painter.drawRect(rect)
        text = self.block_text[block.key]
        painter.save()
        painter.translate(block.x + 4, block.y + (block.h - text.size().height()) / 2)
        _draw_text(painter, text)
        painter.restore()


def motor_loop(config: Configuration) -> tuple[tuple[float, float], list[Block], list[Link]]:
    """Speed control loop with fault entry points, in the style of a manipulator control diagram."""
    p, g = config.plant, config.controller
    blocks = [
        Block("ramp", f"<b>Reference ramp</b><br>rate ≤ {g.reference_ramp_rpm_s:.0f} rpm/s", 90, 120, 120, 70),
        Block("sum", "<b>Σ</b>", 249, 139, 32, 32, "sum"),
        Block("pi", f"<b>PI controller</b><br>+ feedforward<br>K<sub>p</sub> = {g.kp:g}, K<sub>i</sub> = {g.ki:g}",
              330, 115, 150, 80),
        Block("limit", f"<b>Supply limit</b><br>±{p.supply_voltage:g} V", 540, 120, 120, 70),
        Block("actuator", "<b>Actuator</b><br>power amplifier", 730, 120, 130, 70),
        Block("plant", f"<b>DC motor + load</b><br>states ω, i<br>RK4 at {config.timing.physics_hz} Hz",
              930, 110, 170, 90),
        Block("sensors", f"<b>Sensors</b> ({config.timing.control_hz} Hz)<br>encoder ω<sub>m</sub>, current i<sub>m</sub>"
                         "<br>+ Gaussian noise", 750, 300, 190, 70, "sensor"),
        Block("faults", "<b>Fault injector</b>", 730, 10, 370, 42, "fault"),
    ]
    links = [
        Link(((0, 155), "ramp.w"), "target <i>n</i>*", (45, 150), value="target"),
        Link(("ramp.e", "sum.w"), "ω<sub>ref</sub>", (229, 150), sign="+"),
        Link(("sum.e", "pi.w"), "error <i>e</i>", (305, 150)),
        Link(("pi.e", "limit.w"), "u<sub>raw</sub>", (510, 150)),
        Link(("limit.e", "actuator.w"), "u<sub>cmd</sub>", (695, 150), value="command"),
        Link(("actuator.e", "plant.w"), "u<sub>a</sub>", (895, 150), value="applied"),
        Link(("plant.e", (1170, 155), (1170, 320), (940, 320)), "ω, i<br>(true)", (1135, 150), value="true_speed"),
        Link(("sensors.w", (265, 335), "sum.s"), "measured speed ω<sub>m</sub>", (480, 330), value="measured_speed",
             sign="-"),
        Link(((795, 52), "actuator.n"), "loss / stuck", (802, 86), "right", dashed=True),
        Link(((1015, 52), "plant.n"), "load, friction,<br>resistance", (1022, 81), "right", dashed=True),
        Link(("faults.e", (1190, 31), (1190, 350), (940, 350)), "bias, noise, corruption", (1065, 354), "below",
             dashed=True),
        Link(((700, 155), (700, 430)), "u<sub>cmd</sub> to predictor", (694, 412), "left", junction=True),
        Link(("sensors.s", (845, 430)), "ω<sub>m</sub>, i<sub>m</sub> to residuals", (851, 412), "right"),
    ]
    return (1200, 440), blocks, links


def diagnostic_chain(config: Configuration) -> tuple[tuple[float, float], list[Block], list[Link]]:
    """Residual generation, detection and model-based isolation running beside the control loop."""
    blocks = [
        Block("predictor", "<b>Nominal predictor</b><br>nominal motor model<br>no correction (K = 0)", 80, 35, 210, 120),
        Block("sum", "<b>Σ</b>", 334, 79, 32, 32, "sum"),
        Block("features", f"<b>Feature extractor</b><br>{config.timing.feature_window:g} s window, "
                          f"{config.timing.feature_hz} Hz<br>mean, RMS, std, trend,<br>energy balances", 440, 45, 180, 100),
        Block("detector", "<b>Anomaly detector</b><br>score S from residual<br>statistics; alarm<br>when S ≥ 1",
              680, 45, 180, 100),
        Block("mode", "<b>Supervisory mode</b><br>advisory only", 930, 45, 180, 100),
        Block("context", "<b>Context builder</b><br>features → plain<br>sentences<br>(no ground truth)",
              440, 225, 180, 90),
        Block("model", f"<b>QJev language model</b><br>{config.model}<br>chooses 1 of 9<br>fault hypotheses",
              680, 215, 180, 110, "model"),
        Block("filter", f"<b>Diagnosis filter</b><br>EMA, margin, ≥ {config.min_diagnosis_score:g} score,<br>"
                        f"{config.diagnosis_persistence:g} s persistence", 930, 225, 180, 90),
    ]
    links = [
        Link(((0, 95), "predictor.w"), "u<sub>cmd</sub>", (40, 90), value="command"),
        Link(("predictor.e", "sum.w"), "ŷ", (312, 90), sign="-"),
        Link(((350, 0), "sum.n"), "y<sub>m</sub> = (ω<sub>m</sub>, i<sub>m</sub>)", (358, 28), "right", sign="+"),
        Link(("sum.e", "features.w"), "residual r", (403, 90), value="residual"),
        Link(("features.e", "detector.w"), "features", (650, 90)),
        Link(("detector.e", "mode.w"), "score S", (895, 90), value="score"),
        Link(("features.s", "context.n"), "features", (536, 185), "right"),
        Link(("context.e", "model.w"), "prompt", (650, 265)),
        Link(("model.e", "filter.w"), "scores", (895, 265), value="top_score"),
        Link(("filter.n", "mode.s"), "stable diagnosis", (1026, 185), "right", value="diagnosis"),
        Link(("detector.s", "model.n"), "triggers<br>request", (776, 180), "right", dashed=True),
        Link(("mode.e", (1195, 95)), "mode", (1152, 90)),
    ]
    return (1200, 330), blocks, links


def room_loop(settings: RoomSettings, interval: float) -> tuple[tuple[float, float], list[Block], list[Link]]:
    """Bang-bang room heating where the language model is the controller."""
    blocks = [
        Block("context", "<b>Prompt builder</b><br>temperature, thresholds,<br>previous heater state", 130, 115, 180, 90),
        Block("model", f"<b>QJev language model</b><br>answers ON or OFF<br>every {interval:g} s", 380, 110, 180, 100,
              "model"),
        Block("heater", f"<b>Heater</b><br>{settings.heater_watts / 1000:g} kW",
              630, 115, 160, 90),
        Block("sum", "<b>Σ</b>", 844, 144, 32, 32, "sum"),
        Block("room", "<b>Room air + walls</b><br>thermal capacity C<br>C·dT/dt = net power", 930, 115, 170, 90),
        Block("loss", "<b>Heat loss</b><br>G·(T - T<sub>out</sub>)<br>×4 when window open", 930, 245, 170, 70),
        Block("thermometer", "<b>Thermometer</b>", 560, 330, 170, 60, "sensor"),
    ]
    links = [
        Link(((0, 160), "context.w"), "desired T*<br>band ±δ", (62, 155), value="target"),
        Link(("context.e", "model.w"), "prompt", (345, 155)),
        Link(("model.e", "heater.w"), "command u", (595, 155), value="heater"),
        Link(("heater.e", "sum.w"), "P<sub>h</sub>", (817, 155), value="power", sign="+"),
        Link(((860, 20), "sum.n"), "disturbance P<sub>d</sub><br>(step / pulse)", (868, 75), "right",
             value="disturbance", sign="+"),
        Link(("sum.e", "room.w"), "P<sub>net</sub>", (903, 155)),
        Link(("room.e", (1180, 160), (1180, 360), "thermometer.e"), "T", (1140, 155), value="temperature"),
        Link(((1180, 280), "loss.e"), junction=True),
        Link(("loss.w", (860, 280), "sum.s"), "P<sub>loss</sub>", (854, 240), "left", value="loss", sign="-"),
        Link(("thermometer.w", (220, 360), "context.s"), "measured T", (390, 355)),
    ]
    return (1200, 400), blocks, links


def readout(top_logprobs: int) -> tuple[tuple[float, float], list[Block], list[Link]]:
    """Two-order letter readout that turns one generated token into a score per option."""
    blocks = [
        Block("inputs", "<b>Inputs</b><br>state text<br>question<br>options", 0, 105, 140, 90),
        Block("first", "<b>Prompt 1</b><br>options labelled<br>A, B, C … in order", 210, 30, 180, 80),
        Block("second", "<b>Prompt 2</b><br>same options,<br>reversed order", 210, 190, 180, 80),
        Block("call1", f"<b>Ollama /api/generate</b><br>1 token, temperature 0<br>top {top_logprobs} log-probabilities",
              450, 30, 190, 80, "model"),
        Block("call2", f"<b>Ollama /api/generate</b><br>1 token, temperature 0<br>top {top_logprobs} log-probabilities",
              450, 190, 190, 80, "model"),
        Block("mass1", "<b>Letter masses</b><br>m = e<sup>log p</sup> per letter<br>normalize to sum 1", 700, 30, 170, 80),
        Block("mass2", "<b>Letter masses</b><br>m = e<sup>log p</sup> per letter<br>normalize to sum 1", 700, 190, 170, 80),
        Block("average", "<b>Average</b><br>p = ½ (p<sub>1</sub> + p<sub>2</sub>)", 930, 110, 150, 80),
    ]
    links = [
        Link(("inputs.e", (175, 150), (175, 70), "first.w")),
        Link(((175, 150), (175, 230), "second.w"), junction=True),
        Link(("first.e", "call1.w")),
        Link(("second.e", "call2.w")),
        Link(("call1.e", "mass1.w"), "tokens", (670, 65)),
        Link(("call2.e", "mass2.w"), "tokens", (670, 225)),
        Link(("mass1.e", (900, 70), (900, 135), (930, 135)), "p<sub>1</sub>", (887, 65)),
        Link(("mass2.e", (900, 230), (900, 165), (930, 165)), "p<sub>2</sub>", (887, 225)),
        Link(("average.e", (1195, 150)), "scores", (1138, 145)),
    ]
    return (1200, 280), blocks, links
