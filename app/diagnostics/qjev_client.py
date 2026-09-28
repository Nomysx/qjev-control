from dataclasses import dataclass
import math
from threading import Event
from time import monotonic

import requests

HYPOTHESES = [
    {"id": "healthy", "description": "Healthy operation: speed and current match the nominal model, with normal sensor noise."},
    {"id": "sensor_bias", "description": "Speed sensor bias: a persistent speed measurement offset with little jitter, while current matches the nominal model."},
    {"id": "sensor_noise", "description": "Speed sensor noise only: irregular speed readings, but current measurements still agree with the nominal model."},
    {"id": "actuator_loss", "description": "Actuator effectiveness loss: inferred voltage responds proportionally to changing command, but with reduced gain; speed and current are below nominal."},
    {"id": "actuator_stuck", "description": "Actuator stuck: inferred motor voltage stays fixed despite changing command, following an abrupt voltage deficit."},
    {"id": "load", "description": "External load disturbance: extra resisting torque appears abruptly and then levels off; current rises."},
    {"id": "friction", "description": "Mechanical friction increase: extra resisting torque grows gradually, often with speed; current rises."},
    {"id": "resistance", "description": "Electrical resistance drift: a gradually growing voltage deficit and lower current, without extra mechanical load."},
    {"id": "unknown", "description": "Unknown or compound fault: both speed AND current measurements are inconsistent or corrupted, or multiple anomalies cannot be explained by one known fault."},
]

QUESTION = "Which condition best explains all the observations, including the current residual?"
SYSTEM_INSTRUCTION = ("You are a judgment engine. Read the question and the options, then decide which single "
                      "option best matches the state. Answer with EXACTLY ONE letter and nothing else.")
LETTER_TOP_LOGPROBS, YES_NO_TOP_LOGPROBS = 20, 10


def option_letters(ordering: list[dict[str, str]]) -> dict[str, str]:
    return {chr(65 + index): option["id"] for index, option in enumerate(ordering)}


