"""744×1009 5x 레이어를 캔버스(1200×875)에 맞춰 리샘플.

- elevation: bilinear
- river/trench mask: nearest (0/1 유지)
- road_type: nearest (문자열 라벨 유지)
- background_5x.png: bilinear, 1200×875로 변환
"""
import os
import numpy as np
import pandas as pd
from PIL import Image

DB = "/home/kdh/hw/wargame/war-game-project/war-game-modeling/database"
TARGET_W, TARGET_H = 1200, 875


def resize_numeric(arr, mode):
    img = Image.fromarray(arr.astype(np.float32), mode="F")
    img = img.resize((TARGET_W, TARGET_H), resample=mode)
    return np.asarray(img, dtype=np.float32)


def resize_categorical(arr):
    """문자열 라벨을 정수로 인코딩 → nearest 리샘플 → 다시 라벨로 디코딩"""
    labels = sorted(set(arr.flatten()))
    label_to_idx = {l: i for i, l in enumerate(labels)}
    idx_to_label = {i: l for l, i in label_to_idx.items()}
    encoded = np.vectorize(label_to_idx.get)(arr).astype(np.float32)
    img = Image.fromarray(encoded, mode="F")
    img = img.resize((TARGET_W, TARGET_H), resample=Image.NEAREST)
    decoded_idx = np.asarray(img, dtype=np.int32)
    return np.vectorize(idx_to_label.get)(decoded_idx)


def main():
    print(f"target size: {TARGET_W} × {TARGET_H}")

    # elevation
    elev = pd.read_csv(f"{DB}/vuhledar_5x_elevation.csv", header=None).values
    elev_r = resize_numeric(elev, Image.BILINEAR)
    pd.DataFrame(elev_r).to_csv(f"{DB}/vuhledar_5x_elevation.csv",
                                header=False, index=False, float_format="%.2f")
    print(f"  elevation: {elev.shape} → {elev_r.shape}, range=[{elev_r.min():.1f}, {elev_r.max():.1f}]m")

    # river mask
    riv = pd.read_csv(f"{DB}/vuhledar_5x_river_mask.csv", header=None).values
    riv_r = (resize_numeric(riv.astype(np.float32), Image.NEAREST) > 0.5).astype(np.int8)
    pd.DataFrame(riv_r).to_csv(f"{DB}/vuhledar_5x_river_mask.csv", header=False, index=False)
    print(f"  river_mask: {riv.shape} → {riv_r.shape}, river_cells={int(riv_r.sum()):,}")

    # trench mask (all zeros, just resize for consistency)
    tre = pd.read_csv(f"{DB}/vuhledar_5x_trench_mask.csv", header=None).values
    tre_r = np.zeros((TARGET_H, TARGET_W), dtype=np.int8)
    pd.DataFrame(tre_r).to_csv(f"{DB}/vuhledar_5x_trench_mask.csv", header=False, index=False)
    print(f"  trench_mask: {tre.shape} → {tre_r.shape} (all zeros)")

    # road_type (categorical)
    road = pd.read_csv(f"{DB}/vuhledar_5x_road_type.csv", header=None, dtype=str).values
    road_r = resize_categorical(road)
    pd.DataFrame(road_r).to_csv(f"{DB}/vuhledar_5x_road_type.csv", header=False, index=False)
    n_road = int((road_r != "none").sum())
    print(f"  road_type: {road.shape} → {road_r.shape}, road_cells={n_road:,}")

    # background image
    bg = Image.open(f"{DB}/background_5x.png").resize((TARGET_W, TARGET_H), Image.BILINEAR)
    bg.save(f"{DB}/background_5x.png")
    print(f"  background_5x.png → {bg.size}")


if __name__ == "__main__":
    main()
