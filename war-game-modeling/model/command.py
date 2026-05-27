from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
from model.unit import UnitType, Team, Unit, Status
from collections import deque
import yaml

with open('config.yaml', 'r') as f:
    _CFG = yaml.safe_load(f)
_PHASES_CFG = _CFG['phases']
_PHASE_TR_CFG = _CFG['phase_transitions']


def _parse_phase_cfg(team: 'Team', phase_key: str) -> dict:
    """config의 phases.<TEAM>.<phase_key> 항목을 (TAI, fire_priority dict, maneuver) 튜플로 변환."""
    raw = _PHASES_CFG[team.value][phase_key]
    tai = tuple(raw['TAI'])
    fp = {UnitType[name]: val for name, val in raw['fire_priority'].items()}
    mo = raw['maneuver_objective']
    if mo is not None:
        mo = [tuple(p) for p in mo]
    return {'TAI': tai, 'fire_priority': fp, 'maneuver_objective': mo}

class LogHandler:
    _instance = None
    _logs = deque(maxlen=100)  # 최근 100개의 로그만 유지
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LogHandler, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def add_log(cls, message: str):
        cls._logs.append(message)
    
    @classmethod
    def get_logs(cls):
        return list(cls._logs)

class Phase(Enum):
    Deep_fires = 1
    Degrade_enemy_forces = 2
    CLOSE_COMBAT = 3

@dataclass
class Command:
    team: Team
    phase: Phase = Phase.Deep_fires
    TAI: Tuple[float, float] = None  # Drone reconnaissance area
    fire_priority: Dict[UnitType, int] = None  # 유닛 타입별 우선순위
    maneuver_objective: List[Tuple[float, float]] = None  # 목표 지점들
    next_phase: Phase = None  # 다음 작전단계

    def __post_init__(self):
        if self.fire_priority is None:
            self.fire_priority = {
                UnitType.RIFLE: 5,
                UnitType.ANTI_TANK: 4,
                UnitType.TANK: 3,
                UnitType.ARTILLERY: 1,
                UnitType.COMMAND_POST: 2
            }
        self.next_phase = self.phase  # 초기값은 현재 단계로 설정

    @classmethod
    def create_phase_1_command(cls, team: Team):
        spec = _parse_phase_cfg(team, 'phase_1')
        return cls(team=team, phase=Phase.Deep_fires, **spec)

    @classmethod
    def create_phase_2_command(cls, team: Team):
        spec = _parse_phase_cfg(team, 'phase_2')
        return cls(team=team, phase=Phase.Degrade_enemy_forces, **spec)

    @classmethod
    def create_phase_3_command(cls, team: Team):
        spec = _parse_phase_cfg(team, 'phase_3')
        return cls(team=team, phase=Phase.CLOSE_COMBAT, **spec)

    def _log_phase_change(self) -> None:
        """작전단계 변경 시 로그를 남김"""
        log_message = f"{self.team.value} 팀 작전단계를 {self.phase.name}로 변경"
        LogHandler.add_log(log_message)

    def evaluate_situation(self, command_post: Unit, all_units: List[Unit]) -> None:
        """지휘소의 상황을 평가하고 작전단계를 업데이트
        
        Args:
            command_post: 지휘소 유닛
            all_units: 모든 유닛 리스트
        """
        if not command_post:
            return
            
        # 1. 결심조건 평가
        Decision_criteria = self._evaluate_decision_criteria(command_post, all_units)
        
        # 2. 작전단계 변경
        if Decision_criteria:
            self._update_phase()

    def _evaluate_decision_criteria(self, command_post: Unit, all_units: List[Unit]) -> bool:
        """결심조건을 평가하여 작전단계 변경 여부를 결정
        
        Returns:
            bool: 작전단계 변경이 필요한지 여부
        """
        # 지휘소가 파괴되었으면 CLOSE_COMBAT 단계로
        if command_post.status not in [Status.ALIVE, Status.MINOR, Status.M_KILL]:
            self.next_phase = Phase.CLOSE_COMBAT
            return True
            
        # 지휘소가 살아있거나 경미한 피해를 입은 경우
        if command_post.status in [Status.ALIVE, Status.MINOR, Status.M_KILL]:
            functional = [Status.ALIVE, Status.MINOR, Status.M_KILL]

            # 아군 포병 N대 이상 파괴되면 CLOSE_COMBAT (임계값 config)
            destroyed_friendly_artillery = sum(
                1 for unit in all_units
                if unit.team == self.team
                and unit.unit_type == UnitType.ARTILLERY
                and unit.status not in functional
            )
            if destroyed_friendly_artillery >= _PHASE_TR_CFG['friendly_artillery_lost_to_close_combat']:
                self.next_phase = Phase.CLOSE_COMBAT
                return True

            if self.phase == Phase.Deep_fires:
                # 적 포병 N대 이상 파괴되면 phase_2
                destroyed_artillery = sum(
                    1 for unit in all_units
                    if unit.team != self.team
                    and unit.unit_type == UnitType.ARTILLERY
                    and unit.status not in functional
                )
                if destroyed_artillery >= _PHASE_TR_CFG['enemy_artillery_destroyed_to_phase_2']:
                    self.next_phase = Phase.Degrade_enemy_forces
                    return True

            elif self.phase == Phase.Degrade_enemy_forces:
                # 적 전차 N대 이상 파괴되면 CLOSE_COMBAT
                destroyed_enemy_tanks = sum(
                    1 for unit in all_units
                    if unit.team != self.team
                    and unit.unit_type == UnitType.TANK
                    and unit.status not in functional
                )
                if destroyed_enemy_tanks >= _PHASE_TR_CFG['enemy_tanks_destroyed_to_close_combat']:
                    self.next_phase = Phase.CLOSE_COMBAT
                    return True

        return False

    def _update_phase(self) -> None:
        """작전단계를 변경하고 관련 명령을 업데이트"""
        if self.next_phase == Phase.CLOSE_COMBAT:
            new_command = Command.create_phase_3_command(self.team)
        elif self.next_phase == Phase.Degrade_enemy_forces:
            new_command = Command.create_phase_2_command(self.team)
        else:
            return

        # 명령 업데이트
        self.phase = new_command.phase
        self.TAI = new_command.TAI
        self.fire_priority = new_command.fire_priority
        self.maneuver_objective = new_command.maneuver_objective
        self._log_phase_change()

