from typing import List, Tuple
from model.unit import Unit, Status, UnitType, Team, Action
from model.terrain import Terrain
from model.function import calculate_distance
import random
import yaml

with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']
_DET_CFG = config['detection']

FUNCTIONAL_STATUSES = {Status.ALIVE, Status.M_KILL, Status.MINOR}

# Slide-based observer profile.
# visual/equipment probabilities are one-glimpse probabilities under best conditions.
# attempts_per_minute is N in the source table.
OBSERVER_PROFILES = {
    UnitType.RIFLE: {
        "visual_glimpse_prob": 0.18,
        "equipment_glimpse_prob": 0.30,
        "visual_range_m": 800.0,
        "equipment_range_m": 2500.0,
        "attempts_per_minute": 4,
    },
    UnitType.ANTI_TANK: {
        "visual_glimpse_prob": 0.18,
        "equipment_glimpse_prob": 0.40,
        "visual_range_m": 800.0,
        "equipment_range_m": 3000.0,
        "attempts_per_minute": 4,
    },
    UnitType.TANK: {
        "visual_glimpse_prob": 0.22,
        "equipment_glimpse_prob": 0.40,
        "visual_range_m": 2500.0,
        "equipment_range_m": 6000.0,
        "attempts_per_minute": 5,
    },
    UnitType.ARTILLERY: {
        "visual_glimpse_prob": 0.06,
        "equipment_glimpse_prob": 0.12,
        "visual_range_m": 2000.0,
        "equipment_range_m": 6000.0,
        "attempts_per_minute": 3,
    },
    UnitType.DRONE: {
        "visual_glimpse_prob": 0.00,
        "equipment_glimpse_prob": 0.50,
        "visual_range_m": 0.0,
        "equipment_range_m": 5000.0,
        "attempts_per_minute": 6,
    },
    UnitType.SELF_DEST_DRONE: {
        "visual_glimpse_prob": 0.00,
        "equipment_glimpse_prob": 0.35,
        "visual_range_m": 0.0,
        "equipment_range_m": 1500.0,
        "attempts_per_minute": 5,
    },
    UnitType.COMMAND_POST: {
        "visual_glimpse_prob": 0.18,
        "equipment_glimpse_prob": 0.30,
        "visual_range_m": 800.0,
        "equipment_range_m": 2500.0,
        "attempts_per_minute": 4,
    },
}

OBSERVER_TERRAIN_CORRECTION = {
    "normal": 1.00,
    "air": 1.00,
    "road": 1.00,
    "mountain": 1.00,
    "forest": 0.60,
    "trench": 0.70,
    "urban": 0.70,
    "river": 1.00,
}

TARGET_TERRAIN_CORRECTION = {
    "normal": 1.00,
    "air": 1.00,
    "road": 1.00,
    "mountain": 0.75,
    "forest": 0.50,
    "trench": 0.45,
    "urban": 0.50,
    "river": 1.00,
}

TARGET_SIZE_CORRECTION = {
    UnitType.TANK: 1.00,
    UnitType.ARTILLERY: 1.00,
    UnitType.COMMAND_POST: 0.80,
    UnitType.RIFLE: 0.60,
    UnitType.ANTI_TANK: 0.60,
    UnitType.DRONE: 0.60,
    UnitType.SELF_DEST_DRONE: 0.35,
}

CONCEALED_TERRAINS = {"trench", "forest", "urban"}


# 팀별 유닛 타입별 오버라이드 — OBSERVER_PROFILES 기본값을 팀 단위로 덮어씀
# 예: BLUE CP만 30km/50km 광역 탐지(통합 ISR 본부 개념)
TEAM_OBSERVER_OVERRIDES = {
    "BLUE": {
        UnitType.COMMAND_POST: {"equipment_range_m": 50000.0},
    },
}


def _get_profile(observer):
    """팀 오버라이드를 적용한 OBSERVER_PROFILE 반환."""
    base = OBSERVER_PROFILES[observer.unit_type]
    override = TEAM_OBSERVER_OVERRIDES.get(observer.team.value, {}).get(observer.unit_type)
    if override is None:
        return base
    return {**base, **override}


