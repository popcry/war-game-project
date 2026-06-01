"""Fetch DEM for the expanded Vuhledar bbox via Open-Elevation API
and write database/xyz_coordinates.csv compatible with the simulator.

새 bbox (확장 부흘레다르):
  south = 47.6664170
  west  = 37.0680910
  north = 47.8612220
  east  = 37.4654310
Canvas 1200×875, pixel_to_meter_scale=25.
"""
import json
import os
import time
import urllib.request

import numpy as np
from PIL import Image

LAT_S, LON_W = 47.6664170, 37.0680910   # south, west = BR x-min / y-min
LAT_N, LON_E = 47.8612220, 37.4654310   # north, east = TL y-max / x-max

OUT_W, OUT_H = 1200, 875                # canvas size
SAMPLE_W, SAMPLE_H = 100, 73            # API sampling grid (≈7,300 points)

API_URL = "https://api.open-elevation.com/api/v1/lookup"
BATCH = 100

OUT_PATH = "database/xyz_coordinates.csv"
BACKUP_PATH = "database/xyz_coordinates.prev.csv"


def build_sample_grid():
    """SAMPLE_H × SAMPLE_W 격자(위경도). y=0이 top(north), x=0이 west."""
    lats = np.linspace(LAT_N, LAT_S, SAMPLE_H)   # 위에서 아래로
    lons = np.linspace(LON_W, LON_E, SAMPLE_W)   # 왼쪽에서 오른쪽으로
    points = [(float(la), float(lo)) for la in lats for lo in lons]
    return points


def fetch_batch(batch):
    payload = json.dumps(
        {"locations": [{"latitude": la, "longitude": lo} for la, lo in batch]}
    ).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return [float(item["elevation"]) for item in data["results"]]


def fetch_dem():
    points = build_sample_grid()
    elevations = []
    total = len(points)
    print(f"Fetching {total} elevation points in batches of {BATCH}...")
    for i in range(0, total, BATCH):
        batch = points[i:i + BATCH]
        tries = 0
        while True:
            try:
                vals = fetch_batch(batch)
                elevations.extend(vals)
                if (i // BATCH) % 10 == 0:
                    print(f"  {i + len(batch):>5d}/{total}", flush=True)
                break
            except Exception as e:
                tries += 1
                if tries >= 5:
                    print(f"  FAIL after {tries} tries: {e}", flush=True)
                    raise
                wait = 2 ** tries
                print(f"  retry {tries} after {wait}s ({e})", flush=True)
                time.sleep(wait)
    arr = np.array(elevations, dtype=np.float64).reshape(SAMPLE_H, SAMPLE_W)
    print(f"DEM sample shape={arr.shape}, range=[{arr.min():.1f}, {arr.max():.1f}]m")
    return arr


def upsample_to_output(arr):
    """SAMPLE_H × SAMPLE_W → OUT_H × OUT_W (bilinear, via PIL)."""
    img = Image.fromarray(arr.astype(np.float32), mode="F")
    img = img.resize((OUT_W, OUT_H), resample=Image.BILINEAR)
    return np.asarray(img, dtype=np.float64)


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if os.path.exists(OUT_PATH) and not os.path.exists(BACKUP_PATH):
        os.rename(OUT_PATH, BACKUP_PATH)
        print(f"Backed up old DEM → {BACKUP_PATH}")

    sampled = fetch_dem()
    upsampled = upsample_to_output(sampled)
    np.savetxt(OUT_PATH, upsampled, delimiter=",", fmt="%.6f")
    print(f"Wrote {OUT_PATH} shape={upsampled.shape}  "
          f"range=[{upsampled.min():.1f}, {upsampled.max():.1f}]m")


if __name__ == "__main__":
    main()
