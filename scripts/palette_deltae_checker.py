#!/usr/bin/env python3
"""Check palette pair distinguishability under common vision deficiencies.

This script mirrors the high-level Leonardo workflow:
1. Simulate colors under a vision condition.
2. Compare the simulated pair with CIEDE2000.
3. Mark pairs with Delta E >= threshold as passing.

It intentionally stays dependency-light so we can use it during design work
without adding scientific Python packages to the repo environment.
"""

from __future__ import annotations

import argparse
import itertools
import math
from dataclasses import dataclass

LEONARDO_DEFAULT_THRESHOLD = 11.0


VISION_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    # Full-severity matrices commonly used from Machado et al. approximations.
    "normal": (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
    "achromatopsia": (
        (0.299, 0.587, 0.114),
        (0.299, 0.587, 0.114),
        (0.299, 0.587, 0.114),
    ),
}


@dataclass(frozen=True)
class Color:
    label: str
    hex_value: str


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def parse_hex_color(value: str, fallback_label: str) -> Color:
    raw = value.strip()
    if "=" in raw:
        label, hex_value = raw.split("=", 1)
        label = label.strip()
    else:
        label = fallback_label
        hex_value = raw
    hex_value = hex_value.strip().lstrip("#")
    if len(hex_value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in hex_value):
        raise ValueError(f"Invalid hex color: {value}")
    return Color(label=label, hex_value=f"#{hex_value.lower()}")


def hex_to_rgb01(hex_value: str) -> tuple[float, float, float]:
    return (
        int(hex_value[1:3], 16) / 255.0,
        int(hex_value[3:5], 16) / 255.0,
        int(hex_value[5:7], 16) / 255.0,
    )


def _cbrt(x: float) -> float:
    return x ** (1 / 3) if x >= 0 else -((-x) ** (1 / 3))


def _lrgb_to_oklab(r: float, g: float, b: float) -> tuple[float, float, float]:
    lo = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * lo + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * lo - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * lo + 0.7827717662 * m - 0.8086757660 * s,
    )


def _oklab_to_lrgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    lo = L + 0.3963377774 * a + 0.2158037573 * b
    m = L - 0.1055613458 * a - 0.0638541728 * b
    s = L - 0.0894841775 * a - 1.2914855480 * b
    return (
        +4.0767416621 * lo**3 - 3.3077115913 * m**3 + 0.2309699292 * s**3,
        -1.2684380046 * lo**3 + 2.6097574011 * m**3 - 0.3413193965 * s**3,
        -0.0041960863 * lo**3 - 0.7034186147 * m**3 + 1.7076147010 * s**3,
    )


def _linear_to_srgb(c: float) -> float:
    if c <= 0.0:
        return 0.0
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def hex_to_oklch(hex_str: str) -> tuple[float, float, float]:
    """Convert a 6-char sRGB hex string to OKLCH (L, C, H in degrees)."""
    h = hex_str.lstrip("#")
    r = int(h[0:2], 16) / 255
    g = int(h[2:4], 16) / 255
    b = int(h[4:6], 16) / 255
    rl = r / 12.92 if r <= 0.04045 else ((r + 0.055) / 1.055) ** 2.4
    gl = g / 12.92 if g <= 0.04045 else ((g + 0.055) / 1.055) ** 2.4
    bl = b / 12.92 if b <= 0.04045 else ((b + 0.055) / 1.055) ** 2.4
    L, a, bb = _lrgb_to_oklab(rl, gl, bl)
    C = math.sqrt(a * a + bb * bb)
    H = math.degrees(math.atan2(bb, a)) % 360
    return (L, C, H)


