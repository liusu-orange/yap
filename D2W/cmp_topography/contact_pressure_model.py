#!/usr/bin/env python3
"""Compute compact CMP contact-pressure and Cu height maps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from omegaconf import OmegaConf
from shapely.geometry import box
from shapely.strtree import STRtree

from effective_density import _load_layer_polygons


def _tile_centers(edges: np.ndarray) -> np.ndarray:
    return 0.5 * (np.asarray(edges[:-1], dtype=np.float64) + np.asarray(edges[1:], dtype=np.float64))


def _save_map(
    values: np.ndarray,
    *,
    output_path: Path,
    title: str,
    colorbar_label: str,
    extent: tuple[float, float, float, float],
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
) -> None:
    masked_values = np.ma.masked_invalid(values)
    finite_values = np.asarray(values, dtype=np.float64)[np.isfinite(values)]
    if finite_values.size == 0:
        vmin = 0.0 if vmin is None else vmin
        vmax = 1.0 if vmax is None else vmax
    else:
        vmin = float(np.min(finite_values)) if vmin is None else vmin
        vmax = float(np.max(finite_values)) if vmax is None else vmax
        if vmax <= vmin:
            vmax = vmin + 1.0

    fig, ax = plt.subplots(figsize=(10, 8))
    image = ax.imshow(
        masked_values,
        origin="lower",
        extent=extent,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
        aspect="equal",
    )
    fig.colorbar(image, ax=ax, label=colorbar_label)
    ax.set_title(title)
    ax.set_xlabel("X (um)")
    ax.set_ylabel("Y (um)")
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def compute_pad_size_map(
    *,
    gds_path: Path,
    layer: int,
    datatype: int,
    x_edges_um: np.ndarray,
    y_edges_um: np.ndarray,
) -> np.ndarray:
    """Return an area-weighted equivalent square pad size per density tile."""
    polygons = _load_layer_polygons(gds_path, layer=layer, datatype=datatype)
    tree = STRtree(polygons)
    polygon_sizes = np.asarray([np.sqrt(polygon.area) for polygon in polygons], dtype=np.float64)
    pad_size_map = np.full((len(y_edges_um) - 1, len(x_edges_um) - 1), np.nan, dtype=np.float64)
    for row in range(pad_size_map.shape[0]):
        for col in range(pad_size_map.shape[1]):
            tile = box(
                float(x_edges_um[col]),
                float(y_edges_um[row]),
                float(x_edges_um[col + 1]),
                float(y_edges_um[row + 1]),
            )
            candidate_indices = tree.query(tile)
            if candidate_indices.size == 0:
                continue

            weights = []
            sizes = []
            for index in candidate_indices:
                index = int(index)
                intersection_area = polygons[index].intersection(tile).area
                if intersection_area <= 0:
                    continue
                weights.append(intersection_area)
                sizes.append(polygon_sizes[index])

            if weights:
                # print(f"sizes:{sizes}")
                # print(f"weights:{weights}")
                pad_size_map[row, col] = float(np.average(sizes, weights=weights))

    return pad_size_map


def compute_macro_pressure(
    effective_density: np.ndarray,
    *,
    x_edges_um: np.ndarray,
    y_edges_um: np.ndarray,
    p0_kpa: float,
    density_epsilon: float,
    density_alpha: float,
    edge_beta: float,
    edge_exponent: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert effective density to load-conserving macro contact pressure."""
    rho = np.asarray(effective_density, dtype=np.float64)
    if p0_kpa <= 0:
        raise ValueError("p0_kpa must be positive.")
    if density_epsilon <= 0:
        raise ValueError("density_epsilon must be positive.")

    x_centers = _tile_centers(x_edges_um)
    y_centers = _tile_centers(y_edges_um)
    xx, yy = np.meshgrid(x_centers, y_centers)
    xc = 0.5 * (float(x_edges_um[0]) + float(x_edges_um[-1]))
    yc = 0.5 * (float(y_edges_um[0]) + float(y_edges_um[-1]))
    half_w = 0.5 * (float(x_edges_um[-1]) - float(x_edges_um[0]))
    half_h = 0.5 * (float(y_edges_um[-1]) - float(y_edges_um[0]))
    radius = float(np.sqrt(half_w**2 + half_h**2))
    r_norm = np.sqrt((xx - xc) ** 2 + (yy - yc) ** 2) / max(radius, 1e-12)

    edge_factor = 1.0 + float(edge_beta) * np.power(r_norm, float(edge_exponent))
    raw_factor = np.power(np.maximum(rho, 0.0) + float(density_epsilon), -float(density_alpha))
    raw_factor *= edge_factor
    normalized_factor = raw_factor / float(np.mean(raw_factor))
    return float(p0_kpa) * normalized_factor, normalized_factor


