from typing import List, Optional
from model.unit import Unit, Status, UnitType, Team
from model.terrain import Terrain
from model.function import calculate_distance
import random
import yaml

with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']
class Detect:
    def __init__(self):
        self.terrain = Terrain()
        self.MOUNTAIN_DETECT_PROB = config['simulation']['mountain_detect_prob']  # 산악지형 탐지 확률

    def check_los(self, observer: Unit, target: Unit) -> bool:
        """시야선(LOS) 확인"""
            
        # 두 유닛의 위치와 고도
        x1, y1 = observer.position
        x2, y2 = target.position
        
        # 드론의 경우 고도를 설정값으로 고정하고 픽셀로 변환
        if observer.unit_type == UnitType.DRONE:
            observer_elevation = config['simulation']['drone_elevation'] / PIXEL_TO_METER_SCALE  # 미터를 픽셀로 변환
        else:
            # 지형의 고도는 이미 픽셀 단위
            observer_elevation = self.terrain.get_elevation((int(x1), int(y1)))
            
        # 목표의 고도 (이미 픽셀 단위)
        target_elevation = self.terrain.get_elevation((int(x2), int(y2)))
        
        # 두 유닛 사이의 거리 계산
        distance = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        
        # 10픽셀 간격으로 체크
        check_interval = 10
        num_checks = int(distance / check_interval)
        
        # 두 유닛 사이의 직선 경로를 체크
        for i in range(1, num_checks):  # 시작점과 끝점은 제외
            # 현재 확인할 지점의 좌표 계산
            x = x1 + (x2 - x1) * (i / num_checks)
            y = y1 + (y2 - y1) * (i / num_checks)
            
            # 현재 지점의 고도 (이미 픽셀 단위)
            current_elevation = self.terrain.get_elevation((int(x), int(y)))
            
            # 현재 지점의 고도가 관측자나 목표의 고도보다 높으면 시야 차단
            if current_elevation > observer_elevation and current_elevation > target_elevation:
                return False
                
        return True

    def detect_target(self, observer: Unit, target: Unit) -> bool:
        """적 유닛 탐지"""
        # 1. 거리 계산 (픽셀단위)
        distance = calculate_distance(observer, target)
        
        # 2. 탐지 거리 확인 (픽셀 단위)
        detect_range = observer.detect_range * target.detectability
        if distance > detect_range:
            return False
        
        # 3. LOS 확인
        if not self.check_los(observer, target):
            return False
        
        # 4. 지형에 따른 탐지 확률 적용
        target_terrain = self.terrain.get_terrain_type((int(target.position[0]), int(target.position[1])))
        
        if target_terrain == 'mountain':
            detect_prob = self.MOUNTAIN_DETECT_PROB
            if random.random() > detect_prob:
                return False
        
        # 5. 탐지 성공
        return True

    def share_info(self, team: Team, all_units: List[Unit]) -> None:
        """지휘소를 통한 표적 정보 공유"""
        # 팀의 지휘소 찾기
        command_post = next((u for u in all_units 
                           if u.team == team 
                           and u.unit_type == UnitType.COMMAND_POST), None)

        # 지휘소가 살아있는 경우 모든 유닛의 표적 정보 공유
        if command_post and command_post.status in [Status.ALIVE, Status.M_KILL, Status.MINOR]:
            shared_targets = set()        
            for unit in all_units:
                if unit.team == team:
                    shared_targets.update(unit.target_list)
            
            # 공유된 표적 정보를 팀의 모든 유닛에 전달
            for unit in all_units:
                if unit.team == team:
                    unit.target_list.update(shared_targets)
        # 지휘소가 피해를 받은 경우 드론의 표적 정보만 포병에게 공유
        else:
            # 드론의 표적 정보 수집
            drone_targets = set()
            for unit in all_units:
                if unit.team == team and unit.unit_type == UnitType.DRONE:
                    drone_targets.update(unit.target_list)
            
            # 드론의 표적 정보를 포병에게만 전달
            for unit in all_units:
                if unit.team == team and unit.unit_type == UnitType.ARTILLERY:
                    unit.target_list.update(drone_targets)

    def update_detection(self, observer: Unit, all_units: List[Unit]):
        """모든 적 유닛에 대한 탐지 업데이트"""
        #observer.clear_targets()  # 이전 탐지 목록 초기화
        
        for target in all_units:
            if target.team != observer.team and target.status in [Status.ALIVE, Status.M_KILL, Status.MINOR]:
                if self.detect_target(observer, target):
                    observer.add_target(target.id)
        
        
        # 지휘소를 통한 표적 정보 공유
        #self.share_info(observer.team, all_units)
                    