from collections import Counter


class ExperimentMetrics:
    def __init__(self):
        self.faults: list[dict] = []
        self.confusion: Counter = Counter()
        self.confirmed_episodes = 0
        self.false_positive_episodes = 0
        self.incorrect_transitions = 0
        self.diagnoses = 0
        self.latency_sum = 0.0
        self.failures = 0
        self.stale_results = 0
        self.max_speed_residual = 0.0
        self.max_current_residual = 0.0
        self.previous_anomaly = "normal"

    def fault_event(self, event: dict) -> None:
        if event["kind"] == "fault":
            self.faults.append({"fault": event["label"], "start": event["time"], "end": None,
                                "detection_time": None, "first_qjev_time": None, "isolation_time": None})
        elif event["kind"] == "clear":
            for episode in self.faults:
                if episode["end"] is None and event["label"] in (episode["fault"], "all"):
                    episode["end"] = event["time"]

    def observe(self, row: dict) -> None:
        self.max_speed_residual = max(self.max_speed_residual, abs(row["speed_residual_rpm"]))
        self.max_current_residual = max(self.max_current_residual, abs(row["current_residual_a"]))
        if row["anomaly"] == "confirmed anomaly":
            if self.previous_anomaly != "confirmed anomaly":
                self.confirmed_episodes += 1
                if row["truth"] == "healthy":
                    self.false_positive_episodes += 1
            for fault in self.faults:
                if fault["end"] is None and fault["detection_time"] is None:
                    fault["detection_time"] = row["time"]
        self.previous_anomaly = row["anomaly"]

    def inference(self, truth: str, selected: str, latency: float, sample_time: float, received_time: float) -> None:
        self.diagnoses += 1
        self.latency_sum += latency
        self.confusion[(truth, selected)] += 1
        for fault in self.faults:
            if fault["start"] <= sample_time and (fault["end"] is None or sample_time < fault["end"]) and fault["first_qjev_time"] is None:
                fault["first_qjev_time"] = received_time

    def transition(self, active: str, truth: str, time: float) -> None:
        if active != "unresolved" and active != truth:
            self.incorrect_transitions += 1
        for fault in self.faults:
            if fault["end"] is None and active == truth == fault["fault"] and fault["isolation_time"] is None:
                fault["isolation_time"] = time

    def summary(self, diagnosis: str, truth: str) -> dict:
        episodes = []
        for fault in self.faults:
            episode = dict(fault)
            for name, field in (("detection_delay_s", "detection_time"), ("isolation_delay_s", "isolation_time")):
                episode[name] = None if fault[field] is None else fault[field] - fault["start"]
            episodes.append(episode)
        return {"fault_episodes": episodes, "final_diagnosis": diagnosis, "true_fault": truth,
                "final_correct": None if diagnosis == "unresolved" else diagnosis == truth,
                "valid_qjev_decisions": self.diagnoses, "qjev_failures": self.failures,
                "stale_results": self.stale_results,
                "qjev_mean_latency_s": self.latency_sum / self.diagnoses if self.diagnoses else None,
                "false_positive_episodes": self.false_positive_episodes,
                "incorrect_diagnosis_transitions": self.incorrect_transitions,
                "max_speed_residual_rpm": self.max_speed_residual,
                "max_current_residual_a": self.max_current_residual,
                "confusion": [{"truth": pair[0], "prediction": pair[1], "count": count}
                              for pair, count in self.confusion.items()]}
