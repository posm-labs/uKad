"""Warning system for RF model confidence tracking.

Warnings are categorized by severity:
  INFO     — informational, no action needed
  WARNING  — degraded confidence, results may be less accurate
  HIGH     — low confidence, EM validation strongly recommended

Confidence propagation: if ANY block is HIGH, the overall chain is LOW-CONFIDENCE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"


@dataclass
class RFWarning:
    """A single RF model warning."""
    severity: Severity
    source: str        # block/module name
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.source}: {self.message}"


@dataclass
class WarningCollector:
    """Collects and categorizes warnings from all blocks."""
    warnings: List[RFWarning] = field(default_factory=list)

    def add(self, severity: Severity, source: str, message: str) -> None:
        self.warnings.append(RFWarning(severity, source, message))

    def add_from_strings(self, source: str, messages: List[str]) -> None:
        """Parse warning strings with 'SEVERITY:' prefix."""
        for msg in messages:
            if msg.startswith("HIGH:"):
                self.add(Severity.HIGH, source, msg[5:].strip())
            elif msg.startswith("WARNING:"):
                self.add(Severity.WARNING, source, msg[8:].strip())
            elif msg.startswith("INFO:"):
                self.add(Severity.INFO, source, msg[5:].strip())
            else:
                self.add(Severity.WARNING, source, msg)

    @property
    def is_low_confidence(self) -> bool:
        """True if any HIGH-severity warning exists."""
        return any(w.severity == Severity.HIGH for w in self.warnings)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def by_severity(self, sev: Severity) -> List[RFWarning]:
        return [w for w in self.warnings if w.severity == sev]

    def summary(self) -> str:
        """Human-readable summary."""
        lines = []
        if self.is_low_confidence:
            lines.append("*** LOW CONFIDENCE — EM validation recommended ***")
        for w in self.warnings:
            lines.append(str(w))
        return "\n".join(lines) if lines else "No warnings."
