from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic

from app.diagnostics.qjev_client import ModelDecision, QJevOllamaClient, QUESTION


@dataclass
class DiagnosticRequest:
    generation: int
    time: float
    context: str
    truth: str
    anomaly: str


@dataclass
class DiagnosticReply:
    request: DiagnosticRequest
    decision: ModelDecision | None
    error: str | None
    latency: float


class DiagnosticService:
    """At most one daemon worker; requests never accumulate behind slow inference."""

    def __init__(self, client: QJevOllamaClient, question: str = QUESTION,
                 options: list[dict[str, str]] | None = None):
        self.client = client
        self.question = question
        self.options = options
        self._thread: Thread | None = None
        self._cancel = Event()
        self._replies: Queue[DiagnosticReply] = Queue(maxsize=1)

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit(self, request: DiagnosticRequest) -> bool:
        if self.busy or not self._replies.empty():
            return False
        self._cancel = Event()
        self._thread = Thread(target=self._run, args=(request, self._cancel), daemon=True)
        self._thread.start()
        return True

    def _run(self, request: DiagnosticRequest, cancel: Event) -> None:
        started = monotonic()
        try:
            decision = self.client.classify(request.context, question=self.question,
                                            options=self.options, cancel=cancel)
            reply = DiagnosticReply(request, decision, None, monotonic() - started)
        except Exception as error:
            reply = DiagnosticReply(request, None, str(error), monotonic() - started)
        self._replies.put(reply)

    def poll(self) -> DiagnosticReply | None:
        try:
            return self._replies.get_nowait()
        except Empty:
            return None

    def invalidate(self) -> None:
        self._cancel.set()
        self.poll()
