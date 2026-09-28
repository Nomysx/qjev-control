"""Y-axis fitting for live plots: the axis follows the data inside the visible time window."""

import numpy as np


class YAutoRange:
    """Fits one plot's y axis to its visible data.

    A minimum span keeps measurement noise from filling the plot, include values stay in view
    (zero lines, thresholds), and the axis grows at once but shrinks gradually so it does not
    jitter. Zooming or dragging the y axis by hand suspends fitting until restore().
    """

    def __init__(self, plot, fields, include=(), min_span: float = 0.0, padding: float = 0.08,
                 shrink_rate: float = 0.25):
        self.plot, self.fields, self.include = plot, tuple(fields), tuple(include)
        self.min_span, self.padding, self.shrink_rate = min_span, padding, shrink_rate
        self.manual = False
        self.snap = True
        plot.hideButtons()
        plot.enableAutoRange(y=False)
        plot.vb.sigRangeChangedManually.connect(self._changed_manually)

    def _changed_manually(self, mask) -> None:
        if mask[1]:
            self.manual = True

    def restore(self) -> None:
        self.manual, self.snap = False, True

    def fit(self, times: np.ndarray, columns: dict[str, np.ndarray]) -> None:
        if self.manual or not len(times):
            return
        x0, x1 = self.plot.vb.viewRange()[0]
        # keep one sample beyond each edge so lines crossing the edge stay in view
        first = max(0, int(np.searchsorted(times, x0)) - 1)
        last = int(np.searchsorted(times, x1, side="right")) + 1
        values = np.concatenate([columns[field][first:last] for field in self.fields])
        values = values[np.isfinite(values)]
        if not values.size:
            return
        low = float(min((values.min(), *self.include)))
        high = float(max((values.max(), *self.include)))
        if high - low < self.min_span:
            middle = (low + high) / 2
            low, high = middle - self.min_span / 2, middle + self.min_span / 2
        margin = (high - low) * self.padding
        low, high = low - margin, high + margin
        if not self.snap:
            current_low, current_high = self.plot.vb.viewRange()[1]
            if low > current_low:
                low = current_low + self.shrink_rate * (low - current_low)
            if high < current_high:
                high = current_high + self.shrink_rate * (high - current_high)
            tolerance = 0.002 * (high - low)
            if abs(low - current_low) < tolerance and abs(high - current_high) < tolerance:
                return
        self.snap = False
        self.plot.setYRange(low, high, padding=0)


def plot_at(plots, scene_position):
    """Return the visible plot under a scene position, or None."""
    for plot in plots:
        if plot.scene() is not None and plot.isVisible() and plot.sceneBoundingRect().contains(scene_position):
            return plot
    return None
