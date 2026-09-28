import json
import math

from PySide6.QtWidgets import (QFormLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QProgressBar, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from app.simulation.faults import FAULT_NAMES


class DiagnosticsPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setContentsMargins(5, 5, 5, 7)
        self.labels = {}
        for key, caption in (("anomaly", "Fast detector"), ("active", "Stable diagnosis"),
                             ("candidate", "Candidate"), ("score", "Accepted EMA score"),
                             ("latency", "Inference latency"), ("update", "Sample / age")):
            label = QLabel("--")
            label.setWordWrap(True)
            form.addRow(caption, label)
            self.labels[key] = label
        status = QWidget()
        status.setLayout(form)
        layout.addWidget(status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        scores = QWidget()
        scores_layout = QVBoxLayout(scores)
        self.table = QTableWidget(len(FAULT_NAMES), 3)
        self.table.setHorizontalHeaderLabels(["Hypothesis", "Model", "EMA"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 105)
        self.table.setColumnWidth(2, 48)
        self.bars = {}
        for row, (key, name) in enumerate(FAULT_NAMES.items()):
            item = QTableWidgetItem(name)
            item.setToolTip(name)
            self.table.setItem(row, 0, item)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(0)
            bar.setFormat("--")
            self.table.setCellWidget(row, 1, bar)
            self.table.setItem(row, 2, QTableWidgetItem("--"))
            self.table.setRowHeight(row, 31)
            self.bars[key] = bar
        scores_layout.addWidget(self.table)
        self.tabs.addTab(scores, "Scores")
        self.context = QPlainTextEdit()
        self.context.setReadOnly(True)
        self.context.setPlaceholderText("The exact observable context sent to the model appears here.")
        self.tabs.addTab(self.context, "Context")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.tabs.addTab(self.raw, "Raw output")
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.tabs.addTab(self.summary, "Evaluation")
        layout.addWidget(QLabel("EVENT LOG"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setMinimumHeight(110)
        layout.addWidget(self.log)
        self.last_decision = None
        self.last_context = None

    def refresh(self, simulation) -> None:
        s, d = simulation, simulation.diagnosis
        self.labels["anomaly"].setText(f"{s.detector.state} ({s.detector.score:.2f})")
        self.labels["active"].setText(FAULT_NAMES.get(d.active, "Unresolved"))
        self.labels["candidate"].setText(FAULT_NAMES.get(d.candidate, "Insufficient separation"))
        self.labels["score"].setText(f"{d.stable_score:.1%}" if math.isfinite(d.stable_score) else "--")
        self.labels["latency"].setText(f"{s.last_latency*1000:.0f} ms" if s.last_latency is not None else "--")
        self.labels["update"].setText(f"t={s.last_model_time:.2f} s / {s.time-s.last_model_time:.2f} s old" if s.last_model_time is not None else "--")
        if self.last_context != s.last_context:
            self.context.setPlainText(s.last_context)
            self.last_context = s.last_context
        decision = s.last_decision
        stale = decision is not None and (s.last_model_time is None or s.time - s.last_model_time > s.config.timing.result_max_age)
        for row, key in enumerate(FAULT_NAMES):
            score = decision.scores.get(key) if decision else None
            bar = self.bars[key]
            bar.setValue(round(score * 1000) if score is not None else 0)
            bar.setFormat(f"{score:.1%}" if score is not None else "--")
            winner = decision is not None and not stale and decision.selected == key
            color = "#858585" if stale else ("#bd8128" if key == "unknown" else ("#3b7b4b" if winner else "#6485a2"))
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {color}; }}")
            self.table.item(row, 2).setText(f"{d.scores[key]:.0%}" if key in d.scores and not stale else "--")
        if decision is not self.last_decision:
            self.raw.setPlainText(json.dumps({"model": decision.model, "readout": decision.readout,
                                              "raw_token_mass_by_order": decision.raw_token_mass,
                                              "normalized_scores": decision.scores}, indent=2) if decision else "")
            self.last_decision = decision
        self.summary.setPlainText(json.dumps(s.metrics.summary(d.active, s.truth), indent=2))
