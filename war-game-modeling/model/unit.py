from dataclasses import dataclass
from typing import List, Tuple, Set, Optional
from enum import Enum
from model.event import Event, EventType
import random
import yaml

# Load config
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Constants
PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']

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

    def get_fire_interval(self) -> float:
        """유닛 타입별 사격 소요시간 반환"""
        if self.unit_type == UnitType.ARTILLERY:
            return random.triangular(6.0, 20.0, 10.0)  # 105밀리견인포 지속사격 분당 3발(장전 20초), 최고 10발(장전 6초)
        elif self.unit_type == UnitType.TANK:
            return random.triangular(5.0, 10.0, 6.0)  # k-2전차 평균 분당 10발 (장전 6초)
        elif self.unit_type == UnitType.ANTI_TANK:
            return random.triangular(60.0, 180.0, 100.0)  # 현궁 급속사격 장전 1분, 정상사격 3분
        else:  # RIFLE, COMMAND_POST
            return random.uniform(2.0, 3.0)

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

        # 임시 DB (나중에 DB에서 가져올 예정)
        self.detect_range = {
            UnitType.RIFLE: 1000 / 5 / PIXEL_TO_METER_SCALE,
            UnitType.ANTI_TANK: 3000 / 5 / PIXEL_TO_METER_SCALE,
            UnitType.TANK: 3000 / 5 / PIXEL_TO_METER_SCALE,     
            UnitType.ARTILLERY: 1000 / 5 / PIXEL_TO_METER_SCALE,
            UnitType.DRONE: 500 / 5 / PIXEL_TO_METER_SCALE,    
            UnitType.COMMAND_POST: 1000 / 5 / PIXEL_TO_METER_SCALE
        }[self.unit_type]

        self.detectability = {
            UnitType.RIFLE: 0.8,
            UnitType.ANTI_TANK: 0.8,
            UnitType.TANK: 2.0,     
            UnitType.ARTILLERY: 2,
            UnitType.DRONE: 0,    
            UnitType.COMMAND_POST: 1.0
        }[self.unit_type]

        self.weapon_range = {
            UnitType.RIFLE: 400 / 5 / PIXEL_TO_METER_SCALE,      
            UnitType.ANTI_TANK: 3000 / 5 / PIXEL_TO_METER_SCALE,  
            UnitType.TANK: 3000 / 5 / PIXEL_TO_METER_SCALE,       
            UnitType.ARTILLERY: 11300 / 1 / PIXEL_TO_METER_SCALE,  
            UnitType.DRONE: 0,      
            UnitType.COMMAND_POST: 400 / 5 / PIXEL_TO_METER_SCALE 
        }[self.unit_type]

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
        """위치 업데이트"""
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

    
