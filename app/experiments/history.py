import csv
import json
import math
from pathlib import Path
import shutil
import tempfile


def clean_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    return value


class RunHistory:
    """Full numerical history is spooled to disk independently of bounded live plots."""

    def __init__(self):
        self._csv = tempfile.TemporaryFile(mode="w+", newline="", encoding="utf-8")
        self._diagnostics = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        self._writer = None
        self.count = 0

    def append(self, row: dict) -> None:
        if self._writer is None:
            self._writer = csv.DictWriter(self._csv, fieldnames=list(row))
            self._writer.writeheader()
        self._writer.writerow(row)
        self.count += 1

    def diagnostic(self, data: dict) -> None:
        self._diagnostics.write(json.dumps(clean_json(data), allow_nan=False) + "\n")

    def export(self, path: str | Path, metadata: dict) -> list[Path]:
        path = Path(path).with_suffix(".csv")
        if not self.count:
            raise ValueError("Run the simulation before exporting.")
        outputs = [path, path.with_suffix(".json"), path.with_name(path.stem + "_diagnostics.jsonl")]
        for source, destination in ((self._csv, outputs[0]), (self._diagnostics, outputs[2])):
            source.flush()
            source.seek(0)
            try:
                with destination.open("w", encoding="utf-8", newline="") as target:
                    shutil.copyfileobj(source, target)
            finally:
                source.seek(0, 2)
        outputs[1].write_text(json.dumps(clean_json(metadata), indent=2, allow_nan=False), encoding="utf-8")
        return outputs

    def close(self) -> None:
        self._csv.close()
        self._diagnostics.close()
