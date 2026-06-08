#!/usr/bin/env python3
"""Extract local and effective Cu density maps from a GDSII layout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import gdstk
import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter
from shapely.geometry import Polygon, box
from shapely.strtree import STRtree


def _print_polygon_debug(index: int, raw_points: np.ndarray, shape: Polygon) -> None:
    print(f"[polygon {index}]")
    print(f"  raw_points shape: {raw_points.shape}")
    print(f"  raw_points:")
    print(raw_points)
    print(f"  shapely type: {shape.geom_type}")
    print(f"  bounds: {shape.bounds}")
    print(f"  area: {shape.area}")
    if hasattr(shape, "exterior"):
        print(f"  exterior coords:")
        print(np.asarray(shape.exterior.coords, dtype=np.float64))
    else:
        print("  exterior coords: unavailable for this geometry type")


def _print_tile_debug(
    *,
    row: int,
    col: int,
    tile: Polygon,
    candidate_indices: np.ndarray,
    polygons: list[Polygon],
) -> None:
    print(f"[tile row={row}, col={col}]")
    print(f"  tile bounds: {tile.bounds}")
    print(f"  tile area: {tile.area}")
    print(f"  candidate polygon indices: {candidate_indices.tolist()}")
    cu_area = 0.0
    for index in candidate_indices:
        polygon_index = int(index)
        intersection = polygons[polygon_index].intersection(tile)
        intersection_area = intersection.area
        cu_area += intersection_area
        print(
            f"  polygon {polygon_index}: "
            f"polygon_bounds={polygons[polygon_index].bounds}, "
            f"intersection_type={intersection.geom_type}, "
            f"intersection_area={intersection_area}"
        )
    print(f"  cu_area: {cu_area}")
    print(f"  density: {min(1.0, cu_area / tile.area)}")


def _load_layer_polygons(
    gds_path: Path,
    layer: int,
    datatype: int,
    debug_polygons: int = 0,
) -> list[Polygon]:
    library = gdstk.read_gds(gds_path)
    top_cells = library.top_level()
    if not top_cells:
        raise ValueError(f"No top-level cells found in {gds_path}")

    polygons: list[Polygon] = []
    for cell in top_cells:
        for polygon in cell.get_polygons(apply_repetitions=True, include_paths=True, depth=None):
            if polygon.layer != layer or polygon.datatype != datatype:
                continue
            raw_points = np.asarray(polygon.points, dtype=np.float64)
            shape = Polygon(raw_points)
            if not shape.is_valid:
                shape = shape.buffer(0)
            if not shape.is_empty and shape.area > 0:
                polygons.append(shape)
                if len(polygons) <= debug_polygons:
                    _print_polygon_debug(len(polygons) - 1, raw_points, shape)

    if not polygons:
        raise ValueError(
            f"No polygons found on layer/datatype {layer}/{datatype} in {gds_path}"
        )
    return polygons


def _layout_bounds(polygons: list[Polygon]) -> tuple[float, float, float, float]:
    bounds = np.asarray([polygon.bounds for polygon in polygons], dtype=np.float64)
    return (
        float(np.min(bounds[:, 0])),
        float(np.min(bounds[:, 1])),
        float(np.max(bounds[:, 2])),
        float(np.max(bounds[:, 3])),
    )


def compute_local_density(
    polygons: list[Polygon],
    *,
    tile_size_um: float,
    bounds: tuple[float, float, float, float] | None = None,
    debug_tiles: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if tile_size_um <= 0:
        raise ValueError("tile_size_um must be positive.")
    if bounds is None:
        bounds = _layout_bounds(polygons)

    xmin, ymin, xmax, ymax = bounds
    x_edges = np.arange(xmin, xmax + tile_size_um, tile_size_um, dtype=np.float64)
    y_edges = np.arange(ymin, ymax + tile_size_um, tile_size_um, dtype=np.float64)
    if x_edges[-1] < xmax:
        x_edges = np.append(x_edges, xmax)
    if y_edges[-1] < ymax:
        y_edges = np.append(y_edges, ymax)

    tree = STRtree(polygons)
    density = np.zeros((len(y_edges) - 1, len(x_edges) - 1), dtype=np.float64)
    debug_tiles_printed = 0

    for row in range(density.shape[0]):
        for col in range(density.shape[1]):
            tile = box(x_edges[col], y_edges[row], x_edges[col + 1], y_edges[row + 1])
            candidate_indices = tree.query(tile)
            if candidate_indices.size == 0:
                continue
            cu_area = sum(polygons[int(index)].intersection(tile).area for index in candidate_indices)
            if debug_tiles_printed < debug_tiles and cu_area > 0:
                _print_tile_debug(
                    row=row,
                    col=col,
                    tile=tile,
                    candidate_indices=candidate_indices,
                    polygons=polygons,
                )
                debug_tiles_printed += 1
            density[row, col] = min(1.0, cu_area / tile.area)

    return density, x_edges, y_edges


def compute_effective_density(
    local_density: np.ndarray,
    *,
    interaction_length_um: float,
    tile_size_um: float,
) -> np.ndarray:
    if interaction_length_um <= 0:
        raise ValueError("interaction_length_um must be positive.")
    sigma_tiles = interaction_length_um / tile_size_um

    # Normalize by the filtered support so the die boundary does not create an
    # artificial low-density halo.
    numerator = gaussian_filter(
        local_density,
        sigma=sigma_tiles,
        mode="constant",
        cval=0.0,
        truncate=4.0,
    )
    denominator = gaussian_filter(
        np.ones_like(local_density),
        sigma=sigma_tiles,
        mode="constant",
        cval=0.0,
        truncate=4.0,
    )
    return np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator),
        where=denominator > 0,
    )


def _save_map(
    values: np.ndarray,
    *,
    output_path: Path,
    title: str,
    colorbar_label: str,
    extent: tuple[float, float, float, float],
) -> None:
    fig, ax = plt.subplots(figsize=(10, 8))
    image = ax.imshow(
        values,
        origin="lower",
        extent=extent,
        cmap="viridis",
        vmin=0.0,
        vmax=1.0,
        interpolation="nearest",
        aspect="equal",
    )
    fig.colorbar(image, ax=ax, label=colorbar_label)
    ax.set_title(title)
    ax.set_xlabel("X (um)")
    ax.set_ylabel("Y (um)")
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def extract_density_maps(
    *,
    gds_path: Path,
    output_dir: Path,
    layer: int,
    datatype: int,
    tile_size_um: float,
    interaction_length_um: float,
    bounds: tuple[float, float, float, float] | None,
    debug_polygons: int = 0,
    debug_tiles: int = 0,
) -> dict[str, object]:
    polygons = _load_layer_polygons(
        gds_path,
        layer=layer,
        datatype=datatype,
        debug_polygons=debug_polygons,
    )
    if bounds is None:
        bounds = _layout_bounds(polygons)
    print(f"bounds:{bounds}")
    local_density, x_edges, y_edges = compute_local_density(
        polygons,
        tile_size_um=tile_size_um,
        bounds=bounds,
        debug_tiles=debug_tiles,
    )
    effective_density = compute_effective_density(
        local_density,
        interaction_length_um=interaction_length_um,
        tile_size_um=tile_size_um,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "local_density.npy", local_density)
    np.save(output_dir / "effective_density.npy", effective_density)
    np.save(output_dir / "x_edges_um.npy", x_edges)
    np.save(output_dir / "y_edges_um.npy", y_edges)

    extent = (float(x_edges[0]), float(x_edges[-1]), float(y_edges[0]), float(y_edges[-1]))
    _save_map(
        local_density,
        output_path=output_dir / "local_density.png",
        title=f"Local Cu Density ({tile_size_um:g} um Tiles)",
        colorbar_label="Local Cu Area Fraction",
        extent=extent,
    )
    _save_map(
        effective_density,
        output_path=output_dir / "effective_density.png",
        title=f"Effective Cu Density (Gaussian L={interaction_length_um:g} um)",
        colorbar_label="Effective Cu Density",
        extent=extent,
    )

    summary = {
        "gds_path": str(gds_path),
        "layer": layer,
        "datatype": datatype,
        "polygon_count": len(polygons),
        "bounds_um": list(bounds),
        "tile_size_um": tile_size_um,
        "interaction_length_um": interaction_length_um,
        "map_shape": list(local_density.shape),
        "local_density_min": float(np.min(local_density)),
        "local_density_max": float(np.max(local_density)),
        "local_density_mean": float(np.mean(local_density)),
        "effective_density_min": float(np.min(effective_density)),
        "effective_density_max": float(np.max(effective_density)),
        "effective_density_mean": float(np.mean(effective_density)),
    }
    with open(output_dir / "density_summary.json", "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gds", type=Path, required=True, help="Input GDSII file.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory.")
    parser.add_argument("--layer", type=int, required=True, help="Cu GDS layer.")
    parser.add_argument("--datatype", type=int, default=0, help="Cu GDS datatype.")
    parser.add_argument("--tile-size-um", type=float, default=20.0, help="Density tile size.")
    parser.add_argument(
        "--interaction-length-um",
        type=float,
        default=150.0,
        help="Gaussian CMP interaction length (sigma).",
    )
    parser.add_argument(
        "--bounds-um",
        type=float,
        nargs=4,
        metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
        help="Optional extraction bounds. Defaults to selected-layer polygon bounds.",
    )
    parser.add_argument(
        "--debug-polygons",
        type=int,
        default=0,
        metavar="N",
        help="Print the first N loaded Cu polygons for debugging.",
    )
    parser.add_argument(
        "--debug-tiles",
        type=int,
        default=0,
        metavar="N",
        help="Print the first N density tiles that overlap Cu polygons with positive area.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = extract_density_maps(
        gds_path=args.gds,
        output_dir=args.output_dir,
        layer=args.layer,
        datatype=args.datatype,
        tile_size_um=args.tile_size_um,
        interaction_length_um=args.interaction_length_um,
        bounds=tuple(args.bounds_um) if args.bounds_um else None,
        debug_polygons=args.debug_polygons,
        debug_tiles=args.debug_tiles,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
