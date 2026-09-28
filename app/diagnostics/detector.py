class AnomalyDetector:
    def __init__(self):
        self.state = "normal"
        self.score = 0.0
        self.above_duration = 0.0
        self.clear_duration = 0.0

    def update(self, features: dict[str, float], time: float, dt: float) -> str:
        self.score = max(features["speed_rms"] / 35.0,
                         features["current_rms"] / 0.6,
                         features["speed_std"] / 12.0)
        if time < 1.5:
            self.state = "normal"
            return self.state
        if self.score >= 1.0:
            self.above_duration += dt
            self.clear_duration = 0.0
            if self.state != "confirmed anomaly":
                self.state = "confirmed anomaly" if self.above_duration >= 0.3 else "suspected anomaly"
        elif self.score < 0.65:
            self.above_duration = 0.0
            self.clear_duration += dt
            if self.clear_duration >= 0.6:
                self.state = "normal"
                self.above_duration = 0.0
        else:
            self.above_duration = 0.0
            self.clear_duration = 0.0
        return self.state
