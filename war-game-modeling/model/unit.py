from dataclasses import dataclass
from typing import List, Tuple, Set, Optional
from enum import Enum
from model.event import Event, EventType
import math
import random
import yaml

# Load config
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Constants
PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']
_UNITS_CFG = config['units']
_UNIT_OVERRIDES_CFG = config.get('unit_overrides', {})

# 원본 스케일 보존: 포병 이외는 detect/weapon range에 한 번 더 제수 적용 (config 기반)
_NON_ARTILLERY_RANGE_EXTRA_DIV = config['scaling']['range_extra_div_non_artillery']


def _get_unit_cfg(team: 'Team', unit_type: 'UnitType') -> dict:
    unit_cfg = dict(_UNITS_CFG[unit_type.name])
    team_overrides = _UNIT_OVERRIDES_CFG.get(team.name, {})
    unit_cfg.update(team_overrides.get(unit_type.name, {}))
    return unit_cfg

class Team(Enum):
    RED = "RED"
    BLUE = "BLUE"

class Status(Enum):
    # Rifle, AntiTank, CommandPost용 상태
    MINOR = "MINOR"         # 경상 (이동은 가능)
    SERIOUS = "SERIOUS"     # 중상 (이동, 사격 불가)
    CRITICAL = "CRITICAL"   # 중증 (이동, 사격 불가)
    FATAL = "FATAL"        # 사망 (이동, 사격 불가)

    # Tank, Artillery, Drone용 상태
    ALIVE = "ALIVE"        # 생존
    M_KILL = "M_KILL"       # 이동 불가
    F_KILL = "F_KILL"       # 사격 불가
    MF_KILL = "MF_KILL"     # 이동 및 사격 불가
    K_KILL = "K_KILL"       # 완전 파괴

class UnitType(Enum):
    RIFLE = "RIFLE"
    ANTI_TANK = "ANTI_TANK"
    TANK = "TANK"
    ARTILLERY = "ARTILLERY"
    DRONE = "DRONE"
    SELF_DEST_DRONE = "SELF_DEST_DRONE"
    COMMAND_POST = "COMMAND_POST"

class Action(Enum):
    FIRE = "FIRE"
    MOVE = "MOVE"
    STOP = "STOP"

@dataclass
class Unit:
    id: int
    team: Team
    unit_type: UnitType
    position: Tuple[int, int]
    status: Status = Status.ALIVE
    action: Action = Action.STOP
    target_list: Set[int] = None
    eligible_target_list: Set[int] = None
    objective: Optional[Tuple[float, float]] = None  # 이동 목표 지점
    target: Optional[int] = None  # 현재 사격 대상
    yaw: float = 0.0  # heading (radians), updated when position changes

    def get_fire_interval(self) -> float:
        """유닛 타입별 사격 소요시간 — config['units'][TYPE]['fire_interval']에서 읽음.
        [a,b]   → uniform(a,b)
        [a,b,c] → triangular(low=a, high=b, mode=c)
        null    → 무한대 (사격 안 함, 예: 드론)
        """
        fi = _get_unit_cfg(self.team, self.unit_type).get('fire_interval')
        if fi is None:
            return float('inf')
        if len(fi) == 2:
            return random.uniform(fi[0], fi[1])
        return random.triangular(fi[0], fi[1], fi[2])

    def __post_init__(self):
        if self.target_list is None:
            self.target_list = set()
        if self.eligible_target_list is None:
            self.eligible_target_list = set()
        
        # position이 tuple인지 확인
        if not isinstance(self.position, tuple):
            raise ValueError(f"Position must be a tuple, got {type(self.position)}")
        
        # position의 각 요소가 정수인지 확인
        if not all(isinstance(x, int) for x in self.position):
            raise ValueError(f"Position coordinates must be integers, got {self.position}")
        
        # position이 2차원 좌표인지 확인
        if len(self.position) != 2:
            raise ValueError(f"Position must be a 2D coordinate, got {self.position}")

        # config['units']에서 유닛 스펙 읽기 (포병만 m→px 직접 환산, 나머지는 한번 더 /5)
        unit_cfg = _get_unit_cfg(self.team, self.unit_type)
        extra_div = 1 if self.unit_type == UnitType.ARTILLERY else _NON_ARTILLERY_RANGE_EXTRA_DIV
        self.detect_range = unit_cfg['detect_range_m'] / extra_div / PIXEL_TO_METER_SCALE
        self.detectability = unit_cfg['detectability']
        self.weapon_range = unit_cfg['weapon_range_m'] / extra_div / PIXEL_TO_METER_SCALE

    def can_move(self) -> bool:
        """이동 가능 여부 확인"""
        if self.unit_type in [UnitType.RIFLE, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
            return self.status not in [Status.SERIOUS, Status.CRITICAL, Status.FATAL]
        else:
            return self.status in [Status.ALIVE, Status.M_KILL]

    def can_fire(self) -> bool:
        """사격 가능 여부 확인"""
        return self.status in [Status.MINOR,Status.ALIVE, Status.M_KILL]

    def update_position(self, new_position: Tuple[float, float]) -> None:
        """위치 업데이트 (이동 방향으로 yaw 갱신)"""
        dx = new_position[0] - self.position[0]
        dy = new_position[1] - self.position[1]
        if dx * dx + dy * dy > 1e-9:
            self.yaw = math.atan2(dy, dx)
        self.position = new_position

    def update_status(self, new_status: Status) -> None:
        """상태 업데이트"""
        self.status = new_status

    def update_action(self, action: Action):
        """유닛의 행동 상태 업데이트"""
        self.action = action

    def add_target(self, target_id: int) -> None:
        """타겟 추가"""
        self.target_list.add(target_id)

    def add_eligible_target(self, target_id: int) -> None:
        """사격 가능 타겟 추가"""
        self.eligible_target_list.add(target_id)

    def clear_targets(self):
        """탐지된 적 유닛 목록 초기화"""
        self.target_list.clear()

    def clear_eligible_targets(self):
        """사격 가능 타겟 목록 초기화"""
        self.eligible_target_list.clear()

    def update_objective(self, objective: Optional[Tuple[float, float]]) -> None:
        """이동 목표 지점 업데이트"""
        self.objective = objective

    def update_target(self, target_id: Optional[int]) -> None:
        """현재 사격 대상 업데이트"""
        self.target = target_id

    
