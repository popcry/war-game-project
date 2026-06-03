"""terrain_grid_30m.csv → 시뮬레이터용 4개 레이어 CSV (1009×744 행렬)

매핑:
  elevation_m   → vuhledar_5x_elevation.csv     (float, meters)
  water_obstacle→ vuhledar_5x_river_mask.csv    (0/1)
  road_type     → vuhledar_5x_road_type.csv     (string label)
  trench_mask   → vuhledar_5x_trench_mask.csv   (all 0, 데이터셋에 trench 정보 없음)

행렬 방향: 행=y(북→남), 열=x(서→동) — 시뮬레이터 픽셀 좌표계와 일치.
"""
import os
import sys
import numpy as np
import pandas as pd

SRC = "/home/kdh/hw/wargame/war-game-project/vuhledar_terrain_project/vuhledar_bbox_5x/data_processed/terrain_grid_30m.csv"
DST_DIR = "/home/kdh/hw/wargame/war-game-project/war-game-modeling/database"
CELL_M = 30


def main():
    print(f"loading {SRC} ...", flush=True)
    df = pd.read_csv(
        SRC,
        usecols=["centroid_x", "centroid_y", "elevation_m", "road_type", "water_obstacle"],
        dtype={"road_type": "string"},
    )
    print(f"loaded {len(df):,} cells", flush=True)

    # 그리드 인덱스 계산
    min_x, max_x = df.centroid_x.min(), df.centroid_x.max()
    min_y, max_y = df.centroid_y.min(), df.centroid_y.max()
    cols = int(round((max_x - min_x) / CELL_M)) + 1
    rows = int(round((max_y - min_y) / CELL_M)) + 1
    print(f"grid: {rows} rows × {cols} cols (= {rows*cols:,} cells, {len(df):,} populated)")

    # row: y가 클수록 북쪽 → row 0 = max_y (북단)
    # col: x가 작을수록 서쪽 → col 0 = min_x (서단)
    df["row"] = ((max_y - df.centroid_y) / CELL_M).round().astype(int)
    df["col"] = ((df.centroid_x - min_x) / CELL_M).round().astype(int)

    # elevation: missing은 0 (시뮬레이터의 LOS 계산에서 안전)
    elev = np.zeros((rows, cols), dtype=np.float32)
    e_df = df.dropna(subset=["elevation_m"])
    elev[e_df.row.values, e_df.col.values] = e_df.elevation_m.values
    elev_path = os.path.join(DST_DIR, "vuhledar_5x_elevation.csv")
    pd.DataFrame(elev).to_csv(elev_path, header=False, index=False, float_format="%.2f")
    print(f"wrote {elev_path}  shape={elev.shape}  range=[{elev.min():.1f}, {elev.max():.1f}]m")

    # river: water_obstacle 1 → 1, else 0
    river = np.zeros((rows, cols), dtype=np.int8)
    river[df.row.values, df.col.values] = df.water_obstacle.fillna(0).astype(int).values
    river_path = os.path.join(DST_DIR, "vuhledar_5x_river_mask.csv")
    pd.DataFrame(river).to_csv(river_path, header=False, index=False)
    print(f"wrote {river_path}  river_cells={int(river.sum()):,}")

    # road: 문자열 라벨 (none/track/residential/...). 누락 셀은 'none'
    road = np.full((rows, cols), "none", dtype=object)
    road[df.row.values, df.col.values] = df.road_type.fillna("none").values
    road_path = os.path.join(DST_DIR, "vuhledar_5x_road_type.csv")
    pd.DataFrame(road).to_csv(road_path, header=False, index=False)
    n_road = int((road != "none").sum())
    print(f"wrote {road_path}  road_cells={n_road:,}")

    # trench: 데이터셋에 없음 → 전부 0
    trench = np.zeros((rows, cols), dtype=np.int8)
    trench_path = os.path.join(DST_DIR, "vuhledar_5x_trench_mask.csv")
    pd.DataFrame(trench).to_csv(trench_path, header=False, index=False)
    print(f"wrote {trench_path}  (all zeros — trench data not in source)")


if __name__ == "__main__":
    main()
