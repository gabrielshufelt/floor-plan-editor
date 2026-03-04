#!/usr/bin/env python3
"""
floor_plan_cleaner.py
=====================
Strips clutter from architectural floor plan PNGs, leaving structural elements:
room outlines (walls), door openings, stair outlines.

Removes: room numbers, text labels, isolated furniture, column/beam markers,
         isolated door-hardware groups, and other non-wall isolated symbols.

Workflow for a new building
---------------------------
1. Drop PNGs in temp_floor_plans/
2. Run:  python floor_plan_cleaner.py --debug
   Read the "CC report before pass-1 filter" printout.
   The main wall network is the LARGEST component (usually 500 000+ px²).
   Isolated non-wall blobs are everything else.
3. Tune MIN_CC_AREA_PASS1 (removes text/small symbols) and
   MIN_CC_AREA_PRE_CLOSE (removes medium blobs like seating groups or
   door-hardware clusters that are isolated from walls BEFORE gap-closing).
   Rule: set each threshold just BELOW the wall-network size.
4. Run without --debug for the final batch.

Known limitation
----------------
Seating rows that share pixels with the auditorium wall (connected in the
drawing) cannot be removed by this script — they merge into the wall CC.
For those floors, do a quick manual erase pass in Inkscape or GIMP after
running this script.

Usage:
    python floor_plan_cleaner.py
    python floor_plan_cleaner.py --debug

Input  : temp_floor_plans/*.png
Output : cleaned_floor_plans/*.png   (white background, black lines)
Debug  : debug_stages/<name>/*.png   (one PNG per pipeline stage)

Tuned for: black-on-white architectural line drawings at ~2000–3000 px wide.
"""

import sys
import cv2
import numpy as np
from pathlib import Path

# ── I/O ─────────────────────────────────────────────────────────────────────
INPUT_DIR  = Path("temp_floor_plans")
OUTPUT_DIR = Path("cleaned_floor_plans")
DEBUG_DIR  = Path("debug_stages")      # only used when --debug is passed

# ── Parameters ───────────────────────────────────────────────────────────────
# All size values are in pixels and calibrated for images ~2000–3000 px wide.
# If your floor plans are significantly larger or smaller, scale proportionally.

# Binarisation
# Pixels darker than BINARY_THRESH are treated as ink.
# Lower if faint wall lines disappear; raise if background speckling survives.
BINARY_THRESH = 200

# Stage 1 – scanner-noise removal
# Morphological open with a small elliptic kernel removes isolated 1–2 px dots
# (scanner speckle, JPEG artifacts) without touching real line art.
DENOISE_KERNEL_PX = 2

# Stage 2 – small isolated-component removal  (text characters, tiny symbols)
# At ~2600 px wide, approximate connected-component sizes:
#   single text character         ~    300 –  1 500 px²
#   3-char label "110"            ~  1 000 –  3 500 px²
#   column/beam marker square     ~  2 000 –  6 000 px²
#   door arc + swing line         ~    200 –  1 000 px²  (OK to lose; gap stays)
#   auditorium seating block      ~ 30 000 – 60 000 px²  ← isolated BEFORE closing
#
# NOTE: the entire wall network is typically ONE huge CC (millions of px²) so
# it always survives regardless of this threshold.
#
# Use --debug to print actual CC sizes for your floor plan, then tune both
# thresholds so they sit between the largest non-wall CC and the wall network.
MIN_CC_AREA_PASS1 = 2500       # (px²) removes text chars and tiny symbols

