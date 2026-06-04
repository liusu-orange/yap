#!/usr/bin/env python3
"""Generate a synthetic GDSII layout for CMP density experiments."""

from __future__ import annotations

import argparse
from pathlib import Path

import gdstk


CU_LAYER = 10
LABEL_LAYER = 100
DIE_WIDTH_UM = 2000.0
DIE_HEIGHT_UM = 1600.0


def _add_pad_array(
    cell: gdstk.Cell,
    *,
    origin: tuple[float, float],
    region_size: tuple[float, float],
    pad_size: tuple[float, float],
    pitch: tuple[float, float],
    layer: int,
) -> int:
    x0, y0 = origin
    region_w, region_h = region_size
    pad_w, pad_h = pad_size
    pitch_x, pitch_y = pitch
    count = 0

    y = y0
    while y + pad_h <= y0 + region_h + 1e-9:
        x = x0
        while x + pad_w <= x0 + region_w + 1e-9:
            cell.add(gdstk.rectangle((x, y), (x + pad_w, y + pad_h), layer=layer))
            count += 1
            x += pitch_x
        y += pitch_y
    return count


def build_synthetic_layout(output_path: Path, cu_layer: int = CU_LAYER) -> dict[str, int]:
    library = gdstk.Library(unit=1e-6, precision=1e-9)
    cell = library.new_cell("CMP_SYNTHETIC_TOP")

    # Layer 0 outlines the die and experiment regions; it is not included in Cu density.
    cell.add(gdstk.rectangle((0, 0), (DIE_WIDTH_UM, DIE_HEIGHT_UM), layer=0))

    margin = 100.0
    gap = 100.0
    region_w = (DIE_WIDTH_UM - 2 * margin - gap) / 2
    region_h = (DIE_HEIGHT_UM - 2 * margin - gap) / 2
    regions = {
        "small_dense": (margin, margin + region_h + gap),
        "large_dense": (margin + region_w + gap, margin + region_h + gap),
        "small_sparse": (margin, margin),
        "large_sparse": (margin + region_w + gap, margin),
    }

    specs = {
        # Approximately equal nominal density (25%), but different size and pitch.
        "small_dense": ((10.0, 10.0), (20.0, 20.0)),
        "large_dense": ((40.0, 40.0), (80.0, 80.0)),
        # Lower-density regions with the same two feature scales.
        "small_sparse": ((10.0, 10.0), (50.0, 50.0)),
        "large_sparse": ((40.0, 40.0), (200.0, 200.0)),
    }

    counts: dict[str, int] = {}
    for name, origin in regions.items():
        pad_size, pitch = specs[name]
        counts[name] = _add_pad_array(
            cell,
            origin=origin,
            region_size=(region_w, region_h),
            pad_size=pad_size,
            pitch=pitch,
            layer=cu_layer,
        )
        x0, y0 = origin
        cell.add(
            gdstk.rectangle(
                (x0, y0),
                (x0 + region_w, y0 + region_h),
                layer=LABEL_LAYER,
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    library.write_gds(output_path)
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Output GDSII path.")
    parser.add_argument("--cu-layer", type=int, default=CU_LAYER, help="Cu polygon layer.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = build_synthetic_layout(args.output, cu_layer=args.cu_layer)
    print(f"Synthetic CMP GDS written to: {args.output}")
    print(f"Die size: {DIE_WIDTH_UM:.1f} um x {DIE_HEIGHT_UM:.1f} um")
    for name, count in counts.items():
        print(f"{name}: {count} Cu pads")


if __name__ == "__main__":
    main()

