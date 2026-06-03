from typing import List, Optional, Dict, Tuple
from model.unit import Unit, Status, Action, UnitType
from model.event import Event, EventType
from model.command import Command
from model.detect import Detect
from model.terrain import Terrain
from model.probabilities import ProbabilitySystem
from model.function import calculate_distance, calculate_point_distance
from model.money import MoneyTracker
import random
import math
import pandas as pd
import numpy as np
import yaml
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']
_FIRE_CFG = config['fire']
_PROTECTED_TERRAIN = set(_FIRE_CFG.get('protected_terrain_types', ['mountain', 'trench']))
_SELF_DEST_DRONE_LETHAL_RADIUS_M = _FIRE_CFG.get('self_dest_drone_lethal_radius_m', 5.0)


def _load_target_priority(raw_priority: Dict[str, List[str]]) -> Dict[UnitType, List[UnitType]]:
    priority = {}
    for attacker_name, target_names in raw_priority.items():
        attacker_type = UnitType[attacker_name]
        priority[attacker_type] = [UnitType[target_name] for target_name in target_names]
    return priority


_TARGET_PRIORITY = _load_target_priority(_FIRE_CFG.get('target_priority', {}))

class Fire:
    def __init__(self, money_tracker: Optional[MoneyTracker] = None):
        self.detect = Detect()
        self.terrain = Terrain()
        self.money_tracker = money_tracker

    def record_damage_cost(self, unit: Unit, old_status: Status, new_status: Status) -> None:
        if self.money_tracker and old_status != new_status:
            self.money_tracker.record_damage(unit, old_status, new_status)

    def record_fire_cost(self, attacker: Unit) -> None:
        if self.money_tracker:
            self.money_tracker.record_fire(attacker)

    def calculate_impact_point(self, target_position: Tuple[float, float], distance: float) -> Tuple[float, float]:
        """곡사화기의 탄착지점 계산

        Args:
            target_position: 목표 지점 좌표
            distance: 사거리 (픽셀단위)

        Returns:
            Tuple[float, float]: 탄착지점 좌표
        """
        # 공산오차 계산 — config에서 비율 읽음
        sigma_y = _FIRE_CFG['artillery_sigma_range_pct'] * distance  # 사거리 공산오차
        sigma_x = _FIRE_CFG['artillery_sigma_dev_pct'] * distance    # 편의 공산오차
        
        # 정규분포를 따르는 랜덤 오차 생성
        error_x = random.gauss(0, sigma_x)
        error_y = random.gauss(0, sigma_y)
        
        # 탄착지점 계산
        impact_x = target_position[0] + error_x
        impact_y = target_position[1] + error_y
        
        return (impact_x, impact_y)

    def calculate_damage_probability(self, distance: float, lethal_radius: float) -> float:
        """Gaussian Damage Function을 사용한 피해확률 계산
        
        Args:
            distance: 탄착지점으로부터의 거리 (픽셀)
            lethal_radius: 치사반경 (픽셀)
            
        Returns:
            float: 피해확률 (0~1)
        """

        return math.exp(-(distance ** 2) / (2 * (lethal_radius ** 2)))

    def apply_artillery_damage(
        self,
        attacker: Unit,
        impact_point: Tuple[float, float],
        all_units: List[Unit],
        current_time: float,
    ) -> None:
        """곡사화기 탄착지점 주변의 모든 유닛에 대한 피해 적용
        
        Args:
            impact_point: 탄착지점 좌표
            all_units: 모든 유닛 리스트
            current_time: 현재 시뮬레이션 시간
        """
        lethal_radius = config['simulation']['lethal_radius'] / PIXEL_TO_METER_SCALE
        affected_units = []
        
        # 치사반경 내의 모든 유닛에 대해 피해 적용
        for unit in all_units:
            if (unit.status.value in ["ALIVE", "M_KILL", "MINOR"] and  # 살아있는 유닛만 처리
                unit.unit_type != UnitType.DRONE):  # 드론은 제외
                distance = calculate_point_distance(impact_point, unit.position)
                
                if distance <= lethal_radius:
                    # 피해확률 계산
                    damage_prob = (
                        self.calculate_damage_probability(distance, lethal_radius)
                        * self.terrain.get_damage_probability_multiplier(unit.position)
                    )
                    
                    # 피해 적용 여부 결정
                    if random.random() <= damage_prob:
                        # 방호상태 확인
                        protection_state = self.get_protection_state(unit)
                        
                        # 살상확률 계산 및 상태 결정
                        kill_probs = ProbabilitySystem.get_kill_probability(
                            UnitType.ARTILLERY,
                            unit.unit_type,
                            distance * PIXEL_TO_METER_SCALE,
                            protection_state,
                            side=attacker.team.value,
                        )
                        
                        if unit.unit_type in [UnitType.TANK, UnitType.ARTILLERY]:
                            m_kill_prob = kill_probs.get(Status.M_KILL, 0.0)
                            if unit.status == Status.ALIVE:
                                rand_val = random.random()
                            else:  # M_KILL 상태
                                rand_val = random.uniform(m_kill_prob, 1.0)
                        else:  # RIFLE, ANTI_TANK, COMMAND_POST
                            minor_prob = kill_probs.get(Status.MINOR, 0.0)
                            if unit.status == Status.ALIVE:
                                rand_val = random.random()
                            else:
                                rand_val = random.uniform(minor_prob, 1.0)
                        
                        cumulative = 0.0
                        old_status = unit.status
                        for status, prob in kill_probs.items():
                            cumulative += prob
                            if rand_val <= cumulative:
                                unit.update_status(status)
                                self.record_damage_cost(unit, old_status, status)
                                affected_units.append((unit, old_status, status))
                                break

    def apply_self_dest_drone_damage(
        self,
        attacker: Unit,
        impact_point: Tuple[float, float],
        all_units: List[Unit],
    ) -> None:
        lethal_radius = _SELF_DEST_DRONE_LETHAL_RADIUS_M / PIXEL_TO_METER_SCALE

        for unit in all_units:
            if (
                unit.team != attacker.team
                and unit.status.value in ["ALIVE", "M_KILL", "MINOR"]
                and unit.unit_type != UnitType.DRONE
                and unit.unit_type != UnitType.SELF_DEST_DRONE
            ):
                impact_distance = calculate_point_distance(impact_point, unit.position)
                if impact_distance > lethal_radius:
                    continue

                protection_state = self.get_protection_state(unit)
                attack_distance = calculate_distance(attacker, unit) * PIXEL_TO_METER_SCALE
                kill_probs = ProbabilitySystem.get_kill_probability(
                    attacker.unit_type,
                    unit.unit_type,
                    attack_distance,
                    protection_state,
                    side=attacker.team.value,
                )
                if not kill_probs:
                    continue

                rand_val = random.random()
                cumulative = 0.0
                old_status = unit.status
                for status, prob in kill_probs.items():
                    cumulative += prob
                    if rand_val <= cumulative:
                        unit.update_status(status)
                        self.record_damage_cost(unit, old_status, status)
                        break

    def update_eligible_targets(self, unit: Unit, all_units: List[Unit]) -> None:
        """사격 가능한 타겟 목록 업데이트"""
        unit.clear_eligible_targets()  # 기존 사격 가능 타겟 목록 초기화
        
        # target_list의 각 타겟에 대해 거리 확인
        for target_id in unit.target_list:
            target = next((u for u in all_units if u.id == target_id), None)
            if target:
                # 
                if target.status in [Status.ALIVE, Status.M_KILL, Status.MINOR]:
                    # Rifle은 전차를 공격할 수 없음
                    if unit.unit_type == UnitType.RIFLE and target.unit_type == UnitType.TANK:
                        continue
                        
                    distance = calculate_distance(unit, target)
                    if distance <= unit.weapon_range:
                        # 직사화기의 경우 LOS 체크
                        if unit.unit_type in [UnitType.RIFLE, UnitType.TANK, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
                            if self.detect.check_los(unit, target):  # LOS가 확보된 경우에만 타겟 추가
                                unit.add_eligible_target(target_id)
                        else:  # 곡사화기(ARTILLERY)는 LOS 체크 없이 타겟 추가
                            unit.add_eligible_target(target_id)

    def get_protection_state(self, target: Unit) -> str:
        """타겟의 방호상태를 결정
        
        Returns:
            str: 방호상태 코드
            - ES: 노출 정지
            - EM: 노출 이동
            - DS: 차폐 정지
            - DM: 차폐 이동
        """
        terrain_type = self.terrain.get_terrain_type(target.position)
        is_protected_terrain = terrain_type in _PROTECTED_TERRAIN
        is_moving = target.action == Action.MOVE

        if is_protected_terrain:
            return "DS" if not is_moving else "DM"
        else:
            return "ES" if not is_moving else "EM"

    def finding_target(self, attacker: Unit, all_units: List[Unit], command: Command) -> Optional[int]:
        """사격 가능한 표적 중에서 목표 선정"""
        if not attacker.eligible_target_list:
            return None

        priority_order = _TARGET_PRIORITY.get(attacker.unit_type)
        if priority_order:
            for target_type in priority_order:
                candidates = []
                for target_id in attacker.eligible_target_list:
                    target = next((u for u in all_units if u.id == target_id), None)
                    if target and target.unit_type == target_type:
                        candidates.append(target)
                if candidates:
                    nearest = min(candidates, key=lambda target: calculate_distance(attacker, target))
                    return nearest.id
            return None

        min_distance = float('inf')
        selected_target = None

        for target_id in attacker.eligible_target_list:
            target = next((u for u in all_units if u.id == target_id), None)
            if target:
                distance = calculate_distance(attacker, target)
                if distance < min_distance:
                    min_distance = distance
                    selected_target = target_id

        return selected_target

    def fire(self, attacker: Unit, target: Unit, all_units: List[Unit], command: Command, current_time: float) -> Optional[Event]:
        """유닛의 사격 처리"""
        if not attacker.can_fire():
            attacker.update_action(Action.STOP)
            return None
        # 표적이 여전히 존재하고 사격 가능한 상태인지 확인
        if attacker.unit_type != UnitType.ARTILLERY:
            if not target or target.status not in [Status.ALIVE, Status.M_KILL, Status.MINOR]:
                attacker.update_action(Action.STOP)
                return None
        # 1. 거리 계산
        distance = calculate_distance(attacker, target)
        
        # 곡사화기인 경우 다른 방식으로 처리
        if attacker.unit_type == UnitType.ARTILLERY:
            # 탄착지점 계산
            impact_point = self.calculate_impact_point(target.position, distance)
            
            # 치사반경 내 아군 확인
            lethal_radius = config['simulation']['lethal_radius'] / PIXEL_TO_METER_SCALE  # 치사반경
            friendly_units_in_radius = []
            
            for unit in all_units:
                if (unit.team == attacker.team 
                    and unit.status.value in ["ALIVE", "M_KILL", "MINOR"]
                    and unit.unit_type != UnitType.DRONE
                    and unit.unit_type != UnitType.SELF_DEST_DRONE):  # 드론 및 자폭 드론 제외
                    unit_distance = calculate_point_distance(impact_point, unit.position)
                    if unit_distance <= lethal_radius:
                        friendly_units_in_radius.append(unit)
            
            # 치사반경 내 아군이 있으면 사격 취소
            if friendly_units_in_radius:
                attacker.update_action(Action.STOP)  # 사격 취소 시 STOP으로 변경
                return None
            
            # 탄착지점 주변의 모든 유닛에 대한 피해 적용
            self.record_fire_cost(attacker)
            self.apply_artillery_damage(attacker, impact_point, all_units, current_time)
            attacker.update_action(Action.STOP)  # 사격 완료 후 STOP으로 변경
            return None

        if attacker.unit_type == UnitType.SELF_DEST_DRONE:
            self.record_fire_cost(attacker)
            protection_state = self.get_protection_state(target)
            hit_prob = (
                ProbabilitySystem.get_hit_probability(
                    attacker.unit_type,
                    target.unit_type,
                    distance * PIXEL_TO_METER_SCALE,
                    protection_state,
                    side=attacker.team.value,
                )
                * self.terrain.get_hit_probability_multiplier(target.position)
            )

            if random.random() <= hit_prob:
                self.apply_self_dest_drone_damage(attacker, target.position, all_units)

            attacker.update_status(Status.K_KILL)
            attacker.update_action(Action.STOP)
            return None
        
        # 직사화기 처리 (기존 코드)
        """
        직사화기(소총/대전차/지휘관) 사격 및 피해 처리
        [1] 명중확률 P_h 불러오기
        [2] 난수로 명중 여부 판정
        [3] 조건부 살상확률 P_k/h 불러오기 → 보간/테이블 참조는 ProbabilitySystem 에서
        [4] 파괴확률 계산 (보간법) → ProbabilitySystem 에서
        [5] 난수로 피해 타입 결정
        [6] 피해 타입별 표적 상태 무력화 판정
            - 탱크·곡사포: MF-kill 이상이면 “무력화 성공” (재탐색 대신 후속 사격 중지)
            - 소총·대전차·지휘관: 치명상(Fatal)이면 “무력화 성공”
        """
        self.record_fire_cost(attacker)
        protection_state = self.get_protection_state(target)
        hit_prob = (
            ProbabilitySystem.get_hit_probability(
                attacker.unit_type,
                target.unit_type,
                distance * PIXEL_TO_METER_SCALE,
                protection_state,
                side=attacker.team.value,
            )
            * self.terrain.get_hit_probability_multiplier(target.position)
        )
        
        hit_success = random.random() <= hit_prob

        # 4. 살상확률 계산 및 상태 결정
        if hit_success:
            kill_probs = ProbabilitySystem.get_kill_probability(
                attacker.unit_type,
                target.unit_type,
                distance * PIXEL_TO_METER_SCALE,
                protection_state,
                side=attacker.team.value,
            )
                
            if target.unit_type in [UnitType.TANK, UnitType.ARTILLERY]:
                m_kill_prob = kill_probs.get(Status.M_KILL, 0.0)
                if target.status == Status.ALIVE:
                    rand_val = random.random()  # 0~1 범위
                else:  # M_KILL 상태
                    rand_val = random.uniform(m_kill_prob, 1.0)  # m_kill_prob~1 범위
            else:  # RIFLE, ANTI_TANK, COMMAND_POST
                minor_prob = kill_probs.get(Status.MINOR, 0.0)
                if target.status == Status.ALIVE:
                    rand_val = random.random()  # 0~1 범위
                else:
                    rand_val = random.uniform(minor_prob, 1.0)  # minor_prob~1 범위
                
            cumulative = 0.0
            old_status = target.status
            for status, prob in kill_probs.items():
                cumulative += prob   # multivariante probability sampling method
                if rand_val <= cumulative:
                    target.update_status(status)
                    self.record_damage_cost(target, old_status, status)
                    break

        attacker.update_action(Action.STOP)  # 사격 완료 후 STOP으로 변경
        return None

    def schedule_fire_event(self, unit: Unit, all_units: List[Unit], command: Command, current_time: float) -> Optional[Event]:
        """사격 이벤트 스케줄링"""
        if not unit.can_fire():
            return None

        # 탐지 상태 업데이트
        self.detect.update_detection(unit, all_units)
        
        # 사격 가능 타겟 목록 업데이트
        self.update_eligible_targets(unit, all_units)
        
        # 사격 가능한 타겟이 있는지 확인
        if not unit.eligible_target_list:
            return None
            
        # finding_target을 통해 목표 선정
        target_id = self.finding_target(unit, all_units, command)
        if target_id is not None:
            target = next((u for u in all_units if u.id == target_id), None)
            if target:
                unit.update_action(Action.FIRE)  # 사격 이벤트 생성 시 FIRE로 변경
                return Event(
                    event_type=EventType.FIRE,
                    time=current_time + unit.get_fire_interval(),
                    source_id=unit.id,
                    target_id=target_id
                )
        
        return None
