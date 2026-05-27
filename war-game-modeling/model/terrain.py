import math
import pandas as pd
import numpy as np
from typing import Tuple, Dict, List
from model.unit import UnitType, Unit
import yaml

with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']
_TERRAIN_CFG = config['terrain']

class Terrain:
    def __init__(self, dem_file: str = None):
        # DEM 데이터 로드 — config 또는 인자로 경로 지정
        if dem_file is None:
            dem_file = _TERRAIN_CFG.get('dem_file', 'database/xyz_coordinates.csv')
        self.dem_data = pd.read_csv(dem_file, header=None).values

        # 지형 임계값 (m → px 환산)
        self.MOUNTAIN_THRESHOLD = _TERRAIN_CFG['mountain_threshold_m'] / PIXEL_TO_METER_SCALE
        self.RIVER_THRESHOLD = _TERRAIN_CFG['river_threshold_m'] / PIXEL_TO_METER_SCALE

        # 지형별 이동속도 감쇠율
        self.terrain_decay_rates = {
            'mountain': _TERRAIN_CFG['decay_rates']['mountain'],
            'river': _TERRAIN_CFG['decay_rates']['river'],
            'normal': _TERRAIN_CFG['decay_rates']['normal'],
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
