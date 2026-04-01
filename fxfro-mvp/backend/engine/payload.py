from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Signal:
    id: str
    label: str
    triggered: bool
    score: float          # 0.0 – 1.0
    evidence: dict        # key facts that caused it
    threshold: float = 0.5

@dataclass
class NodePayload:
    node_id:    str
    node_type:  str       # source | transform | signal | analyst | output
    label:      str

    rows:       list[dict] = field(default_factory=list)
    row_count:  int = 0
    schema:     list[dict] = field(default_factory=list)   # [{name, type, description}]

    signals:    list[Signal] = field(default_factory=list)

    summary_text: str = ""
    warnings:     list[str] = field(default_factory=list)

    execution_ms:     int = 0
    filters_applied:  dict = field(default_factory=dict)

    csv_filename: str = ""   # basename only; served from /files/
    metadata:     dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id":        self.node_id,
            "node_type":      self.node_type,
            "label":          self.label,
            "row_count":      self.row_count,
            "summary_text":   self.summary_text,
            "warnings":       self.warnings,
            "execution_ms":   self.execution_ms,
            "filters_applied": self.filters_applied,
            "csv_filename":   self.csv_filename,
            "metadata":       self.metadata,
            "signals": [
                {
                    "id":        s.id,
                    "label":     s.label,
                    "triggered": s.triggered,
                    "score":     s.score,
                    "evidence":  s.evidence,
                    "threshold": s.threshold,
                }
                for s in self.signals
            ],
            "rows": self.rows[:50],   # cap at 50 rows for SSE payload
        }
