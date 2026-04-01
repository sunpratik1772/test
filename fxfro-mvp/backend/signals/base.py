from __future__ import annotations
from abc import ABC, abstractmethod
from engine.payload import NodePayload, Signal

class BaseSignal(ABC):
    id: str = ""
    label: str = ""
    default_threshold: float = 0.5

    @abstractmethod
    def evaluate(self, inputs: dict[str, NodePayload], params: dict) -> Signal:
        """Run the signal logic. Return a Signal with triggered/score/evidence."""
        ...
