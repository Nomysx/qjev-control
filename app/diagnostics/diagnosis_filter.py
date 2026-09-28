class DiagnosisFilter:
    def __init__(self, minimum_score: float = 0.42, persistence: float = 1.0):
        self.minimum_score, self.persistence = minimum_score, persistence
        self.scores: dict[str, float] = {}
        self.active = "unresolved"
        self.candidate = "unresolved"
        self.candidate_since = 0.0
        self.candidate_count = 0
        self.last_time: float | None = None
        self.stable_score = float("nan")
        self.weak_count = 0

    def update(self, scores: dict[str, float], time: float, anomaly: str) -> bool:
        previous = self.active
        if anomaly == "normal" and self.active not in ("healthy", "unresolved"):
            self.active = "unresolved"
        self.scores = {key: 0.5 * value + 0.5 * self.scores.get(key, value)
                       for key, value in scores.items()}
        self.last_time = time
        if self.active != "unresolved" and self.scores.get(self.active, 0) < self.minimum_score * 0.7:
            self.weak_count += 1
            if self.weak_count >= 2:
                self.active = "unresolved"
        else:
            self.weak_count = 0
        ranked = sorted(self.scores, key=self.scores.get, reverse=True)
        winner = ranked[0]
        margin = self.scores[winner] - self.scores[ranked[1]]
        eligible = self.scores[winner] >= self.minimum_score and margin >= 0.10
        if winner == "healthy" and anomaly != "normal":
            eligible = False
        if winner != "healthy" and anomaly == "normal":
            eligible = False
        if self.active != "unresolved" and winner != self.active:
            eligible = eligible and self.scores[winner] >= self.scores[self.active] + 0.12
        if not eligible:
            self.candidate, self.candidate_count = "unresolved", 0
        elif winner != self.candidate:
            self.candidate, self.candidate_since, self.candidate_count = winner, time, 1
        else:
            self.candidate_count += 1
            if self.candidate_count >= 2 and time - self.candidate_since >= self.persistence:
                self.active = winner
        self.stable_score = self.scores.get(self.active, float("nan"))
        return previous != self.active

    def expire(self, time: float, maximum_age: float) -> bool:
        if self.last_time is not None and time - self.last_time > maximum_age:
            changed = self.active != "unresolved"
            self.active = self.candidate = "unresolved"
            self.candidate_count = 0
            self.scores.clear()
            self.last_time = None
            self.stable_score = float("nan")
            self.weak_count = 0
            return changed
        return False