def compute_contact_pressure_maps(
    *,
    density_dir: Path,
    gds_path: Path,
    output_dir: Path,
    layer: int,
    datatype: int,
    p0_kpa: float,
    density_epsilon: float,
    density_alpha: float,
    edge_beta: float,
    edge_exponent: float,
    reference_pad_size_um: float,
    pad_size_coeff: float,
    pad_size_exponent: float,
    preston_k_cu_nm_per_min_kpa: float,
    preston_k_diel_nm_per_min_kpa: float,
    polish_time_min: float,
    platen_velocity: float,
) -> dict[str, object]:
    effective_density = np.load(density_dir / "effective_density.npy")
    local_density = np.load(density_dir / "local_density.npy")
    x_edges_um = np.load(density_dir / "x_edges_um.npy")
    y_edges_um = np.load(density_dir / "y_edges_um.npy")
    if effective_density.shape != local_density.shape:
        raise ValueError("effective_density and local_density shapes do not match.")

    pad_size_map = compute_pad_size_map(
        gds_path=gds_path,
        layer=layer,
        datatype=datatype,
        x_edges_um=x_edges_um,
        y_edges_um=y_edges_um,
    )
    pressure_macro_kpa, pressure_factor = compute_macro_pressure(
        effective_density,
        x_edges_um=x_edges_um,
        y_edges_um=y_edges_um,
        p0_kpa=p0_kpa,
        density_epsilon=density_epsilon,
        density_alpha=density_alpha,
        edge_beta=edge_beta,
        edge_exponent=edge_exponent,
    )

    cu_mask = np.isfinite(pad_size_map) & (local_density > 0.0)
    size_ratio = np.divide(
        pad_size_map,
        float(reference_pad_size_um),
        out=np.zeros_like(pad_size_map, dtype=np.float64),
        where=np.isfinite(pad_size_map),
    )
    pad_size_factor = np.full_like(pad_size_map, np.nan, dtype=np.float64)
    pad_size_factor[cu_mask] = 1.0 + float(pad_size_coeff) * np.power(
        size_ratio[cu_mask],
        float(pad_size_exponent),
    )

    pressure_cu_kpa = np.full_like(pressure_macro_kpa, np.nan, dtype=np.float64)
    pressure_cu_kpa[cu_mask] = pressure_macro_kpa[cu_mask] * pad_size_factor[cu_mask]

    mrr_cu_nm_per_min = (
        float(preston_k_cu_nm_per_min_kpa) * pressure_cu_kpa * float(platen_velocity)
    )
    mrr_diel_nm_per_min = (
        float(preston_k_diel_nm_per_min_kpa) * pressure_macro_kpa * float(platen_velocity)
    )
    dishing_nm = np.full_like(pressure_macro_kpa, np.nan, dtype=np.float64)
    dishing_nm[cu_mask] = np.maximum(
        0.0,
        float(polish_time_min) * (mrr_cu_nm_per_min[cu_mask] - mrr_diel_nm_per_min[cu_mask]),
    )
    mu_h_nm = -dishing_nm

    output_dir.mkdir(parents=True, exist_ok=True)
    arrays = {
        "pad_size_um": pad_size_map,
        "pressure_factor": pressure_factor,
        "pressure_macro_kpa": pressure_macro_kpa,
        "pad_size_factor": pad_size_factor,
        "pressure_cu_kpa": pressure_cu_kpa,
        "mrr_cu_nm_per_min": mrr_cu_nm_per_min,
        "mrr_diel_nm_per_min": mrr_diel_nm_per_min,
        "dishing_nm": dishing_nm,
        "mu_h_nm": mu_h_nm,
    }
    for name, values in arrays.items():
        np.save(output_dir / f"{name}.npy", values)

    extent = (float(x_edges_um[0]), float(x_edges_um[-1]), float(y_edges_um[0]), float(y_edges_um[-1]))
    _save_map(
        pressure_macro_kpa,
        output_path=output_dir / "pressure_macro_kpa.png",
        title="Macro Contact Pressure",
        colorbar_label="Pressure (kPa)",
        extent=extent,
    )
    _save_map(
        pad_size_map,
        output_path=output_dir / "pad_size_um.png",
        title="Area-Weighted Pad Size",
        colorbar_label="Equivalent Square Pad Size (um)",
        extent=extent,
    )
    _save_map(
        pressure_cu_kpa,
        output_path=output_dir / "pressure_cu_kpa.png",
        title="Cu Contact Pressure",
        colorbar_label="Pressure (kPa)",
        extent=extent,
    )
    _save_map(
        dishing_nm,
        output_path=output_dir / "dishing_nm.png",
        title="Predicted Cu Dishing",
        colorbar_label="Dishing (nm)",
        extent=extent,
    )
    _save_map(
        mu_h_nm,
        output_path=output_dir / "mu_h_nm.png",
        title="Predicted Cu Height Mean",
        colorbar_label="mu_h (nm)",
        extent=extent,
        cmap="coolwarm",
    )

    summary = {
        "density_dir": str(density_dir),
        "gds_path": str(gds_path),
        "layer": layer,
        "datatype": datatype,
        "model": {
            "p0_kpa": p0_kpa,
            "density_epsilon": density_epsilon,
            "density_alpha": density_alpha,
            "edge_beta": edge_beta,
            "edge_exponent": edge_exponent,
            "reference_pad_size_um": reference_pad_size_um,
            "pad_size_coeff": pad_size_coeff,
            "pad_size_exponent": pad_size_exponent,
            "preston_k_cu_nm_per_min_kpa": preston_k_cu_nm_per_min_kpa,
            "preston_k_diel_nm_per_min_kpa": preston_k_diel_nm_per_min_kpa,
            "polish_time_min": polish_time_min,
            "platen_velocity": platen_velocity,
        },
        "map_shape": list(effective_density.shape),
        "cu_tile_count": int(np.count_nonzero(cu_mask)),
        "pressure_macro_mean_kpa": float(np.mean(pressure_macro_kpa)),
        "pressure_macro_min_kpa": float(np.min(pressure_macro_kpa)),
        "pressure_macro_max_kpa": float(np.max(pressure_macro_kpa)),
        "pressure_cu_mean_kpa": float(np.nanmean(pressure_cu_kpa)),
        "pressure_cu_min_kpa": float(np.nanmin(pressure_cu_kpa)),
        "pressure_cu_max_kpa": float(np.nanmax(pressure_cu_kpa)),
        "dishing_mean_nm": float(np.nanmean(dishing_nm)),
        "dishing_min_nm": float(np.nanmin(dishing_nm)),
        "dishing_max_nm": float(np.nanmax(dishing_nm)),
        "mu_h_mean_nm": float(np.nanmean(mu_h_nm)),
        "mu_h_min_nm": float(np.nanmin(mu_h_nm)),
        "mu_h_max_nm": float(np.nanmax(mu_h_nm)),
    }
    with open(output_dir / "contact_pressure_summary.json", "w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)
    return summary


def _load_model_config(config_path: Path | None) -> dict[str, float]:
    defaults = {
        "p0_kpa": 30.0,
        "density_epsilon": 0.05,
        "density_alpha": 0.8,
        "edge_beta": 0.0,
        "edge_exponent": 4.0,
        "reference_pad_size_um": 10.0,
        "pad_size_coeff": 0.2,
        "pad_size_exponent": 1.0,
        "preston_k_cu_nm_per_min_kpa": 1.0,
        "preston_k_diel_nm_per_min_kpa": 0.5,
        "polish_time_min": 1.0,
        "platen_velocity": 1.0,
    }
    if config_path is None:
        return defaults

    cfg = OmegaConf.load(config_path)
    if "contact_pressure" in cfg:
        cfg = cfg.contact_pressure
    loaded = OmegaConf.to_container(cfg, resolve=True)
    for key, value in loaded.items():
        if key in defaults:
            defaults[key] = float(value)
    return defaults


def _override_if_present(config: dict[str, float], args: argparse.Namespace) -> dict[str, float]:
    for key in list(config):
        value = getattr(args, key, None)
        if value is not None:
            config[key] = float(value)
    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="YAML model config.")
    parser.add_argument("--density-dir", type=Path, required=True, help="Directory from effective_density.py.")
    parser.add_argument("--gds", type=Path, required=True, help="Input GDSII file.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory.")
    parser.add_argument("--layer", type=int, required=True, help="Cu GDS layer.")
    parser.add_argument("--datatype", type=int, default=0, help="Cu GDS datatype.")
    parser.add_argument("--p0-kpa", type=float, help="Global average pressure.")
    parser.add_argument("--density-epsilon", type=float, help="Density floor.")
    parser.add_argument("--density-alpha", type=float, help="Density pressure exponent.")
    parser.add_argument("--edge-beta", type=float, help="Radial edge-effect amplitude.")
    parser.add_argument("--edge-exponent", type=float, help="Radial edge-effect exponent.")
    parser.add_argument("--reference-pad-size-um", type=float, help="Reference pad size.")
    parser.add_argument("--pad-size-coeff", type=float, help="Pad-size pressure gain.")
    parser.add_argument("--pad-size-exponent", type=float, help="Pad-size pressure exponent.")
    parser.add_argument(
        "--preston-k-cu-nm-per-min-kpa",
        type=float,
        help="Cu Preston coefficient in nm/min/kPa.",
    )
    parser.add_argument(
        "--preston-k-diel-nm-per-min-kpa",
        type=float,
        help="Dielectric Preston coefficient in nm/min/kPa.",
    )
    parser.add_argument("--polish-time-min", type=float, help="CMP polish time.")
    parser.add_argument("--platen-velocity", type=float, help="Relative platen velocity.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_config = _override_if_present(_load_model_config(args.config), args)
    summary = compute_contact_pressure_maps(
        density_dir=args.density_dir,
        gds_path=args.gds,
        output_dir=args.output_dir,
        layer=args.layer,
        datatype=args.datatype,
        p0_kpa=model_config["p0_kpa"],
        density_epsilon=model_config["density_epsilon"],
        density_alpha=model_config["density_alpha"],
        edge_beta=model_config["edge_beta"],
        edge_exponent=model_config["edge_exponent"],
        reference_pad_size_um=model_config["reference_pad_size_um"],
        pad_size_coeff=model_config["pad_size_coeff"],
        pad_size_exponent=model_config["pad_size_exponent"],
        preston_k_cu_nm_per_min_kpa=model_config["preston_k_cu_nm_per_min_kpa"],
        preston_k_diel_nm_per_min_kpa=model_config["preston_k_diel_nm_per_min_kpa"],
        polish_time_min=model_config["polish_time_min"],
        platen_velocity=model_config["platen_velocity"],
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