def oklch_to_hex(L: float, C: float, H: float) -> str:
    """Convert OKLCH (L, C, H in degrees) to a 6-char sRGB hex string.

    Gamut-maps by binary-searching for the largest in-gamut chroma when
    the target (L, C, H) is outside sRGB.
    """

    def _try_c(cc: float) -> tuple[float, float, float] | None:
        a = cc * math.cos(math.radians(H))
        b_ = cc * math.sin(math.radians(H))
        r, g, b = _oklab_to_lrgb(L, a, b_)
        if -1e-5 <= r <= 1.0001 and -1e-5 <= g <= 1.0001 and -1e-5 <= b <= 1.0001:
            return (max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))
        return None

    result = _try_c(C)
    if result is None:
        lo, hi = 0.0, C
        for _ in range(30):
            mid = (lo + hi) / 2
            if _try_c(mid):
                lo = mid
            else:
                hi = mid
        result = _try_c(lo) or (0.0, 0.0, 0.0)
    r, g, b = result
    rs = max(0.0, min(1.0, _linear_to_srgb(r)))
    gs = max(0.0, min(1.0, _linear_to_srgb(g)))
    bs = max(0.0, min(1.0, _linear_to_srgb(b)))
    return f"#{int(round(rs * 255)):02x}{int(round(gs * 255)):02x}{int(round(bs * 255)):02x}"


def srgb_to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def apply_matrix(
    rgb: tuple[float, float, float],
    matrix: tuple[tuple[float, float, float], ...],
) -> tuple[float, float, float]:
    r, g, b = rgb
    return (
        clamp(matrix[0][0] * r + matrix[0][1] * g + matrix[0][2] * b),
        clamp(matrix[1][0] * r + matrix[1][1] * g + matrix[1][2] * b),
        clamp(matrix[2][0] * r + matrix[2][1] * g + matrix[2][2] * b),
    )


def simulate_vision(
    rgb: tuple[float, float, float], vision_type: str
) -> tuple[float, float, float]:
    matrix = VISION_MATRICES[vision_type]
    r, g, b = rgb
    linear_rgb: tuple[float, float, float] = (
        srgb_to_linear(r),
        srgb_to_linear(g),
        srgb_to_linear(b),
    )
    return apply_matrix(linear_rgb, matrix)


def linear_rgb_to_xyz(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    return (
        0.4124564 * r + 0.3575761 * g + 0.1804375 * b,
        0.2126729 * r + 0.7151522 * g + 0.0721750 * b,
        0.0193339 * r + 0.1191920 * g + 0.9503041 * b,
    )


def xyz_to_lab(xyz: tuple[float, float, float]) -> tuple[float, float, float]:
    # D65 reference white.
    xr, yr, zr = 0.95047, 1.00000, 1.08883
    x, y, z = xyz

    def f(t: float) -> float:
        delta = 6 / 29
        if t > delta**3:
            return t ** (1 / 3)
        return t / (3 * delta**2) + 4 / 29

    fx = f(x / xr)
    fy = f(y / yr)
    fz = f(z / zr)
    return ((116 * fy) - 16, 500 * (fx - fy), 200 * (fy - fz))


def linear_rgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    return xyz_to_lab(linear_rgb_to_xyz(rgb))


def delta_e_ciede2000(
    lab1: tuple[float, float, float], lab2: tuple[float, float, float]
) -> float:
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2

    c1 = math.sqrt(a1 * a1 + b1 * b1)
    c2 = math.sqrt(a2 * a2 + b2 * b2)
    c_bar = (c1 + c2) / 2

    c_bar7 = c_bar**7
    g = 0.5 * (1 - math.sqrt(c_bar7 / (c_bar7 + 25**7))) if c_bar else 0.0

    a1_prime = (1 + g) * a1
    a2_prime = (1 + g) * a2
    c1_prime = math.sqrt(a1_prime * a1_prime + b1 * b1)
    c2_prime = math.sqrt(a2_prime * a2_prime + b2 * b2)

    def hue_angle(a_prime: float, b: float) -> float:
        if a_prime == 0 and b == 0:
            return 0.0
        angle = math.degrees(math.atan2(b, a_prime))
        return angle + 360 if angle < 0 else angle

    h1_prime = hue_angle(a1_prime, b1)
    h2_prime = hue_angle(a2_prime, b2)

    delta_l_prime = l2 - l1
    delta_c_prime = c2_prime - c1_prime

    if c1_prime * c2_prime == 0:
        delta_h_prime = 0.0
    else:
        diff = h2_prime - h1_prime
        if abs(diff) <= 180:
            delta_h_prime = diff
        elif diff > 180:
            delta_h_prime = diff - 360
        else:
            delta_h_prime = diff + 360

    delta_big_h_prime = (
        2 * math.sqrt(c1_prime * c2_prime) * math.sin(math.radians(delta_h_prime / 2))
    )

    l_bar_prime = (l1 + l2) / 2
    c_bar_prime = (c1_prime + c2_prime) / 2

    if c1_prime * c2_prime == 0:
        h_bar_prime = h1_prime + h2_prime
    else:
        if abs(h1_prime - h2_prime) <= 180:
            h_bar_prime = (h1_prime + h2_prime) / 2
        elif h1_prime + h2_prime < 360:
            h_bar_prime = (h1_prime + h2_prime + 360) / 2
        else:
            h_bar_prime = (h1_prime + h2_prime - 360) / 2

    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar_prime - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar_prime))
        + 0.32 * math.cos(math.radians(3 * h_bar_prime + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar_prime - 63))
    )

    delta_theta = 30 * math.exp(-(((h_bar_prime - 275) / 25) ** 2))
    c_bar_prime7 = c_bar_prime**7
    r_c = 2 * math.sqrt(c_bar_prime7 / (c_bar_prime7 + 25**7)) if c_bar_prime else 0
    s_l = 1 + (
        0.015 * ((l_bar_prime - 50) ** 2) / math.sqrt(20 + ((l_bar_prime - 50) ** 2))
    )
    s_c = 1 + 0.045 * c_bar_prime
    s_h = 1 + 0.015 * c_bar_prime * t
    r_t = -math.sin(math.radians(2 * delta_theta)) * r_c

    delta_l = delta_l_prime / s_l
    delta_c = delta_c_prime / s_c
    delta_h = delta_big_h_prime / s_h
    return math.sqrt(
        delta_l * delta_l
        + delta_c * delta_c
        + delta_h * delta_h
        + r_t * delta_c * delta_h
    )


