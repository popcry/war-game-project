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

with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']
MAP_WIDTH = config['simulation']['map_width_px']
MAP_HEIGHT = config['simulation']['map_height_px']
_MOV_CFG = config['movement']
_DRONE_CFG = config['drone']
# config의 초 단위 시간을 tick으로 환산하기 위한 상수
_SECONDS_PER_TICK = float(config['simulation'].get('seconds_per_tick', 1.0))
_UNITS_CFG = config['units']
_PLATFORM_OVERRIDES = config.get('platform_overrides', {})
_SCALING = config['scaling']
_SPEED_DIV = _SCALING['speed_scale_divisor']
_SPEED_TMUL = _SCALING['speed_time_multiplier']

# kmh → px/s 변환식 (계수 config 기반): kmh /div *1000/3600 /pixel_to_meter_scale *tmul
def _kmh_to_pxps(kmh: float) -> float:
    return kmh / _SPEED_DIV * 1000 / 3600 / PIXEL_TO_METER_SCALE * _SPEED_TMUL


def _get_platform_override(team: Team, unit_type: UnitType, key: str):
    return _PLATFORM_OVERRIDES.get(team.name, {}).get(unit_type.name, {}).get(key)


class Movement:
    # 유닛별 이동 속도 (px/s) — config['units'][TYPE]['speed_kmh']에서 변환
    UNIT_SPEEDS = {
        UnitType[name]: _kmh_to_pxps(spec['speed_kmh'])
        for name, spec in _UNITS_CFG.items()
    }

    # 목표 지점 도달 판정 거리 (m → px)
    MIN_DISTANCE_TO_OBJECTIVE = _MOV_CFG['min_distance_to_objective_m'] / PIXEL_TO_METER_SCALE

    # maneuver_objective에 더하는 ±랜덤 분산 (px)
    _OBJECTIVE_JITTER_PX = _MOV_CFG['objective_jitter_px']

    # 드론 탐지 패턴 (config 기반) — TAI 중심 3×3 격자 순회 순서
    DRONE_PATTERN = [tuple(p) for p in _DRONE_CFG['pattern']]
    # config 'pattern_change_time_s' (초) → tick으로 환산
    DRONE_OBJECTIVE_CHANGE_TIME = _DRONE_CFG['pattern_change_time_s'] / _SECONDS_PER_TICK
    DRONE_GRID_SIZE = _DRONE_CFG['grid_cell_size_m'] / PIXEL_TO_METER_SCALE

    def __init__(self):
        self.terrain = Terrain()
        self.detect = Detect()
        self.drone_positions = {}  # 드론의 현재 탐지 패턴 위치 저장
        self.drone_last_objective_change = {}  # 드론의 마지막 목표 지점 변경 시간 저장
        self.drone_orbit_targets = {}  # 드론별 마지막 선회 표적 위치 저장

    def _initial_drone_pattern(self, unit: Unit) -> int:
        if not self.DRONE_PATTERN:
            return 0
        return unit.id % len(self.DRONE_PATTERN)

    # 차단 시 우회: 좁은 각부터 넓은 각까지, 양쪽으로 — 벽을 따라 옆으로 미끄러지듯 전진
    _BYPASS_ANGLES = [math.radians(a) for a in
                      (30, -30, 45, -45, 60, -60, 90, -90, 120, -120, 150, -150)]
    # 우회 실패 시 보폭을 줄여 좁은 틈으로 들어가도록 재시도
    _STEP_FRACTIONS = [1.0, 0.5, 0.25]

    def _try_passable_step(self, unit: Unit, dx: float, dy: float, speed: float, time_step: float):
        """(dx,dy) 정규화 방향에서 직진/우회를 시도.
        - 직진 → ±30/45/60/90/120/150° 회전 순으로 검사
        - 각도가 모두 막히면 보폭을 1.0/0.5/0.25배로 줄여 재시도 (좁은 틈 통과)
        반환: (next_x, next_y) 또는 None (모두 막힘).
        """
        cur = unit.position
        full_step = speed * time_step

        # 1) 직진 (full step 우선)
        for frac in self._STEP_FRACTIONS:
            step = full_step * frac
            nx = cur[0] + dx * step
            ny = cur[1] + dy * step
            if self.terrain.is_passable_path(cur, (nx, ny), unit.unit_type):
                return (nx, ny)
            # 2) 우회 (±30 ~ ±150)
            for a in self._BYPASS_ANGLES:
                ca, sa = math.cos(a), math.sin(a)
                rdx = dx * ca - dy * sa
                rdy = dx * sa + dy * ca
                nx = cur[0] + rdx * step
                ny = cur[1] + rdy * step
                if self.terrain.is_passable_path(cur, (nx, ny), unit.unit_type):
                    return (nx, ny)
        return None

    def calculate_drone_orbit_objective(self, unit: Unit, current_time: float,
                                        all_units: List[Unit]) -> Optional[Tuple[float, float]]:
        candidates = []
        for target_id in unit.target_list:
            target = next((u for u in all_units if u.id == target_id), None)
            if target:
                candidates.append(target)

        if candidates:
            target = min(candidates, key=lambda t: calculate_point_distance(unit.position, t.position))
            orbit_center = target.position
            self.drone_orbit_targets[unit.id] = orbit_center
        else:
            orbit_center = self.drone_orbit_targets.get(unit.id)
            if orbit_center is None:
                return None

        orbit_radius = self.DRONE_GRID_SIZE
        orbit_period = max(1.0, self.DRONE_OBJECTIVE_CHANGE_TIME)
        phase = (unit.id % 8) / 8.0
        angle = 2 * math.pi * ((current_time / orbit_period) + phase)
        x = orbit_center[0] + math.cos(angle) * orbit_radius
        y = orbit_center[1] + math.sin(angle) * orbit_radius
        return (
            max(0.0, min(float(MAP_WIDTH), x)),
            max(0.0, min(float(MAP_HEIGHT), y)),
        )

    def get_unit_speed(self, unit: Unit, position: Tuple[float, float]) -> float:
        """유닛의 이동 속도 반환 (지형 영향 포함)"""
        speed_override = _get_platform_override(unit.team, unit.unit_type, 'speed_kmh')
        if speed_override is None:
            base_speed = self.UNIT_SPEEDS.get(unit.unit_type, 0.0)  # m/s
        else:
            base_speed = _kmh_to_pxps(float(speed_override))
        decay_rate = self.terrain.get_terrain_decay_rate(unit, (int(position[0]), int(position[1])))
        return base_speed * decay_rate

    def can_move(self, unit: Unit) -> bool:
        """이동 가능 여부 확인"""
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
            current_pattern = self.drone_positions.get(unit.id, self._initial_drone_pattern(unit))
            
            # 다음 패턴 위치 계산
            next_pattern = (current_pattern + 1) % len(self.DRONE_PATTERN)
            self.drone_positions[unit.id] = next_pattern
            
            # 마지막 변경 시간 업데이트
            self.drone_last_objective_change[unit.id] = current_time
        else:
            # 현재 패턴 위치 유지
            current_pattern = self.drone_positions.get(unit.id, self._initial_drone_pattern(unit))
        
        # 패턴의 그리드 위치
        grid_x, grid_y = self.DRONE_PATTERN[current_pattern]
        
        # TAI를 중심으로 한 3x3 그리드의 시작점 계산
        start_x = tai[0] - self.DRONE_GRID_SIZE
        start_y = tai[1] - self.DRONE_GRID_SIZE
        
        # 해당 방안의 중심점 계산
        center_x = start_x + (grid_x - 0.5) * self.DRONE_GRID_SIZE
        center_y = start_y + (grid_y - 0.5) * self.DRONE_GRID_SIZE
        
        
        return (center_x, center_y)

    def get_objective(self, unit: Unit, command: Command, current_time: float,
                      all_units: Optional[List[Unit]] = None) -> Optional[Tuple[float, float]]:
        """유닛 타입에 따른 목적지 반환

        SELF_DEST_DRONE: 탐지된 전차/포병이 있으면 그 위치로 직접 비행(자폭 접근),
                         없으면 기존 TAI 3×3 정찰 패턴.
        """
        if unit.unit_type == UnitType.SELF_DEST_DRONE and all_units is not None:
            HIGH_VALUE = {UnitType.TANK, UnitType.ARTILLERY}
            best_pos = None
            best_dist = float('inf')
            for tid in unit.target_list:
                t = next((u for u in all_units if u.id == tid), None)
                if t and t.unit_type in HIGH_VALUE and t.status in [Status.ALIVE, Status.M_KILL, Status.MINOR]:
                    d = calculate_point_distance(unit.position, t.position)
                    if d < best_dist:
                        best_dist = d
                        best_pos = t.position
            if best_pos is not None:
                return best_pos
            return self.calculate_drone_objective(unit, command, current_time)

        if unit.unit_type == UnitType.DRONE:
            if all_units is not None:
                orbit_objective = self.calculate_drone_orbit_objective(unit, current_time, all_units)
                if orbit_objective is not None:
                    return orbit_objective
            return self.calculate_drone_objective(unit, command, current_time)
        elif unit.unit_type in [UnitType.RIFLE, UnitType.TANK, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
            if command.maneuver_objective and len(command.maneuver_objective) > 0:
                # maneuver_objective는 리스트이므로 첫 번째 목표 지점을 사용
                base_objective = command.maneuver_objective[0]
                # 목적지 겹침 완화를 위해 ±jitter(px) 랜덤 분산 적용
                j = self._OBJECTIVE_JITTER_PX
                return tuple(x + random.uniform(-j, j) for x in base_objective)
        return None

    # --- Squad / 진형 헬퍼 ---
    def _find_alive_leader(self, unit: Unit, all_units: List[Unit]) -> Optional[Unit]:
        """unit이 속한 squad의 살아있는 리더 반환. unit 자신이 리더면 None."""
        if not unit.squad_id or unit.is_leader:
            return None
        for u in all_units:
            if (u.squad_id == unit.squad_id and u.is_leader
                    and u.status in [Status.ALIVE, Status.MINOR, Status.M_KILL]):
                return u
        return None

    def _squad_follower_target(self, unit: Unit, all_units: List[Unit]) -> Optional[Tuple[float, float]]:
        """진형 추종 유닛(non-leader)의 목표 위치 = 리더 위치 + 회전된 진형 오프셋.
        리더가 없거나(squad 단독) 진형 오프셋이 없으면 None."""
        leader = self._find_alive_leader(unit, all_units)
        if leader is None or unit.formation_offset is None:
            return None
        local_x_m, local_y_m = unit.formation_offset
        yaw = leader.yaw  # 리더의 진행 방향 (radian)
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        # local: +y=forward, +x=right
        # world forward = (cos, sin), world right = (sin, -cos)
        world_dx_m = local_x_m * sin_y + local_y_m * cos_y
        world_dy_m = local_x_m * (-cos_y) + local_y_m * sin_y
        dx_px = world_dx_m / PIXEL_TO_METER_SCALE
        dy_px = world_dy_m / PIXEL_TO_METER_SCALE
        return (leader.position[0] + dx_px, leader.position[1] + dy_px)

    def move(self, unit: Unit, command: Command, current_time: float, all_units: List[Unit],
             time_step: float = 1.0) -> Optional[Event]:
        """유닛 이동 실행
        - 분대 추종원: 리더 위치 + 회전된 진형 오프셋을 목표로 직선 이동
        - 리더 / squad 없음: 기존 로직 (TAI 또는 maneuver_objective)
        """
        if not self.can_move(unit):
            unit.update_action(Action.STOP)
            return None

        # === 분대 추종원: 리더 위치 + 진형 오프셋으로 ===
        follower_target = self._squad_follower_target(unit, all_units)
        if follower_target is not None:
            unit.update_objective(follower_target)
            dx = follower_target[0] - unit.position[0]
            dy = follower_target[1] - unit.position[1]
            distance = calculate_point_distance(unit.position, follower_target)
            if distance < self.MIN_DISTANCE_TO_OBJECTIVE:
                # 이미 진형 위치 ≒ 정지 (리더가 움직이면 다시 이동 이벤트 예약됨)
                unit.update_action(Action.STOP)
                return None
            unit.update_action(Action.MOVE)
            if distance > 0:
                dx /= distance
                dy /= distance
            speed = self.get_unit_speed(unit, unit.position)
            # 직진 + 우회 시도 — 막히면 옆으로 돌아감
            step = self._try_passable_step(unit, dx, dy, speed, time_step)
            if step is None:
                unit.update_action(Action.STOP)
                return None
            next_x, next_y = step
            return Event(
                event_type=EventType.MOVE,
                time=current_time + time_step,
                source_id=unit.id,
                position=(next_x, next_y),
            )

        # === 리더 또는 squad 없음: 기존 로직 ===
        # 목표 지점 가져오기
        objective = self.get_objective(unit, command, current_time, all_units)
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
            if unit.unit_type in [UnitType.DRONE, UnitType.SELF_DEST_DRONE]:
                # 드론의 경우 다음 패턴으로 즉시 이동
                current_pattern = self.drone_positions.get(unit.id, self._initial_drone_pattern(unit))
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
                    next_x = unit.position[0] + dx * speed * time_step
                    next_y = unit.position[1] + dy * speed * time_step
                    return Event(
                        event_type=EventType.MOVE,
                        time=current_time + time_step,
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

        # 다음 위치 계산 + 우회 시도 (강·건물·언덕 막히면 ±각도 회전)
        speed = self.get_unit_speed(unit, unit.position)
        step = self._try_passable_step(unit, dx, dy, speed, time_step)
        if step is None:
            unit.update_action(Action.STOP)
            return None
        next_x, next_y = step

        return Event(
            event_type=EventType.MOVE,
            time=current_time + time_step,
            source_id=unit.id,
            position=(next_x, next_y)
        )
