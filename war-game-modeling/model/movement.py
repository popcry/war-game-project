from typing import List, Tuple, Optional
from model.unit import Unit, Status, Team, Action, UnitType
from model.event import Event, EventType
from model.command import Command
from model.terrain import Terrain
from model.detect import Detect
from model.function import calculate_distance, calculate_point_distance
import random
import math
import heapq
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
        UnitType.COMMAND_POST: 5/5 * 1000/3600 /PIXEL_TO_METER_SCALE * 30,
        UnitType.WATCH_TOWER: 0,
        UnitType.SELF_DEST_DRONE: 25/5 * 1000/3600 /PIXEL_TO_METER_SCALE * 30 # 자폭 드론 속도는 일반 드론과 동일
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

    def _is_in_bounds(self, position: Tuple[int, int]) -> bool:
        x, y = position
        height, width = self.terrain.dem_data.shape
        return 0 <= x < width and 0 <= y < height

    def _is_tank_passable(self, position: Tuple[int, int]) -> bool:
        return (
            self._is_in_bounds(position)
            and self.terrain.get_terrain_type(position) == 'normal'
        )

    def _get_tank_neighbors(self, position: Tuple[int, int]) -> List[Tuple[Tuple[int, int], float]]:
        x, y = position
        neighbors = []
        directions = [
            (-1, 0), (1, 0), (0, -1), (0, 1),
            (-1, -1), (-1, 1), (1, -1), (1, 1)
        ]

        for dx, dy in directions:
            next_position = (x + dx, y + dy)
            if not self._is_tank_passable(next_position):
                continue

            if dx != 0 and dy != 0:
                if not (
                    self._is_tank_passable((x + dx, y))
                    and self._is_tank_passable((x, y + dy))
                ):
                    continue
                move_cost = math.sqrt(2)
            else:
                move_cost = 1.0

            neighbors.append((next_position, move_cost))

        return neighbors

    def _find_nearest_tank_passable(self, position: Tuple[int, int], max_radius: int = 100) -> Optional[Tuple[int, int]]:
        x, y = position
        if self._is_tank_passable((x, y)):
            return (x, y)

        for radius in range(1, max_radius + 1):
            candidates = []
            for dx in range(-radius, radius + 1):
                candidates.append((x + dx, y - radius))
                candidates.append((x + dx, y + radius))
            for dy in range(-radius + 1, radius):
                candidates.append((x - radius, y + dy))
                candidates.append((x + radius, y + dy))

            passable = [candidate for candidate in candidates if self._is_tank_passable(candidate)]
            if passable:
                return min(passable, key=lambda candidate: calculate_point_distance(position, candidate))

        return None

    def _find_tank_path(self, start: Tuple[int, int], goal: Tuple[int, int]) -> Optional[List[Tuple[int, int]]]:
        if not self._is_in_bounds(start):
            return None

        goal = self._find_nearest_tank_passable(goal)
        if goal is None:
            return None
        if start == goal:
            return [start]

        open_set = [(0.0, start)]
        came_from = {}
        g_score = {start: 0.0}
        closed = set()

        while open_set:
            _, current = heapq.heappop(open_set)
            if current in closed:
                continue
            if current == goal:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path

            closed.add(current)
            for neighbor, move_cost in self._get_tank_neighbors(current):
                if neighbor in closed:
                    continue

                tentative_g_score = g_score[current] + move_cost
                if tentative_g_score >= g_score.get(neighbor, float('inf')):
                    continue

                came_from[neighbor] = current
                g_score[neighbor] = tentative_g_score
                f_score = tentative_g_score + calculate_point_distance(neighbor, goal)
                heapq.heappush(open_set, (f_score, neighbor))

        return None

    def _calculate_tank_next_position(self, unit: Unit, speed: float) -> Optional[Tuple[float, float]]:
        if not unit.objective or speed <= 0:
            return None

        start = (int(round(unit.position[0])), int(round(unit.position[1])))
        goal = (int(round(unit.objective[0])), int(round(unit.objective[1])))
        path = self._find_tank_path(start, goal)
        if not path or len(path) == 1:
            return None

        remaining_distance = speed
        current_position = (float(unit.position[0]), float(unit.position[1]))

        for waypoint in path[1:]:
            waypoint_position = (float(waypoint[0]), float(waypoint[1]))
            segment_distance = calculate_point_distance(current_position, waypoint_position)
            if segment_distance == 0:
                current_position = waypoint_position
                continue

            if remaining_distance >= segment_distance:
                current_position = waypoint_position
                remaining_distance -= segment_distance
                continue

            ratio = remaining_distance / segment_distance
            next_position = (
                current_position[0] + (waypoint_position[0] - current_position[0]) * ratio,
                current_position[1] + (waypoint_position[1] - current_position[1]) * ratio
            )
            next_cell = (int(next_position[0]), int(next_position[1]))
            if self._is_tank_passable(next_cell):
                return next_position
            return waypoint_position

        return current_position

    def can_move(self, unit: Unit) -> bool:
        """이동 가능 여부 확인"""
        if unit.unit_type == UnitType.WATCH_TOWER:
            return False
        return unit.status in [Status.ALIVE, Status.F_KILL, Status.MINOR, Status.SERIOUS]

    def calculate_drone_objective(self, unit: Unit, command: Command, current_time: float) -> Tuple[float, float]:
        """드론의 목표 지점 계산"""
        if unit.unit_type not in [UnitType.DRONE, UnitType.SELF_DEST_DRONE]:
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
        if unit.unit_type == UnitType.DRONE or unit.unit_type == UnitType.SELF_DEST_DRONE:
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
            if unit.unit_type == UnitType.DRONE or unit.unit_type == UnitType.SELF_DEST_DRONE:
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

        if unit.unit_type == UnitType.TANK:
            speed = self.get_unit_speed(unit, unit.position)
            next_position = self._calculate_tank_next_position(unit, speed)
            if not next_position:
                unit.update_action(Action.STOP)
                return None

            return Event(
                event_type=EventType.MOVE,
                time=current_time + 1.0,
                source_id=unit.id,
                position=next_position
            )

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