def pair_label(color_a: Color, color_b: Color) -> str:
    return f"{color_a.label}-{color_b.label}"


def format_result_cell(delta_e: float, threshold: float) -> str:
    status = "PASS" if delta_e >= threshold else "FAIL"
    return f"{delta_e:5.2f} {status}"


def analyze_palette(colors: list[Color], threshold: float) -> list[str]:
    lines: list[str] = []
    headers = ["pair"] + list(VISION_MATRICES.keys()) + ["weakest"]
    pair_results: list[tuple[str, dict[str, float]]] = []

    for color_a, color_b in itertools.combinations(colors, 2):
        deltas: dict[str, float] = {}
        for vision_type in VISION_MATRICES:
            rgb_a = simulate_vision(hex_to_rgb01(color_a.hex_value), vision_type)
            rgb_b = simulate_vision(hex_to_rgb01(color_b.hex_value), vision_type)
            deltas[vision_type] = delta_e_ciede2000(
                linear_rgb_to_lab(rgb_a), linear_rgb_to_lab(rgb_b)
            )
        pair_results.append((pair_label(color_a, color_b), deltas))

    widths = {header: len(header) for header in headers}
    for label, deltas in pair_results:
        widths["pair"] = max(widths["pair"], len(label))
        weakest = min(deltas.values())
        widths["weakest"] = max(widths["weakest"], len(f"{weakest:5.2f}"))
        for vision_type, value in deltas.items():
            widths[vision_type] = max(
                widths[vision_type], len(format_result_cell(value, threshold))
            )

    def row(values: list[str]) -> str:
        return "  ".join(
            value.ljust(widths[header])
            for value, header in zip(values, headers, strict=True)
        )

    lines.append(row(headers))
    lines.append(row(["-" * widths[header] for header in headers]))
    for label, deltas in pair_results:
        weakest = min(deltas.values())
        values = [label]
        values.extend(
            format_result_cell(deltas[vision_type], threshold)
            for vision_type in VISION_MATRICES
        )
        values.append(f"{weakest:5.2f}")
        lines.append(row(values))

    failing = sorted(
        (
            (label, vision_type, value)
            for label, deltas in pair_results
            for vision_type, value in deltas.items()
            if value < threshold
        ),
        key=lambda item: item[2],
    )
    lines.append("")
    lines.append(f"Threshold: Delta E >= {threshold:.2f} passes")
    if failing:
        lines.append("Failing pair/vision combinations:")
        for label, vision_type, value in failing:
            lines.append(f"  - {label} under {vision_type}: {value:.2f}")
    else:
        lines.append("All pair/vision combinations pass.")
    return lines


