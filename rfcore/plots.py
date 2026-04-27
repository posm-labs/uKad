"""Headless plot generation for taper reports.

Generates PNG plots from AssemblyResult and KlopfensteinProfile using
the matplotlib Agg backend (no GUI required).

All plots use the generalized unequal-port reference convention:
    Port 1 → z01 = ZS
    Port 2 → z02 = ZL
"""

from __future__ import annotations

import pathlib
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

from rfcore.taper_assembly import AssemblyResult
from rfcore.klopfenstein import KlopfensteinProfile


# ── Style constants ──────────────────────────────────────────────────────
_FIGSIZE = (8, 4.5)
_DPI = 150
_COLOR_S11 = "#1f77b4"
_COLOR_S21 = "#2ca02c"
_COLOR_S22 = "#d62728"
_COLOR_PHASE = "#9467bd"
_COLOR_Z = "#1f77b4"
_COLOR_W = "#ff7f0e"
_COLOR_TARGET = "#888888"
_GRID_ALPHA = 0.3


def _style_ax(ax, xlabel: str, ylabel: str, title: str) -> None:
    """Apply consistent axis styling."""
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(True, alpha=_GRID_ALPHA, linewidth=0.5)
    ax.tick_params(labelsize=9)


def _save(fig, path: pathlib.Path) -> None:
    fig.tight_layout()
    fig.savefig(str(path), dpi=_DPI, bbox_inches="tight")
    plt.close(fig)


# ── S-parameter plots ───────────────────────────────────────────────────

def plot_s11(result: AssemblyResult, path: str | pathlib.Path) -> None:
    """Plot |S11| dB vs frequency."""
    path = pathlib.Path(path)
    freqs_ghz = result.freqs / 1e9

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(freqs_ghz, result.s11_db, color=_COLOR_S11, linewidth=1.5,
            label=f"|S11| (z01={result.z01:.0f} Ω)")

    # Γm target line
    gamma_m_db = float(result.s11_db[0])  # S11 at f_start ≈ Γm target
    # Find actual worst point
    worst_idx = int(np.argmax(result.s11_db))
    ax.plot(freqs_ghz[worst_idx], result.s11_db[worst_idx], "v",
            color=_COLOR_S11, markersize=8,
            label=f"Max: {result.max_s11_db:.1f} dB @ {freqs_ghz[worst_idx]:.2f} GHz")

    ax.legend(fontsize=9, loc="upper right")
    _style_ax(ax, "Frequency (GHz)", "|S11| (dB)",
              f"Input Return Loss — z01 = {result.z01:.0f} Ω, z02 = {result.z02:.0f} Ω")
    _save(fig, path)


def plot_s21(result: AssemblyResult, path: str | pathlib.Path) -> None:
    """Plot |S21| dB vs frequency."""
    path = pathlib.Path(path)
    freqs_ghz = result.freqs / 1e9

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(freqs_ghz, result.s21_db, color=_COLOR_S21, linewidth=1.5,
            label="|S21|")

    worst_idx = int(np.argmin(result.s21_db))
    ax.plot(freqs_ghz[worst_idx], result.s21_db[worst_idx], "v",
            color=_COLOR_S21, markersize=8,
            label=f"Worst IL: {result.max_insertion_loss_db:.2f} dB @ {freqs_ghz[worst_idx]:.2f} GHz")

    ax.legend(fontsize=9, loc="lower left")
    _style_ax(ax, "Frequency (GHz)", "|S21| (dB)",
              "Insertion Loss")
    _save(fig, path)


def plot_s22(result: AssemblyResult, path: str | pathlib.Path) -> None:
    """Plot |S22| dB vs frequency."""
    path = pathlib.Path(path)
    freqs_ghz = result.freqs / 1e9

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(freqs_ghz, result.s22_db, color=_COLOR_S22, linewidth=1.5,
            label=f"|S22| (z02={result.z02:.0f} Ω)")

    worst_idx = int(np.argmax(result.s22_db))
    ax.plot(freqs_ghz[worst_idx], result.s22_db[worst_idx], "v",
            color=_COLOR_S22, markersize=8,
            label=f"Max: {result.max_s22_db:.1f} dB @ {freqs_ghz[worst_idx]:.2f} GHz")

    ax.legend(fontsize=9, loc="upper right")
    _style_ax(ax, "Frequency (GHz)", "|S22| (dB)",
              f"Output Return Loss — z01 = {result.z01:.0f} Ω, z02 = {result.z02:.0f} Ω")
    _save(fig, path)


