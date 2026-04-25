"""Abstract base class for discontinuity blocks.

Every discontinuity block is a two-port that produces a 2×2 ABCD matrix
at a given frequency.  Blocks may be lossy (complex ABCD elements).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

import numpy as np

from rfcore.network import Mat2


class DiscontinuityBlock(ABC):
    """Abstract base for all endpoint discontinuity blocks."""

    @abstractmethod
    def abcd(self, f: float) -> Mat2:
        """Compute the 2×2 ABCD matrix at frequency f (Hz).

        The returned matrix may have complex elements (lossy block).
        """
        ...

    @abstractmethod
    def validate(self) -> List[str]:
        """Check parameter validity.  Return list of warning strings.

        Warnings are prefixed:
          'INFO:' — informational
          'WARNING:' — degraded confidence
          'HIGH:' — low confidence / out of model validity
        """
        ...

    @abstractmethod
    def params(self) -> Dict:
        """Return all parameters as a serializable dict."""
        ...

    @property
    def name(self) -> str:
        """Human-readable block name."""
        return self.__class__.__name__
