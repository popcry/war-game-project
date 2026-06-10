from typing import Dict, Optional

import pandas as pd
import yaml

from model.unit import UnitType, Status


with open('config.yaml', 'r', encoding='utf-8') as _f:
    _PROB_CFG = yaml.safe_load(_f)['probabilities']


_RANGE_POINTS = [
    (100.0, "100m Ph"),
    (500.0, "500m Ph"),
    (1500.0, "1,500m Ph"),
    (2500.0, "2,500m Ph"),
]

_TARGET_STATUS_BY_PROTECTION = {
    "ES": ["Prone", "Open", "All"],
    "EM": ["Stand", "Open", "All"],
    "DS": ["Defilade", "Trench", "All"],   # "Trench" 추가 — 참호 정지 보병 무적 버그 수정
    "DM": ["Trench", "Defilade", "All"],
}


def _build_table(name: str) -> pd.DataFrame:
    spec = _PROB_CFG[name]
    return pd.DataFrame(spec['rows'], columns=spec['columns'])


def _normalize_side(side: Optional[str]) -> Optional[str]:
    if side is None:
        return None
    value = str(side).strip()
    if not value:
        return None
    return value[:1].upper() + value[1:].lower()


def _parse_number(value, default: Optional[float] = None) -> Optional[float]:
    if pd.isna(value):
        return default
    text = str(value).strip()
    if not text or text == "-":
        return default
    number = ""
    for char in text:
        if char.isdigit() or char == ".":
            number += char
        elif number:
            break
    return float(number) if number else default


def _parse_probability(value) -> Optional[float]:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    if text.lower() == "carlton":
        return None
    return float(text)


def _target_status_candidates(protection_state: str) -> list:
    if protection_state in {"Open", "Defilade", "Stand", "Prone", "Trench", "All"}:
        return [protection_state, "All"]
    return _TARGET_STATUS_BY_PROTECTION.get(protection_state, ["All"])


def _damage_logic_target_type(target_type: UnitType) -> UnitType:
    if target_type == UnitType.ANTI_TANK:
        return UnitType.RIFLE
    return target_type


class ProbabilitySystem:
    damage_logics = _build_table('damage_logics')

    @classmethod
    def get_hit_probability(
        cls,
        attacker_type: UnitType,
        target_type: UnitType,
        distance: float,
        protection_state: str,
        side: Optional[str] = None,
    ) -> float:
        """Return Ph from config probabilities.damage_logics.

        distance is meters. Carlton rows return 0 here; artillery currently uses
        the existing impact-radius logic and Pk/h from get_kill_probability().
        """
        row = cls._find_damage_logic(attacker_type, target_type, protection_state, side)
        if row is None or not cls._is_in_range(row, distance):
            return 0.0

        points = [
            (range_m, probability)
            for range_m, column in _RANGE_POINTS
            if (probability := _parse_probability(row[column])) is not None
        ]
        if not points:
            return 0.0

        if distance <= points[0][0]:
            return points[0][1]
        if distance >= points[-1][0]:
            return points[-1][1]

        for (lower_range, lower_prob), (upper_range, upper_prob) in zip(points, points[1:]):
            if lower_range <= distance <= upper_range:
                return cls._linear_interpolate(
                    distance,
                    lower_range,
                    upper_range,
                    lower_prob,
                    upper_prob,
                )

        return 0.0

    @classmethod
    def get_kill_probability(
        cls,
        attacker_type: UnitType,
        target_type: UnitType,
        distance: float,
        protection_state: str,
        side: Optional[str] = None,
    ) -> Dict[Status, float]:
        """Return Pk/h from config probabilities.damage_logics."""
        row = cls._find_damage_logic(attacker_type, target_type, protection_state, side)
        if row is None:
            return {}
        if not cls._is_in_range(row, distance):
            return {}

        probability = _parse_probability(row["Pk/h"])
        if probability is None:
            return {}

        if target_type in [UnitType.RIFLE, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
            return {Status.FATAL: probability}
        return {Status.K_KILL: probability}

    @classmethod
    def is_in_damage_logic_range(
        cls,
        attacker_type: UnitType,
        target_type: UnitType,
        distance: float,
        protection_state: str,
        side: Optional[str] = None,
    ) -> bool:
        """Return whether this attack is inside the matching damage logic range."""
        row = cls._find_damage_logic(attacker_type, target_type, protection_state, side)
        if row is None:
            return False
        return cls._is_in_range(row, distance)

    @classmethod
    def get_effect_radius(
        cls,
        attacker_type: UnitType,
        target_type: UnitType,
        protection_state: str,
        side: Optional[str] = None,
    ) -> Optional[float]:
        """Return RL from damage_logics in meters when it is numeric."""
        row = cls._find_damage_logic(attacker_type, target_type, protection_state, side)
        if row is None or "RL" not in row:
            return None
        return _parse_number(row["RL"])

    @classmethod
    def _find_damage_logic(
        cls,
        attacker_type: UnitType,
        target_type: UnitType,
        protection_state: str,
        side: Optional[str] = None,
    ) -> Optional[pd.Series]:
        logic_target_type = _damage_logic_target_type(target_type)
        rows = cls.damage_logics[
            (cls.damage_logics["Attacker"] == attacker_type.name)
            & (cls.damage_logics["Target"] == logic_target_type.name)
        ]

        normalized_side = _normalize_side(side)
        if normalized_side is not None:
            side_rows = rows[rows["Side"] == normalized_side]
            if not side_rows.empty:
                rows = side_rows

        for target_status in _target_status_candidates(protection_state):
            status_rows = rows[rows["Target_Status"] == target_status]
            if not status_rows.empty:
                return status_rows.iloc[0]

        return None

    @classmethod
    def _is_in_range(cls, row: pd.Series, distance: float) -> bool:
        min_range = _parse_number(row["Min_range"], 0.0)
        max_range = _parse_number(row["Max_range"])
        if min_range is not None and distance < min_range:
            return False
        if max_range is not None and distance > max_range:
            return False
        return True

    @staticmethod
    def _linear_interpolate(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
        if x0 == x1:
            return y0
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
