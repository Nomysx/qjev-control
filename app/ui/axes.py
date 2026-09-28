"""Plot axes that write units in square brackets, e.g. "Simulation time [s]"."""

import pyqtgraph as pg


class BracketAxis(pg.AxisItem):
    def labelString(self) -> str:
        if self.labelUnits:
            units = f"[{self.labelUnitPrefix}{self.labelUnits}]"
        elif self.autoSIPrefix and self.autoSIPrefixScale != 1.0:
            units = f"[x{1.0 / self.autoSIPrefixScale:g}]"
        else:
            units = ""
        style = ";".join(f"{key}: {value}" for key, value in self.labelStyle.items())
        return f"<span style='{style}'>{self.labelText} {units}</span>"


def bracket_axes() -> dict[str, BracketAxis]:
    return {"left": BracketAxis("left"), "bottom": BracketAxis("bottom")}