# Stage 3 – dense-pattern removal  (auditorium seating rows, stair hatching)
# Local ink density is computed via a Gaussian blur; pixels above DENSITY_THRESH
# belong to a "dense region" (repetitive fill pattern).  We erase that region
# entirely.  The room walls surrounding the seating are thick continuous lines
# that survive other stages and do NOT need to be redrawn here.
#
# Key calibration rule: scattered elements (column markers, isolated chairs)
# create LOCAL density well below 0.30 even with a 20px blur.  Tightly-packed
# seat rows produce local densities of 0.50–0.70.  Keep DENSITY_THRESH between
# those two values so only genuine dense fills are caught.
#
# Keep DENSITY_BLUR_RADIUS SMALL (15–25 px) so that a dense seating block at
# one end of the building doesn't spread its influence to the outer walls.
# A 45 px radius creates a 91 px Gaussian kernel — far too large for this image.
# NOTE: generic density-based seating removal is currently DISABLED.
# It works well on very clean seat-row-only regions but will incorrectly
# detect window-hatching patterns on wall lines (which look identical to seat
# rows from a density standpoint), breaking the wall network.  Enable only
# if your floor plan has auditorium seating AND the density threshold can be
# tuned to skip the window-hatch lines on walls.
CLEAN_DENSE_PATTERNS = False
DENSITY_BLUR_RADIUS  = 20      # (px) half-window for density Gaussian
DENSITY_THRESH       = 0.55    # 0–1; high value = only extremely dense areas
DENSE_EXPAND_PX      = 8       # (px) grow mask to close inter-row gaps

# Stage 4 – gap closing
# Bridges tiny breaks in wall lines caused by door openings or the erase step.
# Keep this SMALLER than the narrowest door opening (~40–60 px at this scale)
# so actual door openings are not bridged over.
CLOSE_KERNEL_PX = 5

# Stage 3b – large isolated-blob removal (auditorium seating, large furniture)
# This runs BEFORE gap-closing, while the seating is still a separate CC from
# the wall network.  After gap-closing the two merge and can no longer be split.
#
# From --debug on the sample: wall network = 679 300 px², seating = 34 544 px².
# Any value between those two removes seating without touching the walls.
# Set to 0 to skip (safe default for buildings without large interior features).
MIN_CC_AREA_PRE_CLOSE = 36000  # (px²)  — 0 = disabled.
                                # Run --debug to find CC sizes, then set this to
                                # a value BETWEEN the largest non-wall CC and the
                                # wall network (e.g. 36 000 for this sample plan).

# Stage 5 – post-closing medium-blob removal
# Cleans artifacts introduced by gap-closing (tiny merged blobs).
# The wall network is fully joined at this point so a moderate threshold is safe.
MIN_CC_AREA_PASS2 = 9000       # (px²)

# ─────────────────────────────────────────────────────────────────────────────


def binarize(gray: np.ndarray) -> np.ndarray:
    """Return binary mask: ink = 255, background = 0."""
    _, binary = cv2.threshold(gray, BINARY_THRESH, 255, cv2.THRESH_BINARY_INV)
    return binary


