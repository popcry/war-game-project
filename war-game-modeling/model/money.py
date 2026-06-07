from typing import Dict

from model.unit import Status, Team, Unit, UnitType


DEFAULT_FIRE_COST = {
    UnitType.RIFLE: 10.0,
    UnitType.ANTI_TANK: 200.0,
    UnitType.TANK: 300.0,
    UnitType.ARTILLERY: 500.0,
    UnitType.DRONE: 0.0,
    UnitType.SELF_DEST_DRONE: 1000.0,
    UnitType.COMMAND_POST: 0.0,
}

DEFAULT_UNIT_VALUE = {
    UnitType.RIFLE: 100.0,
    UnitType.ANTI_TANK: 800.0,
    UnitType.TANK: 5000.0,
    UnitType.ARTILLERY: 3000.0,
    UnitType.DRONE: 1500.0,
    UnitType.SELF_DEST_DRONE: 2000.0,
    UnitType.COMMAND_POST: 10000.0,
}

DEFAULT_DAMAGE_RATIO = {
    Status.ALIVE: 0.0,
    Status.MINOR: 0.1,
    Status.SERIOUS: 0.5,
    Status.CRITICAL: 0.8,
    Status.FATAL: 1.0,
    Status.M_KILL: 0.4,
    Status.F_KILL: 0.4,
    Status.MF_KILL: 0.7,
    Status.K_KILL: 1.0,
}


class MoneyTracker:
    def __init__(self, money_config: Dict = None, platform_overrides: Dict = None):
        money_config = money_config or {}
        self.platform_overrides = platform_overrides or {}
        self.fire_cost_by_type = self._load_unit_type_values(
            DEFAULT_FIRE_COST,
            money_config.get("fire_cost", {}),
        )
        self.unit_value_by_type = self._load_unit_type_values(
            DEFAULT_UNIT_VALUE,
            money_config.get("unit_value", {}),
        )
        self.damage_ratio_by_status = self._load_status_values(
            DEFAULT_DAMAGE_RATIO,
            money_config.get("damage_ratio", {}),
        )
        self.fire_cost = {team: 0.0 for team in Team}
        self.damage_cost = {team: 0.0 for team in Team}

    def _load_unit_type_values(self, defaults: Dict[UnitType, float], overrides: Dict) -> Dict[UnitType, float]:
        values = dict(defaults)
        for key, value in overrides.items():
            values[UnitType[key]] = float(value)
        return values

    def _load_status_values(self, defaults: Dict[Status, float], overrides: Dict) -> Dict[Status, float]:
        values = dict(defaults)
        for key, value in overrides.items():
            values[Status[key]] = float(value)
        return values

    def _get_platform_override(self, team: Team, unit_type: UnitType, key: str):
        value = (
            self.platform_overrides
            .get(team.name, {})
            .get(unit_type.name, {})
            .get(key)
        )
        return None if value is None else float(value)

    def record_fire(self, attacker: Unit) -> None:
        cost = self._get_platform_override(attacker.team, attacker.unit_type, "fire_cost")
        if cost is None:
            cost = self.fire_cost_by_type.get(attacker.unit_type, 0.0)
        self.fire_cost[attacker.team] += cost

    def record_damage(self, unit: Unit, old_status: Status, new_status: Status) -> None:
        old_ratio = self.damage_ratio_by_status.get(old_status, 0.0)
        new_ratio = self.damage_ratio_by_status.get(new_status, 0.0)
        ratio_delta = max(0.0, new_ratio - old_ratio)
        if ratio_delta == 0.0:
            return

        unit_value = self._get_platform_override(unit.team, unit.unit_type, "unit_value")
        if unit_value is None:
            unit_value = self.unit_value_by_type.get(unit.unit_type, 0.0)
        self.damage_cost[unit.team] += unit_value * ratio_delta

    def get_team_summary(self, team: Team) -> Dict[str, float]:
        fire_cost = self.fire_cost[team]
        damage_cost = self.damage_cost[team]
        return {
            "fire": fire_cost,
            "damage": damage_cost,
            "total": fire_cost + damage_cost,
        }

    def format_team_summary(self, team: Team) -> str:
        summary = self.get_team_summary(team)
        return (
            f"{team.value} Fire: {summary['fire']:,.0f} | "
            f"Damage: {summary['damage']:,.0f} | "
            f"Total: {summary['total']:,.0f}"
        )