def prefix_waterfall(colors: list[Color], threshold: float) -> list[str]:
    lines: list[str] = []
    if len(colors) < 2:
        only = colors[0].label if colors else "none"
        lines.append("Need at least 2 colors for --prefix-waterfall.")
        lines.append(f"Received: {len(colors)} color ({only}).")
        return lines

    headers = [
        "prefix",
        "colors",
        "pairs",
        "fails",
        "worst",
        "fail_rate",
        "weakest_pair",
    ]
    rows: list[list[str]] = []

    for prefix_len in range(2, len(colors) + 1):
        subset = colors[:prefix_len]
        pair_count = 0
        fail_count = 0
        weakest_value = float("inf")
        weakest_label = ""

        for color_a, color_b in itertools.combinations(subset, 2):
            pair_count += 1
            for vision_type in VISION_MATRICES:
                rgb_a = simulate_vision(hex_to_rgb01(color_a.hex_value), vision_type)
                rgb_b = simulate_vision(hex_to_rgb01(color_b.hex_value), vision_type)
                delta_e = delta_e_ciede2000(
                    linear_rgb_to_lab(rgb_a),
                    linear_rgb_to_lab(rgb_b),
                )
                if delta_e < threshold:
                    fail_count += 1
                if delta_e < weakest_value:
                    weakest_value = delta_e
                    weakest_label = f"{color_a.label}-{color_b.label} ({vision_type})"

        vision_pair_checks = pair_count * len(VISION_MATRICES)
        fail_rate = fail_count / vision_pair_checks if vision_pair_checks else 0.0
        rows.append(
            [
                str(prefix_len),
                ",".join(color.label for color in subset),
                str(pair_count),
                str(fail_count),
                f"{weakest_value:.2f}",
                f"{fail_rate:.1%}",
                weakest_label,
            ]
        )

    widths = {
        header: max([len(header), *(len(row[i]) for row in rows)])
        for i, header in enumerate(headers)
    }

    def row(values: list[str]) -> str:
        return "  ".join(
            value.ljust(widths[header])
            for value, header in zip(values, headers, strict=True)
        )

    lines.append(row(headers))
    lines.append(row(["-" * widths[header] for header in headers]))
    lines.extend(row(values) for values in rows)
    lines.append("")
    lines.append(
        "Interpretation: `fails` counts pair/vision combinations with Delta E below "
        f"{threshold:.2f} among the first N colors."
    )
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze pairwise palette distinguishability under simulated vision conditions."
        )
    )
    parser.add_argument(
        "colors",
        nargs="+",
        help=(
            "Hex colors. Optionally prefix with a label, e.g. blue=#2d74b3 cyan=#4cb6d3."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=LEONARDO_DEFAULT_THRESHOLD,
        help="Delta E threshold for passing. Leonardo uses 11 by default.",
    )
    parser.add_argument(
        "--prefix-waterfall",
        action="store_true",
        help=(
            "Show how pairwise failures accumulate as colors are added in order "
            "from left to right."
        ),
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    colors = [
        parse_hex_color(value, fallback_label=f"c{i + 1}")
        for i, value in enumerate(args.colors)
    ]
    output = (
        prefix_waterfall(colors, threshold=args.threshold)
        if args.prefix_waterfall
        else analyze_palette(colors, threshold=args.threshold)
    )
    for line in output:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