def letter_prompt(state: str, question: str, ordering: list[dict[str, str]]) -> str:
    """Qwen chat-formatted raw prompt with thinking closed, so the next token is the answer letter."""
    choices = "\n".join(f"{chr(65 + index)}. {option['description']}" for index, option in enumerate(ordering))
    return (f"<|im_start|>system\n{SYSTEM_INSTRUCTION}<|im_end|>\n"
            f"<|im_start|>user\n[QUESTION]\n{question}\n\n[OPTIONS]\n{choices}\n\n[STATE]\n{state}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def yes_no_prompt(state: str, question: str, option: dict[str, str]) -> str:
    return (f"Context: {state}\nQuestion: {question}\nCandidate: {option['description']}\n"
            "Is this the best match? Answer (Yes/No):")


class QJevError(RuntimeError):
    pass


@dataclass
class ModelDecision:
    scores: dict[str, float]
    raw_token_mass: list[dict[str, float]]
    latency: float
    model: str
    readout: str

    @property
    def selected(self) -> str:
        return max(self.scores, key=self.scores.get)


class QJevOllamaClient:
    """The existing raw Ollama logprob transport with explicit bounded readouts."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qjev-0.8b:latest",
                 timeout: float = 15.0, readout: str = "letters"):
        if readout not in ("letters", "legacy_yes_no"):
            raise ValueError("Readout must be letters or legacy_yes_no.")
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/api/generate"
        self.model, self.timeout, self.readout = model, timeout, readout

    def check_model_available(self) -> str:
        """Return a status message when the configured model is listed by Ollama."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=(2.0, 4.0))
            if response.status_code >= 400:
                raise QJevError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as error:
            raise QJevError(f"Ollama server unavailable: {error}") from error
        except ValueError as error:
            raise QJevError("Ollama returned invalid model-list JSON.") from error
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise QJevError("Ollama returned an invalid model list.")

        names = set()
        for item in data["models"]:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if isinstance(name, str):
                    names.add(name)
        requested = self.model.strip()
        candidates = {requested, f"{requested}:latest"} if ":" not in requested else {requested}
        if not names.intersection(candidates):
            raise QJevError(f"Model '{self.model}' not found on Ollama.")
        return f"Model {self.model} is available at {self.base_url}."

    def payload(self, prompt: str, top: int) -> dict:
        return {"model": self.model, "prompt": prompt, "raw": True, "stream": False,
                "logprobs": True, "top_logprobs": top,
                "options": {"num_predict": 1, "temperature": 0.0}}

    @staticmethod
    def orderings(options: list[dict[str, str]]) -> list[list[dict[str, str]]]:
        """Given and reversed option order; averaging both cancels a preference for early letters."""
        return [options, list(reversed(options))]

    def prompts(self, state: str, question: str = QUESTION,
                options: list[dict[str, str]] | None = None) -> list[tuple[str, str]]:
        """The exact raw prompts one decision sends, in request order, each with a short title."""
        options = HYPOTHESES if options is None else options
        if self.readout == "legacy_yes_no":
            return [(f"Yes/No: {option['id']}", yes_no_prompt(state, question, option)) for option in options]
        return [(title, letter_prompt(state, question, ordering)) for title, ordering
                in zip(("Prompt 1 (given order)", "Prompt 2 (reversed order)"), self.orderings(options))]

    def _tokens(self, prompt: str, top: int, cancel: Event) -> dict[str, float]:
        if cancel.is_set():
            raise QJevError("Request cancelled.")
        try:
            response = requests.post(self.endpoint, json=self.payload(prompt, top), timeout=(3.0, self.timeout))
            if response.status_code >= 400:
                raise QJevError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as error:
            raise QJevError(f"Ollama request failed: {error}") from error
        except ValueError as error:
            raise QJevError("Ollama returned invalid JSON.") from error
        if cancel.is_set():
            raise QJevError("Request cancelled.")
        if not isinstance(data, dict) or data.get("error"):
            raise QJevError(f"Ollama error: {data.get('error') if isinstance(data, dict) else 'invalid response'}")
        try:
            position = data["logprobs"][0]
            alternatives = position["top_logprobs"]
            if not isinstance(alternatives, list) or not alternatives:
                raise ValueError("empty alternatives")
            tokens = {}
            for item in alternatives:
                token, logprob = item["token"], float(item["logprob"])
                if not isinstance(token, str) or not math.isfinite(logprob) or logprob > 1e-5:
                    raise ValueError("invalid token logprob")
                tokens[token] = math.exp(logprob)
            return tokens
        except (KeyError, TypeError, ValueError, IndexError) as error:
            raise QJevError("Ollama returned missing or malformed token logprobs.") from error

    @staticmethod
    def _normalize(masses: dict[str, float]) -> dict[str, float]:
        total = sum(masses.values())
        if not math.isfinite(total) or total <= 0:
            raise QJevError("No usable model token mass; no decision was produced.")
        return {key: value / total for key, value in masses.items()}

    def classify(self, state: str, question: str = QUESTION,
                 options: list[dict[str, str]] | None = None, cancel: Event | None = None) -> ModelDecision:
        options = HYPOTHESES if options is None else options
        if not 2 <= len(options) <= 26 or len({o["id"] for o in options}) != len(options):
            raise ValueError("Supply 2-26 uniquely identified options.")
        cancellation = cancel or Event()
        started = monotonic()
        raw = []
        if self.readout == "legacy_yes_no":
            masses = {}
            for option in options:
                tokens = self._tokens(yes_no_prompt(state, question, option), YES_NO_TOP_LOGPROBS, cancellation)
                mass = sum(value for token, value in tokens.items() if token.strip().capitalize() in ("Yes", "True"))
                if mass <= 0:
                    raise QJevError(f"Affirmative token missing for {option['id']}; truncated logprobs cannot be treated as zero probability.")
                masses[option["id"]] = mass
            raw.append(masses)
            scores = self._normalize(masses)
        else:
            distributions = []
            for ordering in self.orderings(options):
                labels = option_letters(ordering)
                tokens = self._tokens(letter_prompt(state, question, ordering), LETTER_TOP_LOGPROBS, cancellation)
                masses = {key: 0.0 for key in labels.values()}
                for token, mass in tokens.items():
                    label = token.strip()
                    if label in labels:
                        masses[labels[label]] += mass
                missing = [key for key, mass in masses.items() if mass <= 0]
                if missing:
                    raise QJevError("Incomplete option logprobs for " + ", ".join(missing) + ". No distribution fabricated.")
                raw.append(masses)
                distributions.append(self._normalize(masses))
            scores = {key: sum(d[key] for d in distributions) / len(distributions) for key in distributions[0]}
        return ModelDecision(scores, raw, monotonic() - started, self.model, self.readout)

    def choice(self, state: str, question: str, options: list[dict[str, str]]) -> dict:
        result = self.classify(state, question, options)
        return {"selected": result.selected, "confidence": result.scores[result.selected],
                "distribution": result.scores}


class SemIfOllamaClient(QJevOllamaClient):
    """Compatibility entry point for the original experiment's Yes/No readout."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qjev-0.8b:latest"):
        super().__init__(base_url, model, timeout=30.0, readout="legacy_yes_no")
