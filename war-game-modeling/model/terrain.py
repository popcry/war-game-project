import os
import math
from collections import deque
from typing import Any, Dict, Optional, Tuple

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
        self.railway_mask = None
        self.bridge_mask = None
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
        railway_file_cache = self.terrain_config.get("railway_mask_file")
        bridge_file_cache = self.terrain_config.get("bridge_mask_file")
        cache_key = (
            elevation_file,
            river_file,
            road_file,
            trench_file,
            urban_file_cache,
            forest_file_cache,
            railway_file_cache,
            bridge_file_cache,
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
            self.railway_mask = cached["railway_mask"]
            self.bridge_mask = cached["bridge_mask"]
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

        # railway mask (철도) — 선형 장애물, 감속
        railway_file = self.terrain_config.get("railway_mask_file")
        if railway_file and os.path.exists(railway_file):
            self.railway_mask = self._read_csv_values(railway_file).astype(float) > 0
        else:
            self.railway_mask = np.zeros(shape, dtype=bool)

        # bridge mask (교량) — 강 위 통행 허용 + 도로 속도
        bridge_file = self.terrain_config.get("bridge_mask_file")
        if bridge_file and os.path.exists(bridge_file):
            self.bridge_mask = self._read_csv_values(bridge_file).astype(float) > 0
        else:
            self.bridge_mask = np.zeros(shape, dtype=bool)

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
            "railway_mask": self.railway_mask,
            "bridge_mask": self.bridge_mask,
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

    def is_railway(self, position: Tuple[float, float]) -> bool:
        """철도 회랑 셀 여부 — 선형 장애물, 횡단 시 감속."""
        x_int, y_int = self._index_position(position)
        if not self._in_bounds(x_int, y_int) or self.railway_mask is None:
            return False
        return bool(self.railway_mask[y_int, x_int])

    def is_bridge(self, position: Tuple[float, float]) -> bool:
        """교량 셀 여부 — 강 위에 있어도 모든 지상 유닛 통행 가능, 도로 속도."""
        x_int, y_int = self._index_position(position)
        if not self._in_bounds(x_int, y_int) or self.bridge_mask is None:
            return False
        return bool(self.bridge_mask[y_int, x_int])

    def is_mountain(self, position: Tuple[float, float]) -> bool:
        """언덕·산악 셀 여부 — DEM elevation이 mountain_threshold를 넘으면 True."""
        return self.get_elevation(position) >= self.MOUNTAIN_THRESHOLD

    def add_obstacle(self, position: Tuple[float, float], radius: int = 1) -> None:
        """동적 장애물 등록 (예: 지휘소). 거리장 캐시 무효화."""
        if not hasattr(self, 'obstacle_mask') or self.obstacle_mask is None:
            H, W = self.dem_data.shape
            self.obstacle_mask = np.zeros((H, W), dtype=bool)
        x, y = int(position[0]), int(position[1])
        H, W = self.obstacle_mask.shape
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    self.obstacle_mask[ny, nx] = True
        # 장애물 추가 시 거리장 무효화 — 다음 호출 때 재계산
        if hasattr(self, '_dist_cache'):
            self._dist_cache.clear()

    def is_passable(self, position: Tuple[float, float], unit_type) -> bool:
        """지상 유닛 통행 가능 여부.
        - 드론/자폭드론: 항상 통과 (비행)
        - 교량 위: 모든 지상 유닛 통과 (강 차단 무시)
        - 보병(RIFLE), 대전차(ANTI_TANK): 강 통과 가능 (도하), 건물·언덕은 차단
        - 그 외 지상(전차·포병 등): 강·건물·언덕 모두 차단
        - 동적 장애물(지휘소 등): 모든 지상 유닛 차단
        """
        from model.unit import UnitType
        if unit_type in (UnitType.DRONE, UnitType.SELF_DEST_DRONE):
            return True
        # 동적 장애물 (CP 등) — 다른 차단 검사보다 먼저
        if hasattr(self, 'obstacle_mask') and self.obstacle_mask is not None:
            x_int, y_int = int(position[0]), int(position[1])
            if 0 <= y_int < self.obstacle_mask.shape[0] and 0 <= x_int < self.obstacle_mask.shape[1]:
                if self.obstacle_mask[y_int, x_int]:
                    return False
        # 교량은 다른 차단보다 우선 — 강 위에 놓여도 통행 허용
        if self.is_bridge(position):
            return True
        if self.is_urban(position):
            return False
        if self.is_mountain(position):
            return False
        if self.is_river(position):
            return unit_type in (UnitType.RIFLE, UnitType.ANTI_TANK)
        return True

    def is_passable_path(self, from_pos: Tuple[float, float], to_pos: Tuple[float, float], unit_type) -> bool:
        """from_pos → to_pos 직선 경로상 모든 셀이 통행 가능한가.

        단순 destination 검사는 step이 크면 1px 짜리 강·1셀 건물을 건너뛰는 문제 발생.
        경로를 1px 간격으로 샘플링해서 막힌 셀을 만나면 False 반환.
        드론/자폭드론은 비행이므로 항상 True.
        """
        from model.unit import UnitType
        if unit_type in (UnitType.DRONE, UnitType.SELF_DEST_DRONE):
            return True
        fx, fy = from_pos
        tx, ty = to_pos
        dist = ((tx - fx) ** 2 + (ty - fy) ** 2) ** 0.5
        if dist < 1e-9:
            return self.is_passable(to_pos, unit_type)
        steps = max(1, int(dist) + 1)   # 1px 이하 간격으로 샘플
        for i in range(1, steps + 1):    # 시작 셀은 건너뜀(이미 거기 있음)
            t = i / steps
            x = fx + (tx - fx) * t
            y = fy + (ty - fy) * t
            if not self.is_passable((x, y), unit_type):
                return False
        return True

    def get_road_type(self, position: Tuple[float, float]) -> str:
        x_int, y_int = self._index_position(position)
        if not self._in_bounds(x_int, y_int) or self.road_type_data is None:
            return "none"
        road_type = str(self.road_type_data[y_int, x_int]).strip().lower()
        return road_type if road_type else "none"

    def get_terrain_type(self, position: Tuple[int, int]) -> str:
        """Return terrain by priority: bridge → river → urban → trench → road → railway → forest → mountain → normal.

        통행 불가(차단): river, urban, mountain
        통행 가능(감속): trench, railway, forest
        가속: road, bridge
        교량은 강보다 우선 (강 셀 위에 교량이 놓일 때 강이 아닌 교량으로 분류)
        """
        if self.layered and self.is_bridge(position):
            return "bridge"
        if self.is_river(position):
            return "river"
        if self.layered and self.is_urban(position):
            return "urban"
        if self.layered and self.is_trench(position):
            return "trench"
        if self.layered and self.get_road_type(position) != "none":
            return "road"
        if self.layered and self.is_railway(position):
            return "railway"
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
        # 보병·대전차가 강을 도하할 때는 mobility.river(0)이 아닌 별도 도하 속도 적용
        if terrain_type == "river" and unit.unit_type in (UnitType.RIFLE, UnitType.ANTI_TANK):
            return float(self.terrain_decay_rates.get("river_infantry", 0.2))
        return float(self.terrain_decay_rates.get(terrain_type, 1.0))

    # ============================================================
    # 경로 탐색 (BFS 기반 거리장) — A* 보다 단순하지만 충분히 빠름
    # 캐시: (goal_x, goal_y, unit_group) → 2D 거리장 (int)
    # ============================================================
    @staticmethod
    def _passability_group(unit_type) -> str:
        """is_passable 결과가 같은 unit_type들끼리 묶어 거리장 1번만 계산."""
        if unit_type in (UnitType.DRONE, UnitType.SELF_DEST_DRONE):
            return "air"
        if unit_type in (UnitType.RIFLE, UnitType.ANTI_TANK):
            return "amphib"   # 강 통과 가능
        return "ground"        # 강 차단 (TANK/ARTILLERY/CP)

    def _compute_distance_field(self, goal_x: int, goal_y: int, group: str) -> np.ndarray:
        """벡터화 wave-propagation BFS — 8방향 numpy 시프트.
        반환: (H, W) int32, 도달 불가 셀 = -1, 골부터 거리(셀 수).

        성능: 1200×875 ≈ 2000 iter × 1ms numpy op = ~2초. Python loop 대비 50배+ 빠름.
        """
        H, W = self.dem_data.shape
        field = np.full((H, W), -1, dtype=np.int32)
        if not (0 <= goal_x < W and 0 <= goal_y < H):
            return field

        # 통행 가능 마스크 (그룹별 1번)
        passable = np.ones((H, W), dtype=bool)
        if self.urban_mask is not None:
            passable &= ~self.urban_mask
        # 동적 장애물 (지휘소 등) 차단
        if hasattr(self, 'obstacle_mask') and self.obstacle_mask is not None:
            passable &= ~self.obstacle_mask
        if hasattr(self, 'MOUNTAIN_THRESHOLD') and self.MOUNTAIN_THRESHOLD is not None:
            # MOUNTAIN_THRESHOLD는 elevation의 "scaled" 단위 (m / PIXEL_TO_METER_SCALE)
            # dem_data는 raw meters. 비교 위해 dem / scale 사용해 동일 단위
            from model.movement import PIXEL_TO_METER_SCALE
            passable &= (self.dem_data / PIXEL_TO_METER_SCALE) < self.MOUNTAIN_THRESHOLD
        if group == "ground" and self.river_mask is not None:
            blocked_water = self.river_mask.copy()
            if self.bridge_mask is not None:
                blocked_water = blocked_water & ~self.bridge_mask
            passable &= ~blocked_water
        # amphib는 강 통과

        if not passable[goal_y, goal_x]:
            return field

        # Wave-propagation BFS (8-방향)
        field[goal_y, goal_x] = 0
        frontier = np.zeros_like(passable, dtype=bool)
        frontier[goal_y, goal_x] = True

        step = 0
        max_iter = H + W   # 대각 최대 거리
        while frontier.any() and step < max_iter:
            step += 1
            # 8방향 시프트로 next wave 만들기 (OR)
            nxt = np.zeros_like(frontier)
            nxt[1:, :]   |= frontier[:-1, :]   # 위 → 아래
            nxt[:-1, :]  |= frontier[1:, :]    # 아래 → 위
            nxt[:, 1:]   |= frontier[:, :-1]   # 왼쪽 → 오른쪽
            nxt[:, :-1]  |= frontier[:, 1:]    # 오른쪽 → 왼쪽
            nxt[1:, 1:]  |= frontier[:-1, :-1]  # 대각
            nxt[1:, :-1] |= frontier[:-1, 1:]
            nxt[:-1, 1:] |= frontier[1:, :-1]
            nxt[:-1, :-1]|= frontier[1:, 1:]
            # 통행 가능 + 미방문만
            nxt &= passable & (field == -1)
            field[nxt] = step
            frontier = nxt
        return field

    # 골을 50px 격자에 스냅해 캐시 — objective_jitter로 유닛별로 ±20px 다른 골이
    # 모두 같은 거리장 공유 (각 유닛마다 BFS 재계산 방지)
    _GOAL_SNAP = 50

    def get_distance_field(self, goal: Tuple[float, float], unit_type) -> np.ndarray:
        """캐시된 거리장 반환. 골은 50px 격자 스냅으로 캐시 키 정규화."""
        if not hasattr(self, '_dist_cache'):
            self._dist_cache = {}
        snap = self._GOAL_SNAP
        gx = (int(goal[0]) // snap) * snap + snap // 2
        gy = (int(goal[1]) // snap) * snap + snap // 2
        key = (gx, gy, self._passability_group(unit_type))
        if key not in self._dist_cache:
            print(f"[Terrain] BFS 거리장 계산: goal=({gx},{gy}), group={key[2]} ...", flush=True)
            self._dist_cache[key] = self._compute_distance_field(gx, gy, key[2])
            n_reach = int((self._dist_cache[key] >= 0).sum())
            print(f"          → 도달 가능 셀 {n_reach:,}개", flush=True)
        return self._dist_cache[key]

    def get_path_direction(self, start: Tuple[float, float], goal: Tuple[float, float],
                            unit_type) -> Optional[Tuple[float, float]]:
        """start 셀에서 goal로 가는 다음 한 발의 방향 (정규화된 dx, dy).
        거리장에서 인접 8셀 중 거리가 가장 작은 곳을 선택.
        None 반환 = 경로 없음 (직선 폴백).
        """
        if self._passability_group(unit_type) == "air":
            return None   # 드론은 그냥 직선
        field = self.get_distance_field(goal, unit_type)
        x0, y0 = int(start[0]), int(start[1])
        H, W = field.shape
        if not (0 <= x0 < W and 0 <= y0 < H):
            return None
        cur = field[y0, x0]
        if cur < 0:
            # 출발지가 도달 불가 영역 (예: 강 안에서 갇힌 전차) — 직선으로
            return None
        best_d = cur
        best_dx, best_dy = 0, 0
        DIRS = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
        for dx, dy in DIRS:
            nx, ny = x0 + dx, y0 + dy
            if 0 <= nx < W and 0 <= ny < H:
                d = field[ny, nx]
                if 0 <= d < best_d:
                    best_d = d
                    best_dx, best_dy = dx, dy
        if best_dx == 0 and best_dy == 0:
            return None   # 이미 도착 (또는 주변에 더 가까운 셀 없음)
        norm = math.sqrt(best_dx * best_dx + best_dy * best_dy)
        return (best_dx / norm, best_dy / norm)
