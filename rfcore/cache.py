"""In-memory LRU cache for microstrip line-model queries.

The optimizer calls the line model many times with the same (w, f) pairs.
This cache avoids redundant computation.

Cache key: (w_rounded, f_rounded) with configurable precision.
Cache scope: per MicrostripModel instance, in-memory only, no disk persistence.
Max entries: 10000 (configurable).  ~80 MB worst case.
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple


class CacheStats(NamedTuple):
    """Cache hit/miss statistics."""
    hits: int
    misses: int
    maxsize: int
    currsize: int


def make_cached_microstrip(model, maxsize: int = 10000):
    """Create cached wrappers around a MicrostripModel's expensive methods.

    Returns a namespace object with cached versions of:
      .Zc(w, f), .eeff(w, f), .gamma(w, f), .alpha_total(w, f), .beta(w, f)

    The cache keys round w to 1 nm and f to 1 kHz to collapse
    near-identical queries from adaptive refinement.
    """
    W_PRECISION = 1e-9   # 1 nm
    F_PRECISION = 1e3    # 1 kHz

    def _round_key(w: float, f: float) -> tuple[int, int]:
        return (round(w / W_PRECISION), round(f / F_PRECISION))

    @lru_cache(maxsize=maxsize)
    def _zc(key: tuple[int, int]) -> float:
        w = key[0] * W_PRECISION
        f = key[1] * F_PRECISION
        return model.Zc(w, f)

    @lru_cache(maxsize=maxsize)
    def _eeff(key: tuple[int, int]) -> float:
        w = key[0] * W_PRECISION
        f = key[1] * F_PRECISION
        return model.eeff(w, f)

    @lru_cache(maxsize=maxsize)
    def _gamma(key: tuple[int, int]) -> complex:
        w = key[0] * W_PRECISION
        f = key[1] * F_PRECISION
        return model.gamma(w, f)

    @lru_cache(maxsize=maxsize)
    def _alpha(key: tuple[int, int]) -> float:
        w = key[0] * W_PRECISION
        f = key[1] * F_PRECISION
        return model.alpha_total(w, f)

    @lru_cache(maxsize=maxsize)
    def _beta(key: tuple[int, int]) -> float:
        w = key[0] * W_PRECISION
        f = key[1] * F_PRECISION
        return model.beta(w, f)

    class CachedMicrostrip:
        """Cached interface to MicrostripModel."""

        def Zc(self, w: float, f: float) -> float:
            return _zc(_round_key(w, f))

        def eeff(self, w: float, f: float) -> float:
            return _eeff(_round_key(w, f))

        def gamma(self, w: float, f: float) -> complex:
            return _gamma(_round_key(w, f))

        def alpha_total(self, w: float, f: float) -> float:
            return _alpha(_round_key(w, f))

        def beta(self, w: float, f: float) -> float:
            return _beta(_round_key(w, f))

        def clear(self) -> None:
            _zc.cache_clear()
            _eeff.cache_clear()
            _gamma.cache_clear()
            _alpha.cache_clear()
            _beta.cache_clear()

        def stats(self) -> dict[str, CacheStats]:
            return {
                "Zc": CacheStats(*_zc.cache_info()),
                "eeff": CacheStats(*_eeff.cache_info()),
                "gamma": CacheStats(*_gamma.cache_info()),
                "alpha": CacheStats(*_alpha.cache_info()),
                "beta": CacheStats(*_beta.cache_info()),
            }

    return CachedMicrostrip()
