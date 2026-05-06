from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert vuhledar_terrain_project grid data into war-game raster layers."
    )
    parser.add_argument(
        "--source-grid",
        default="../vuhledar_terrain_project/data_processed/terrain_grid_30m.csv",
        help="Path to terrain_grid_30m.csv or terrain_grid_50m.csv.",
    )
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=450)
    parser.add_argument("--output-dir", default="database")
    parser.add_argument("--prefix", default="vuhledar")
    return parser.parse_args()


def fill_numeric_grid(values: np.ndarray) -> np.ndarray:
    frame = pd.DataFrame(values)
    frame = frame.interpolate(axis=1, limit_direction="both")
    frame = frame.interpolate(axis=0, limit_direction="both")
    frame = frame.ffill(axis=1).bfill(axis=1).ffill(axis=0).bfill(axis=0)
    return frame.values


def pivot_source_grid(source_grid: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    columns = [
        "centroid_x",
        "centroid_y",
        "elevation_m",
        "terrain_type",
        "road_type",
        "water_obstacle",
    ]
    df = pd.read_csv(source_grid, usecols=columns)
    df["river_mask"] = (
        (df["water_obstacle"].fillna(0).astype(float) > 0)
        | (df["terrain_type"].fillna("").str.lower() == "water")
    ).astype(int)
    df["road_type"] = df["road_type"].fillna("none").astype(str).str.lower()

    x_values = np.sort(df["centroid_x"].unique())
    y_values = np.sort(df["centroid_y"].unique())[::-1]

    elevation = (
        df.pivot(index="centroid_y", columns="centroid_x", values="elevation_m")
        .reindex(index=y_values, columns=x_values)
        .values
    )
    river = (
        df.pivot(index="centroid_y", columns="centroid_x", values="river_mask")
        .reindex(index=y_values, columns=x_values)
        .fillna(0)
        .values
        .astype(int)
    )
    road = (
        df.pivot(index="centroid_y", columns="centroid_x", values="road_type")
        .reindex(index=y_values, columns=x_values)
        .fillna("none")
        .values
    )

    elevation = fill_numeric_grid(elevation)
    return elevation, river, road, np.array([len(y_values), len(x_values)])


def resample_nearest(values: np.ndarray, height: int, width: int) -> np.ndarray:
    source_h, source_w = values.shape
    row_idx = np.rint(np.linspace(0, source_h - 1, height)).astype(int)
    col_idx = np.rint(np.linspace(0, source_w - 1, width)).astype(int)
    return values[np.ix_(row_idx, col_idx)]


def main() -> None:
    args = parse_args()
    source_grid = Path(args.source_grid)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    elevation, river, road, source_shape = pivot_source_grid(source_grid)
    elevation_out = resample_nearest(elevation, args.height, args.width)
    river_out = resample_nearest(river, args.height, args.width).astype(int)
    road_out = resample_nearest(road, args.height, args.width).astype(str)
    trench_out = np.zeros((args.height, args.width), dtype=int)

    elevation_path = output_dir / f"{args.prefix}_elevation.csv"
    river_path = output_dir / f"{args.prefix}_river_mask.csv"
    road_path = output_dir / f"{args.prefix}_road_type.csv"
    trench_path = output_dir / f"{args.prefix}_trench_mask.csv"

    np.savetxt(elevation_path, elevation_out, delimiter=",", fmt="%.3f")
    np.savetxt(river_path, river_out, delimiter=",", fmt="%d")
    np.savetxt(road_path, road_out, delimiter=",", fmt="%s")
    if not trench_path.exists():
        np.savetxt(trench_path, trench_out, delimiter=",", fmt="%d")

    threshold = float(np.nanquantile(elevation_out, 0.75))
    print(f"Source grid shape: {int(source_shape[0])} x {int(source_shape[1])}")
    print(f"Output shape: {args.height} x {args.width}")
    print(f"Elevation CSV: {elevation_path}")
    print(f"River mask CSV: {river_path}")
    print(f"Road type CSV: {road_path}")
    print(f"Trench mask CSV: {trench_path}")
    print(f"Mountain threshold, top 25% q75: {threshold:.3f} m")
    print(f"River cells: {int(river_out.sum())}")
    print(f"Road cells: {int((road_out != 'none').sum())}")


if __name__ == "__main__":
    main()