class Detect:
    def __init__(self):
        self.terrain = Terrain()
        self.LOS_CHECK_INTERVAL_PX = _DET_CFG['los_check_interval_px']

    def _unit_elevation_m(self, unit: Unit) -> float:
        ground_m = self.terrain.get_elevation_m((int(unit.position[0]), int(unit.position[1])))
        if unit.unit_type in [UnitType.DRONE, UnitType.SELF_DEST_DRONE]:
            return ground_m + float(config['simulation']['drone_elevation'])
        return ground_m

    def check_los(self, observer: Unit, target: Unit) -> bool:
        """Return whether terrain blocks the line of sight.

        LOS is blocked if an intermediate cell is at least 50m above the
        straight sight line between observer and target.
        """
        x1, y1 = observer.position
        x2, y2 = target.position
        observer_elevation = self._unit_elevation_m(observer)
        target_elevation = self._unit_elevation_m(target)
        distance = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        num_checks = int(distance / self.LOS_CHECK_INTERVAL_PX)

        for i in range(1, num_checks):
            ratio = i / num_checks
            x = x1 + (x2 - x1) * ratio
            y = y1 + (y2 - y1) * ratio
            sightline_elevation = observer_elevation + (target_elevation - observer_elevation) * ratio
            current_elevation = self.terrain.get_elevation_m((int(x), int(y)))
            if current_elevation >= sightline_elevation + 50.0:
                return False
        return True

    def _observer_terrain(self, observer: Unit) -> str:
        if observer.unit_type in [UnitType.DRONE, UnitType.SELF_DEST_DRONE]:
            return "air"
        return self.terrain.get_terrain_type((int(observer.position[0]), int(observer.position[1])))

    def _range_correction(self, distance_m: float, max_range_m: float) -> float:
        if max_range_m <= 0:
            return 0.0
        ratio = distance_m / max_range_m
        if ratio <= 0.5:
            return 1.00
        if ratio <= 0.8:
            return 0.70
        if ratio <= 1.0:
            return 0.40
        return 0.0

    def _glimpse_mode(self, profile: dict, distance_m: float) -> Tuple[float, float]:
        visual_range = profile["visual_range_m"]
        equipment_range = profile["equipment_range_m"]
        visual_probability = profile["visual_glimpse_prob"]
        equipment_probability = profile["equipment_glimpse_prob"]

        if visual_range > 0 and distance_m <= visual_range:
            combined_probability = 1.0 - ((1.0 - visual_probability) * (1.0 - equipment_probability))
            return combined_probability, visual_range
        if equipment_range > 0 and distance_m <= equipment_range:
            return equipment_probability, equipment_range
        return 0.0, equipment_range

    def _height_correction(self, observer: Unit, target: Unit) -> float:
        delta_h = self._unit_elevation_m(observer) - self._unit_elevation_m(target)
        if delta_h >= 0:
            return 1.00
        if delta_h >= -50.0:
            return 0.85
        return 0.65

    def _posture_correction(self, target: Unit, target_terrain: str) -> float:
        if target.action == Action.MOVE:
            return 0.90
        if target_terrain in CONCEALED_TERRAINS:
            return 0.40
        if target.action == Action.FIRE:
            return 1.00
        return 0.70

    def calculate_glimpse_probability(self, observer: Unit, target: Unit) -> float:
        profile = _get_profile(observer)
        distance_m = calculate_distance(observer, target) * PIXEL_TO_METER_SCALE
        base_probability, max_range_m = self._glimpse_mode(profile, distance_m)
        if base_probability <= 0.0:
            return 0.0

        target_terrain = self.terrain.get_terrain_type((int(target.position[0]), int(target.position[1])))
        observer_terrain = self._observer_terrain(observer)
        probability = (
            base_probability
            * OBSERVER_TERRAIN_CORRECTION.get(observer_terrain, 1.0)
            * TARGET_TERRAIN_CORRECTION.get(target_terrain, 1.0)
            * TARGET_SIZE_CORRECTION.get(target.unit_type, 0.60)
            * self._posture_correction(target, target_terrain)
            * self._range_correction(distance_m, max_range_m)
            * self._height_correction(observer, target)
        )
        return max(0.0, min(1.0, probability))

    def detect_target(self, observer: Unit, target: Unit, detection_interval_s: float = 1.0) -> bool:
        """Detect a target using glimpse probability and interval-scaled attempts."""
        if target.status not in FUNCTIONAL_STATUSES:
            return False
        profile = _get_profile(observer)
        distance_m = calculate_distance(observer, target) * PIXEL_TO_METER_SCALE
        if distance_m > profile["equipment_range_m"]:
            return False
        if not self.check_los(observer, target):
            return False

        glimpse_probability = self.calculate_glimpse_probability(observer, target)
        attempts = profile["attempts_per_minute"] * max(0.0, detection_interval_s) / 60.0
        detection_probability = 1.0 - ((1.0 - glimpse_probability) ** attempts)
        return random.random() <= detection_probability

    def share_info(self, team: Team, all_units: List[Unit]) -> None:
        """Share target information through command posts or drones."""
        command_post = next((u for u in all_units
                           if u.team == team
                           and u.unit_type == UnitType.COMMAND_POST), None)

        if command_post and command_post.status in FUNCTIONAL_STATUSES:
            shared_targets = set()
            for unit in all_units:
                if unit.team == team:
                    shared_targets.update(unit.target_list)

            for unit in all_units:
                if unit.team == team:
                    unit.target_list.update(shared_targets)
        else:
            drone_targets = set()
            for unit in all_units:
                if unit.team == team and unit.unit_type in [UnitType.DRONE, UnitType.SELF_DEST_DRONE]:
                    drone_targets.update(unit.target_list)

            for unit in all_units:
                if unit.team == team and unit.unit_type == UnitType.ARTILLERY:
                    unit.target_list.update(drone_targets)

    def update_detection(self, observer: Unit, all_units: List[Unit], detection_interval_s: float = 1.0):
        """Update the observer's detected enemy target list."""
        for target in all_units:
            if target.team != observer.team and target.status in FUNCTIONAL_STATUSES:
                if self.detect_target(observer, target, detection_interval_s):
                    observer.add_target(target.id)