def filter_small_components(binary: np.ndarray, min_area: int) -> np.ndarray:
    """Remove connected components whose pixel area is below min_area."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    out = np.zeros_like(binary)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            out[labels == i] = 255
    return out


def cc_size_report(binary: np.ndarray, n_show: int = 20) -> str:
    """
    Return a text summary of the largest and smallest connected components.
    Useful for calibrating MIN_CC_AREA thresholds.
    """
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    areas = sorted(
        [stats[i, cv2.CC_STAT_AREA] for i in range(1, n)], reverse=True
    )
    total = len(areas)
    lines = [f"  Total components: {total}"]
    if areas:
        lines.append(f"  Largest  {min(n_show, len(areas))}: "
                     + ", ".join(f"{a:,}" for a in areas[:n_show]))
        lines.append(f"  Smallest {min(n_show, len(areas))}: "
                     + ", ".join(f"{a:,}" for a in areas[-n_show:]))
    return "\n".join(lines)


def remove_dense_patterns(binary: np.ndarray) -> np.ndarray:
    """
    Detect and erase high-density fill regions (auditorium seating, diagonal
    hatching).  The room walls that surround these regions are solid lines
    that survive other filter stages, so no boundary redraw is needed.

    Algorithm:
    1. Gaussian-blur the binary mask → per-pixel local ink density (0–1).
    2. Threshold → binary mask of dense regions.
    3. Dilate to close gaps between adjacent rows.
    4. Subtract the grown mask from the binary image.
    """
    floated = binary.astype(np.float32) / 255.0
    ksize   = DENSITY_BLUR_RADIUS * 2 + 1                  # must be odd
    density = cv2.GaussianBlur(floated, (ksize, ksize), DENSITY_BLUR_RADIUS / 2.5)

    dense_mask  = (density > DENSITY_THRESH).astype(np.uint8) * 255
    exp_side    = DENSE_EXPAND_PX * 2 + 1
    expand_k    = np.ones((exp_side, exp_side), np.uint8)
    dense_grown = cv2.dilate(dense_mask, expand_k, iterations=1)

    # Erase the dense region; surrounding wall lines remain intact
    return cv2.subtract(binary, cv2.bitwise_and(dense_grown, binary))


def clean(gray: np.ndarray, debug_dir: Path | None = None,
          stem: str = "img") -> np.ndarray:
    """
    Full cleaning pipeline.
    If debug_dir is given, saves a PNG after each stage there.
    Returns binary ink mask (ink = 255, background = 0).
    """
    def save_stage(name: str, mask: np.ndarray) -> None:
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(debug_dir / f"{stem}__{name}.png"),
                        cv2.bitwise_not(mask))

    binary = binarize(gray)
    save_stage("00_binary", binary)

    # ── Stage 1: scanner-noise removal ──────────────────────────────────────
    k_denoise = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (DENOISE_KERNEL_PX, DENOISE_KERNEL_PX)
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k_denoise)
    save_stage("01_denoised", binary)

    # ── Stage 2: small isolated-component removal ────────────────────────────
    if debug_dir is not None:
        print(f"\n  [debug] CC report before pass-1 filter:")
        print(cc_size_report(binary))
    binary = filter_small_components(binary, MIN_CC_AREA_PASS1)
    save_stage("02_cc_pass1", binary)

    # ── Stage 3: dense-pattern removal (seating, hatching) ──────────────────
    if CLEAN_DENSE_PATTERNS:
        binary = remove_dense_patterns(binary)
        save_stage("03_dense_removed", binary)

    # ── Stage 3b: large isolated-blob removal (seating, before gap-closing) ──
    # Must run BEFORE closing: once gap-closing bridges seating to the wall
    # network they merge into one CC and can no longer be separated.
    if MIN_CC_AREA_PRE_CLOSE > 0:
        if debug_dir is not None:
            print(f"\n  [debug] CC report before pre-close filter:")
            print(cc_size_report(binary))
        binary = filter_small_components(binary, MIN_CC_AREA_PRE_CLOSE)
        save_stage("03b_pre_close_filter", binary)

    # ── Stage 4: gap closing ─────────────────────────────────────────────────
    k_close = cv2.getStructuringElement(
        cv2.MORPH_RECT, (CLOSE_KERNEL_PX, CLOSE_KERNEL_PX)
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k_close)
    save_stage("04_closed", binary)

    # ── Stage 5: post-closing medium-blob removal ─────────────────────────────
    if debug_dir is not None:
        print(f"\n  [debug] CC report before pass-2 filter:")
        print(cc_size_report(binary))
    binary = filter_small_components(binary, MIN_CC_AREA_PASS2)
    save_stage("05_cc_pass2", binary)

    return binary


def process(src: Path, dst: Path, debug: bool = False) -> None:
    img = cv2.imread(str(src))
    if img is None:
        print(f"  [SKIP] Cannot open: {src}")
        return

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    print(f"  {w}x{h} px", end="  ")

    debug_dir = DEBUG_DIR / src.stem if debug else None
    ink_mask  = clean(gray, debug_dir=debug_dir, stem=src.stem)

    result = cv2.bitwise_not(ink_mask)          # white background, black ink
    cv2.imwrite(str(dst), result)
    print(f"-> {dst.name}")


def main() -> None:
    debug = "--debug" in sys.argv

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    seen = {}
    for p in list(INPUT_DIR.glob("*.png")) + list(INPUT_DIR.glob("*.PNG")):
        seen[p.resolve()] = p
    pngs = sorted(seen.values())

    if not pngs:
        print(f"No PNG files found in '{INPUT_DIR}/'.")
        return

    mode = " (debug mode)" if debug else ""
    print(f"Cleaning {len(pngs)} floor plan(s) from '{INPUT_DIR}/'{mode}...\n")
    for src in pngs:
        print(f"  {src.name}", end="  ")
        dst = OUTPUT_DIR / src.name
        process(src, dst, debug=debug)

    print(f"\nDone. Output in '{OUTPUT_DIR}/'.")
    if debug:
        print(f"Stage images in '{DEBUG_DIR}/'.")


if __name__ == "__main__":
    main()
