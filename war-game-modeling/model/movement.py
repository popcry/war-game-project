from typing import List, Tuple, Optional
from model.unit import Unit, Status, Team, Action, UnitType
from model.event import Event, EventType
from model.command import Command
from model.terrain import Terrain
from model.detect import Detect
from model.function import calculate_distance, calculate_point_distance
import random
import math
import yaml 

with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']

class Movement:
    # 상수 정의
    MIN_DISTANCE_TO_OBJECTIVE = 50.0 / PIXEL_TO_METER_SCALE  # 목표 지점에 도달했다고 판단하는 최소 거리 (미터를 픽셀로 변환)
    UNIT_SPEEDS = {  # 유닛 타입별 이동 속도 (픽셀/초)
        UnitType.RIFLE: 7/5 * 1000/3600 /PIXEL_TO_METER_SCALE * 30,
        UnitType.ANTI_TANK: 5/5 * 1000/3600 /PIXEL_TO_METER_SCALE * 30,
        UnitType.TANK: 13/5 * 1000/3600 /PIXEL_TO_METER_SCALE * 30,
        UnitType.ARTILLERY: 0 * 1000/3600 /PIXEL_TO_METER_SCALE * 30,
        UnitType.DRONE: 25/5 * 1000/3600 /PIXEL_TO_METER_SCALE * 30,
        UnitType.COMMAND_POST: 5/5 * 1000/3600 /PIXEL_TO_METER_SCALE * 30
    }
     
    # 드론 탐지 패턴 정의
    DRONE_PATTERN = [
        (1, 1), (1, 2), (1, 3),
        (2, 3), (2, 2), (2, 1),
        (3, 1), (3, 2), (3, 3)
    ]
    DRONE_OBJECTIVE_CHANGE_TIME = 60.0  # 목표 지점 변경 주기 (초)
    DRONE_GRID_SIZE = 250 / PIXEL_TO_METER_SCALE  # 방안의 크기 (미터를 픽셀로 변환)

    def __init__(self):
        self.terrain = Terrain()
        self.detect = Detect()
        self.drone_positions = {}  # 드론의 현재 탐지 패턴 위치 저장
        self.drone_last_objective_change = {}  # 드론의 마지막 목표 지점 변경 시간 저장

    def get_unit_speed(self, unit: Unit, position: Tuple[float, float]) -> float:
        """유닛의 이동 속도 반환 (지형 영향 포함)"""
        base_speed = self.UNIT_SPEEDS.get(unit.unit_type, 0.0)  # m/s
        decay_rate = self.terrain.get_terrain_decay_rate(unit, (int(position[0]), int(position[1])))
        return base_speed * decay_rate

    def can_move(self, unit: Unit) -> bool:
        """이동 가능 여부 확인"""
        return unit.status in [Status.ALIVE, Status.F_KILL, Status.MINOR, Status.SERIOUS]

    def calculate_drone_objective(self, unit: Unit, command: Command, current_time: float) -> Tuple[float, float]:
        """드론의 목표 지점 계산"""
        if unit.unit_type != UnitType.DRONE:
            return None

        # TAI 위치
        tai = command.TAI
        if not tai:
            return None

        # 마지막 목표 지점 변경 시간 확인
        last_change = self.drone_last_objective_change.get(unit.id, 0.0)
        
        # 30초가 지났거나 처음 실행되는 경우에만 목표 지점 변경
        if current_time - last_change >= self.DRONE_OBJECTIVE_CHANGE_TIME:
            # 현재 드론의 패턴 위치 가져오기
            current_pattern = self.drone_positions.get(unit.id, 0)
            
            # 다음 패턴 위치 계산
            next_pattern = (current_pattern + 1) % len(self.DRONE_PATTERN)
            self.drone_positions[unit.id] = next_pattern
            
            # 마지막 변경 시간 업데이트
            self.drone_last_objective_change[unit.id] = current_time
        else:
            # 현재 패턴 위치 유지
            current_pattern = self.drone_positions.get(unit.id, 0)
        
        # 패턴의 그리드 위치
        grid_x, grid_y = self.DRONE_PATTERN[current_pattern]
        
        # TAI를 중심으로 한 3x3 그리드의 시작점 계산
        start_x = tai[0] - self.DRONE_GRID_SIZE
        start_y = tai[1] - self.DRONE_GRID_SIZE
        
        # 해당 방안의 중심점 계산
        center_x = start_x + (grid_x - 0.5) * self.DRONE_GRID_SIZE
        center_y = start_y + (grid_y - 0.5) * self.DRONE_GRID_SIZE
        
        
        return (center_x, center_y)

    def get_objective(self, unit: Unit, command: Command, current_time: float) -> Optional[Tuple[float, float]]:
        """유닛 타입에 따른 목적지 반환"""
        if unit.unit_type == UnitType.DRONE:
            return self.calculate_drone_objective(unit, command, current_time)
        elif unit.unit_type in [UnitType.RIFLE, UnitType.TANK, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
            if command.maneuver_objective and len(command.maneuver_objective) > 0:
                # maneuver_objective는 리스트이므로 첫 번째 목표 지점을 사용
                base_objective = command.maneuver_objective[0]
                # 2차원 좌표에 랜덤 오차를 한 번에 더함
                # 목적지가 다 겹칠 수 있으니, -100~+100 uniform dist 적용해서 더해서 좀 흐트러지게 설정.
                return tuple(x + random.uniform(-100, 100) for x in base_objective)
        return None

    def move(self, unit: Unit, command: Command, current_time: float, all_units: List[Unit]) -> Optional[Event]:
        """유닛 이동 실행
        1. objective 방향으로 1초 후의 new position 계산
        3. FEL에 move event 예약 (1초 후 new position으로 이동)
        3. action을 move로 변경
        """
        if not self.can_move(unit):
            unit.update_action(Action.STOP)
            return None

        # 목표 지점 가져오기
        objective = self.get_objective(unit, command, current_time)
        if not objective:
            unit.update_action(Action.STOP)
            unit.update_objective(None)  # 목표 지점 초기화
            return None

        # 목표 지점 업데이트 및 action을 MOVE로 변경
        unit.update_objective(objective)
        unit.update_action(Action.MOVE)

        # 목표 지점까지의 방향 벡터 계산
        dx = unit.objective[0] - unit.position[0]
        dy = unit.objective[1] - unit.position[1]
        distance = calculate_point_distance(unit.position, unit.objective)

        # 목표 지점에 도달했는지 확인
        if distance < self.MIN_DISTANCE_TO_OBJECTIVE:
            if unit.unit_type == UnitType.DRONE:
                # 드론의 경우 다음 패턴으로 즉시 이동
                current_pattern = self.drone_positions.get(unit.id, 0)
                next_pattern = (current_pattern + 1) % len(self.DRONE_PATTERN)
                self.drone_positions[unit.id] = next_pattern
                self.drone_last_objective_change[unit.id] = current_time
                
                # 새로운 목표 지점 계산
                new_objective = self.calculate_drone_objective(unit, command, current_time)
                if new_objective:
                    unit.update_objective(new_objective)
                    # 새로운 목표 지점으로의 이동 이벤트 생성
                    dx = new_objective[0] - unit.position[0]
                    dy = new_objective[1] - unit.position[1]
                    distance = calculate_point_distance(unit.position, new_objective)
                    if distance > 0:
                        dx /= distance
                        dy /= distance
                    speed = self.get_unit_speed(unit, unit.position)
                    next_x = unit.position[0] + dx * speed * 1 #time interval (simulation.py 에서 sim_speed와 같은 수치로 해야함함)
                    next_y = unit.position[1] + dy * speed * 1 #time interval (simulation.py 에서 sim_speed와 같은 수치로 해야함함)
                    return Event(
                        event_type=EventType.MOVE,
                        time=current_time + 1.0, #time interval
                        source_id=unit.id,
                        position=(next_x, next_y)
                    )
            else:
                # 다른 유닛들은 기존대로 처리
                unit.update_action(Action.STOP)
                unit.update_objective(None)
                return None

        # 정규화된 방향 벡터
        if distance > 0:
            dx /= distance
            dy /= distance

        # 다음 위치 계산 (지형 영향 포함)
        speed = self.get_unit_speed(unit, unit.position)
        next_x = unit.position[0] + dx * speed* 1 #time interval (simulation.py 에서 sim_speed와 같은 수치로 해야함함)
        next_y = unit.position[1] + dy * speed* 1 #time interval (simulation.py 에서 sim_speed와 같은 수치로 해야함함)

        # 이동 이벤트 생성
        return Event(
            event_type=EventType.MOVE,
            time=current_time + 1.0, #time interval (simulation.py 에서 sim_speed와 같은 수치로 해야함함)
            source_id=unit.id,
            position=(next_x, next_y)
        )