def plot_phase_s21(result: AssemblyResult, path: str | pathlib.Path) -> None:
    """Plot ∠S21 (degrees) vs frequency."""
    path = pathlib.Path(path)
    freqs_ghz = result.freqs / 1e9
    phase_deg = np.angle(result.s_params[:, 1, 0], deg=True)

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(freqs_ghz, phase_deg, color=_COLOR_PHASE, linewidth=1.5)

    _style_ax(ax, "Frequency (GHz)", "∠S21 (°)",
              "Transmission Phase")
    _save(fig, path)


def plot_s_combined(result: AssemblyResult, path: str | pathlib.Path) -> None:
    """Combined |S11|, |S21|, |S22| on one plot."""
    path = pathlib.Path(path)
    freqs_ghz = result.freqs / 1e9

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(freqs_ghz, result.s11_db, color=_COLOR_S11, linewidth=1.5,
            label=f"|S11| (z01={result.z01:.0f}Ω)")
    ax.plot(freqs_ghz, result.s21_db, color=_COLOR_S21, linewidth=1.5,
            label="|S21|")
    ax.plot(freqs_ghz, result.s22_db, color=_COLOR_S22, linewidth=1.5,
            label=f"|S22| (z02={result.z02:.0f}Ω)")

    ax.legend(fontsize=9, loc="best")
    _style_ax(ax, "Frequency (GHz)", "Magnitude (dB)",
              f"S-Parameters — z01={result.z01:.0f}Ω, z02={result.z02:.0f}Ω")
    _save(fig, path)


# ── Geometry plots ───────────────────────────────────────────────────────

def plot_impedance_profile(
    profile: KlopfensteinProfile,
    path: str | pathlib.Path,
) -> None:
    """Plot Z(z) vs position along taper."""
    path = pathlib.Path(path)
    z_mm = profile.z_samples * 1e3
    Z_ohm = profile.Z_profile

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(z_mm, Z_ohm, color=_COLOR_Z, linewidth=1.5)

    # Show ZS and ZL reference lines
    ax.axhline(profile.ZS, color=_COLOR_TARGET, linestyle="--", linewidth=0.8,
               label=f"ZS = {profile.ZS:.1f} Ω")
    ax.axhline(profile.ZL, color=_COLOR_TARGET, linestyle=":", linewidth=0.8,
               label=f"ZL = {profile.ZL:.1f} Ω")

    ax.legend(fontsize=9, loc="best")
    _style_ax(ax, "Position z (mm)", "Impedance Z (Ω)",
              "Ideal Electrical Impedance Profile")
    _save(fig, path)


def plot_width_profile(
    profile: KlopfensteinProfile,
    path: str | pathlib.Path,
) -> None:
    """Plot w(z) vs position — layout-realized width profile."""
    path = pathlib.Path(path)
    z_mm = profile.z_samples * 1e3
    w_mm = profile.w_layout * 1e3

    fig, ax = plt.subplots(figsize=_FIGSIZE)
    ax.plot(z_mm, w_mm, color=_COLOR_W, linewidth=1.5)

    # Mark endpoints
    ax.plot(z_mm[0], w_mm[0], "o", color=_COLOR_W, markersize=6,
            label=f"w_start = {w_mm[0]:.3f} mm")
    ax.plot(z_mm[-1], w_mm[-1], "o", color=_COLOR_W, markersize=6,
            label=f"w_end = {w_mm[-1]:.3f} mm")

    ax.legend(fontsize=9, loc="best")
    _style_ax(ax, "Position z (mm)", "Width w (mm)",
              "Layout-Realized Width Profile")
    _save(fig, path)


# ── Convenience: generate all ────────────────────────────────────────────

def generate_all_plots(
    result: AssemblyResult,
    profile: KlopfensteinProfile,
    output_dir: str | pathlib.Path,
) -> list[pathlib.Path]:
    """Generate all standard report plots as PNGs.

    Returns list of generated file paths.
    """
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files: list[pathlib.Path] = []

    plot_funcs = [
        ("s11_db.png", lambda p: plot_s11(result, p)),
        ("s21_db.png", lambda p: plot_s21(result, p)),
        ("s22_db.png", lambda p: plot_s22(result, p)),
        ("phase_s21.png", lambda p: plot_phase_s21(result, p)),
        ("s_combined.png", lambda p: plot_s_combined(result, p)),
        ("impedance_profile.png", lambda p: plot_impedance_profile(profile, p)),
        ("width_profile.png", lambda p: plot_width_profile(profile, p)),
    ]

    for fname, func in plot_funcs:
        fp = output_dir / fname
        func(fp)
        files.append(fp)

    return files
