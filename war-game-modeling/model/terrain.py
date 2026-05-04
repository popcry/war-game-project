import pandas as pd
import numpy as np
from typing import Tuple, Dict
from model.unit import UnitType, Unit
import yaml

with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']

class Terrain:
    def __init__(self, dem_file: str = "database/xyz_coordinates.csv"):
        # DEM 데이터 로드
        self.dem_data = pd.read_csv(dem_file, header=None).values
        
        # 지형 타입 상수 (픽셀 단위)
        self.MOUNTAIN_THRESHOLD = 50 / PIXEL_TO_METER_SCALE  # 50m를 픽셀로 변환
        self.RIVER_THRESHOLD = 39 / PIXEL_TO_METER_SCALE     # 39m를 픽셀로 변환
        
        # 지형별 이동속도 감소율
        self.terrain_decay_rates = {
            'mountain': 0.8,  # 산악
            'river': 0.8,     # 하천
            'normal': 1.0     # 일반
        }

    def get_elevation(self, position: Tuple[float, float]) -> float:
        """위치의 고도 반환 (픽셀 단위)"""
        x, y = position
        x_int, y_int = int(x), int(y)
        if 0 <= x_int < self.dem_data.shape[1] and 0 <= y_int < self.dem_data.shape[0]:
            # DEM 데이터는 미터 단위이므로 픽셀로 변환
            return self.dem_data[y_int, x_int] / PIXEL_TO_METER_SCALE
        return 0.0  # 범위를 벗어난 경우 기본값

    def get_terrain_type(self, position: Tuple[int, int]) -> str:
        """주어진 위치의 지형 타입 반환"""
        elevation = self.get_elevation(position)
        if elevation >= self.MOUNTAIN_THRESHOLD:
            return 'mountain'
        elif elevation <= self.RIVER_THRESHOLD:
            return 'river'
        return 'normal'

    def get_terrain_decay_rate(self, unit: Unit, position: Tuple[int, int]) -> float:
        """유닛의 지형에 따른 이동속도 감소율 반환"""
        # 드론은 지형 영향을 받지 않음
        if unit.unit_type == UnitType.DRONE:
            return 1.0
            
        terrain_type = self.get_terrain_type(position)
        return self.terrain_decay_rates[terrain_type] 