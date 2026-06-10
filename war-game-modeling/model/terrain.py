import os
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import yaml

from model.unit import Unit, UnitType

with open("config.yaml", "r", encoding='utf-8') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config["simulation"]["pixel_to_meter_scale"]


class Terrain:
    _layer_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

    def __init__(self, dem_file: str = "database/xyz_coordinates.csv"):
        self.terrain_config = config.get("terrain", {})
        self.layered = bool(self.terrain_config.get("elevation_file"))

        self.terrain_decay_rates = {
            "normal": 1.0,
            "mountain": 0.8,
            "river": 0.2,
            "road": 1.15,
            "trench": 0.7,
            **self.terrain_config.get("mobility", {}),
        }
        self.visibility_multipliers = {
            "normal": 1.0,
            "mountain": 0.8,
            "river": 1.0,
            "road": 1.0,
            "trench": 0.5,
            **self.terrain_config.get("visibility", {}),
        }
        self.hit_probability_multipliers = {
            "normal": 1.0,
            "mountain": 0.9,
            "river": 1.0,
            "road": 1.0,
            "trench": 0.6,
            **self.terrain_config.get("hit_probability", {}),
        }
        self.damage_probability_multipliers = {
            "normal": 1.0,
            "mountain": 0.9,
            "river": 1.0,
            "road": 1.0,
            "trench": 0.6,
            **self.terrain_config.get("damage_probability", {}),
        }

        if self.layered:
            self._load_layered_terrain()
        else:
            self._load_legacy_terrain(dem_file)

    def _read_csv_values(self, path: str, dtype: Any = None) -> np.ndarray:
        return pd.read_csv(path, header=None, dtype=dtype).values

    def _load_legacy_terrain(self, dem_file: str) -> None:
        self.dem_data = self._read_csv_values(dem_file).astype(float)
        self.river_mask = None
        self.trench_mask = None
        self.urban_mask = None
        self.forest_mask = None
        self.road_type_data = None
        self.MOUNTAIN_THRESHOLD = 50 / PIXEL_TO_METER_SCALE
        self.RIVER_THRESHOLD = 39 / PIXEL_TO_METER_SCALE

    def _load_layered_terrain(self) -> None:
        elevation_file = self.terrain_config["elevation_file"]
        river_file = self.terrain_config.get("river_mask_file")
        road_file = self.terrain_config.get("road_type_file")
        trench_file = self.terrain_config.get("trench_mask_file")
        trench_labels = tuple(
            str(value).lower()
            for value in self.terrain_config.get("trench_labels", [1, "1", "trench", "true", "t"])
        )
        urban_file_cache = self.terrain_config.get("urban_mask_file")
        forest_file_cache = self.terrain_config.get("forest_mask_file")
        cache_key = (
            elevation_file,
            river_file,
            road_file,
            trench_file,
            urban_file_cache,
            forest_file_cache,
            trench_labels,
            self.terrain_config.get("mountain_threshold_m"),
            self.terrain_config.get("mountain_elevation_quantile", 0.75),
        )

        cached = Terrain._layer_cache.get(cache_key)
        if cached is not None:
            self.dem_data = cached["dem_data"]
            self.river_mask = cached["river_mask"]
            self.trench_mask = cached["trench_mask"]
            self.urban_mask = cached["urban_mask"]
            self.forest_mask = cached["forest_mask"]
            self.road_type_data = cached["road_type_data"]
            self.MOUNTAIN_THRESHOLD = cached["mountain_threshold"]
            self.RIVER_THRESHOLD = None
            return

        self.dem_data = self._read_csv_values(elevation_file).astype(float)
        shape = self.dem_data.shape

        if river_file and os.path.exists(river_file):
            self.river_mask = self._read_csv_values(river_file).astype(float) > 0
        else:
            self.river_mask = np.zeros(shape, dtype=bool)

        if road_file and os.path.exists(road_file):
            road_data = self._read_csv_values(road_file, dtype=str)
            self.road_type_data = np.where(pd.isna(road_data), "none", road_data)
        else:
            self.road_type_data = np.full(shape, "none", dtype=object)

        if trench_file and os.path.exists(trench_file):
            trench_data = self._read_csv_values(trench_file, dtype=str)
            trench_data = np.where(pd.isna(trench_data), "0", trench_data).astype(str)
            normalized = np.char.lower(np.char.strip(trench_data))
            self.trench_mask = np.isin(normalized, list(trench_labels))
        else:
            self.trench_mask = np.zeros(shape, dtype=bool)

        # urban mask (건물·시가지) — 지상 유닛 통행 불가 판정에 사용
        urban_file = self.terrain_config.get("urban_mask_file")
        if urban_file and os.path.exists(urban_file):
            self.urban_mask = self._read_csv_values(urban_file).astype(float) > 0
        else:
            self.urban_mask = np.zeros(shape, dtype=bool)

        # forest mask (산림) — 지상 유닛 감속에 사용
        forest_file = self.terrain_config.get("forest_mask_file")
        if forest_file and os.path.exists(forest_file):
            self.forest_mask = self._read_csv_values(forest_file).astype(float) > 0
        else:
            self.forest_mask = np.zeros(shape, dtype=bool)

        threshold_m = self.terrain_config.get("mountain_threshold_m")
        if threshold_m is None:
            quantile = float(self.terrain_config.get("mountain_elevation_quantile", 0.75))
            threshold_m = float(np.nanquantile(self.dem_data, quantile))
        self.MOUNTAIN_THRESHOLD = float(threshold_m) / PIXEL_TO_METER_SCALE
        self.RIVER_THRESHOLD = None

        Terrain._layer_cache[cache_key] = {
            "dem_data": self.dem_data,
            "river_mask": self.river_mask,
            "trench_mask": self.trench_mask,
            "urban_mask": self.urban_mask,
            "forest_mask": self.forest_mask,
            "road_type_data": self.road_type_data,
            "mountain_threshold": self.MOUNTAIN_THRESHOLD,
        }

    def _index_position(self, position: Tuple[float, float]) -> Tuple[int, int]:
        x, y = position
        return int(x), int(y)

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= y < self.dem_data.shape[0] and 0 <= x < self.dem_data.shape[1]

    def get_elevation(self, position: Tuple[float, float]) -> float:
        """Return elevation in the simulation's scaled elevation unit."""
        x_int, y_int = self._index_position(position)
        if self._in_bounds(x_int, y_int):
            return float(self.dem_data[y_int, x_int]) / PIXEL_TO_METER_SCALE
        return 0.0

    def get_elevation_m(self, position: Tuple[float, float]) -> float:
        """Return raw DEM elevation in meters."""
        x_int, y_int = self._index_position(position)
        if self._in_bounds(x_int, y_int):
            return float(self.dem_data[y_int, x_int])
        return 0.0

    def is_river(self, position: Tuple[float, float]) -> bool:
        x_int, y_int = self._index_position(position)
        if not self._in_bounds(x_int, y_int):
            return False
        if self.layered:
            return bool(self.river_mask[y_int, x_int])
        return self.get_elevation(position) <= self.RIVER_THRESHOLD

    def is_trench(self, position: Tuple[float, float]) -> bool:
        x_int, y_int = self._index_position(position)
        return self._in_bounds(x_int, y_int) and bool(self.trench_mask[y_int, x_int])

    def is_urban(self, position: Tuple[float, float]) -> bool:
        """건물·시가지 셀 여부 — 지상 유닛 통행 불가."""
        x_int, y_int = self._index_position(position)
        if not self._in_bounds(x_int, y_int) or self.urban_mask is None:
            return False
        return bool(self.urban_mask[y_int, x_int])

    def is_forest(self, position: Tuple[float, float]) -> bool:
        """산림 셀 여부 — 지상 유닛 감속(통과는 가능)."""
        x_int, y_int = self._index_position(position)
        if not self._in_bounds(x_int, y_int) or self.forest_mask is None:
            return False
        return bool(self.forest_mask[y_int, x_int])

    def is_passable(self, position: Tuple[float, float], unit_type) -> bool:
        """지상 유닛 통행 가능 여부. 강·건물은 막힘. 드론은 항상 True (비행)."""
        # 드론과 자폭드론은 비행하므로 모두 통과
        from model.unit import UnitType
        if unit_type in (UnitType.DRONE, UnitType.SELF_DEST_DRONE):
            return True
        # 지상 유닛: 강·건물은 차단
        if self.is_river(position):
            return False
        if self.is_urban(position):
            return False
        return True

    def get_road_type(self, position: Tuple[float, float]) -> str:
        x_int, y_int = self._index_position(position)
        if not self._in_bounds(x_int, y_int) or self.road_type_data is None:
            return "none"
        road_type = str(self.road_type_data[y_int, x_int]).strip().lower()
        return road_type if road_type else "none"

    def get_terrain_type(self, position: Tuple[int, int]) -> str:
        """Return terrain by priority: river → urban → trench → road → forest → mountain → normal.

        통행 불가(차단): river, urban
        통행 가능(감속): trench, road(가속), forest, mountain
        """
        if self.is_river(position):
            return "river"
        if self.layered and self.is_urban(position):
            return "urban"
        if self.layered and self.is_trench(position):
            return "trench"
        if self.layered and self.get_road_type(position) != "none":
            return "road"
        if self.layered and self.is_forest(position):
            return "forest"

        elevation = self.get_elevation(position)
        if elevation >= self.MOUNTAIN_THRESHOLD:
            return "mountain"
        return "normal"

    def get_visibility_multiplier(self, position: Tuple[float, float]) -> float:
        terrain_type = self.get_terrain_type(position)
        return float(self.visibility_multipliers.get(terrain_type, 1.0))

    def get_hit_probability_multiplier(self, position: Tuple[float, float]) -> float:
        terrain_type = self.get_terrain_type(position)
        return float(self.hit_probability_multipliers.get(terrain_type, 1.0))

    def get_damage_probability_multiplier(self, position: Tuple[float, float]) -> float:
        terrain_type = self.get_terrain_type(position)
        return float(self.damage_probability_multipliers.get(terrain_type, 1.0))

    def get_terrain_decay_rate(self, unit: Unit, position: Tuple[int, int]) -> float:
        """Return movement speed multiplier for the terrain at position."""
        if unit.unit_type in [UnitType.DRONE, UnitType.SELF_DEST_DRONE]:
            return 1.0

        terrain_type = self.get_terrain_type(position)
        return float(self.terrain_decay_rates.get(terrain_type, 1.0))
