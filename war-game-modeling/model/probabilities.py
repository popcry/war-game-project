import pandas as pd
from typing import Dict, Tuple, Union
from model.unit import UnitType, Status

class ProbabilitySystem:
    # Load probability data
    rifle_at_commander_hit = pd.read_csv('database/rifle_at_commander_hit.csv')
    # 직사화기(라이플, 전차, 대전차, 지휘소)가 라이플, 대전차, 지휘소를 명중시킬 확률

    rifle_at_commander_kh = pd.read_csv('database/rifle_at_commander_kh.csv')
    # 직사화기(라이플, 전차, 대전차, 지휘소)가 라이플, 대전차, 지휘소를 명중시켰을 때 상태별 확률

    tank_artillery_hit = pd.read_csv('database/tank_artillery_hit.csv')
    # 직사화기(라이플, 전차, 대전차, 지휘소)가 탱크, 포병을 명중시킬 확률

    tank_artillery_kh = pd.read_csv('database/tank_artillery_kh.csv')
    # 직사화기(라이플, 전차, 대전차, 지휘소)가 탱크, 포병을 명중시켰을 때 상태별 확률

    @classmethod
    def get_hit_probability(cls, attacker_type: UnitType, target_type: UnitType, 
                          distance: float, protection_state: str) -> float:
        """명중확률 반환
        
        Args:
            attacker_type: 공격자 유닛 타입
            target_type: 표적 유닛 타입
            distance: 거리
            protection_state: 방호상태 (ES, EM, DS, DM)
            
        Returns:
            float: 명중확률 (0~1)
        """
        # 직사화기인지 확인
        if attacker_type in [UnitType.RIFLE, UnitType.TANK, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
            # 표적 타입에 따라 적절한 테이블 선택
            if target_type in [UnitType.RIFLE, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
                table = cls.rifle_at_commander_hit
            else:  # TANK, ARTILLERY
                table = cls.tank_artillery_hit

            # 거리에 따른 보간
            return cls._interpolate_probability(table, distance, protection_state)
        else:
            return 0.0  # 직사화기가 아닌 경우 0 반환

    @classmethod
    def get_kill_probability(cls, attacker_type: UnitType, target_type: UnitType,
                           distance: float, protection_state: str) -> Dict[Status, float]:
        """살상확률 반환
        
        Args:
            attacker_type: 공격자 유닛 타입
            target_type: 표적 유닛 타입
            distance: 거리
            protection_state: 방호상태 (ES, EM, DS, DM)
            
        Returns:
            Dict[Status, float]: 상태별 살상확률
        """
        # 직사화기인지 확인
        #if attacker_type not in [UnitType.RIFLE, UnitType.TANK, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
        #    return {}

        # 표적 타입에 따라 적절한 테이블 선택
        if target_type in [UnitType.RIFLE, UnitType.ANTI_TANK, UnitType.COMMAND_POST]:
            table = cls.rifle_at_commander_kh
        else:  # TANK, ARTILLERY
            table = cls.tank_artillery_kh

        # 모든 상태의 확률을 한번에 계산
        return cls._interpolate_probability(table, distance, protection_state)

    @classmethod
    def _interpolate_probability(cls, table: pd.DataFrame, distance: float, 
                               protection_state: str, state: Status = None) -> Union[float, Dict[Status, float]]:
        """거리와 방호상태에 따른 확률 보간
        
        Args:
            table: 확률 테이블
            distance: 거리
            protection_state: 방호상태 (ES, EM, DS, DM)
            state: 살상확률을 구할 때만 사용되는 상태
            
        Returns:
            Union[float, Dict[Status, float]]: 보간된 확률
            - hit probability의 경우 float 반환
            - kill probability의 경우 Dict[Status, float] 반환
        """
        # tank_artillery_kh.csv의 경우 특별 처리
        if 'Kill Type' in table.columns:
            # 모든 살상 유형의 확률을 반환
            probabilities = {}
            mf_prob = table.loc[table['Kill Type'] == 'MF-Kill', protection_state].iloc[0]
            m_kill_prob = table.loc[table['Kill Type'] == 'M-Kill', protection_state].iloc[0]
            f_kill_prob = table.loc[table['Kill Type'] == 'F-Kill', protection_state].iloc[0]
            
            # Kill Type을 Status로 변환
            probabilities[Status.M_KILL] = mf_prob - f_kill_prob  # MF-kill 확률에서 F-kill 확률 제외
            probabilities[Status.F_KILL] = mf_prob - m_kill_prob  # MF-kill 확률에서 M-kill 확률 제외
            probabilities[Status.MF_KILL] = mf_prob
            probabilities[Status.K_KILL] = table.loc[table['Kill Type'] == 'K-Kill', protection_state].iloc[0]
            return probabilities

        # rifle_at_commander_kh.csv의 경우 특별 처리
        if 'State' in table.columns:
            # 거리가 테이블 범위를 벗어나는 경우
            distances = table['Distance (m)'].unique()
            if distance <= min(distances):
                closest_dist = min(distances)
                row = table[(table['Distance (m)'] == closest_dist) & (table['State'] == protection_state)]
                return {
                    Status.MINOR: row['Minor'].iloc[0],
                    Status.SERIOUS: row['Serious'].iloc[0],
                    Status.CRITICAL: row['Critical'].iloc[0],
                    Status.FATAL: row['Fetal'].iloc[0]
                }
            if distance >= max(distances):
                closest_dist = max(distances)
                row = table[(table['Distance (m)'] == closest_dist) & (table['State'] == protection_state)]
                return {
                    Status.MINOR: row['Minor'].iloc[0],
                    Status.SERIOUS: row['Serious'].iloc[0],
                    Status.CRITICAL: row['Critical'].iloc[0],
                    Status.FATAL: row['Fetal'].iloc[0]
                }

            # 거리에 따른 보간
            lower_dist = max(d for d in distances if d <= distance)
            upper_dist = min(d for d in distances if d >= distance)
            
            if lower_dist == upper_dist:
                row = table[(table['Distance (m)'] == lower_dist) & (table['State'] == protection_state)]
                return {
                    Status.MINOR: row['Minor'].iloc[0],
                    Status.SERIOUS: row['Serious'].iloc[0],
                    Status.CRITICAL: row['Critical'].iloc[0],
                    Status.FATAL: row['Fetal'].iloc[0]
                }
            
            # 선형 보간
            lower_row = table[(table['Distance (m)'] == lower_dist) & (table['State'] == protection_state)]
            upper_row = table[(table['Distance (m)'] == upper_dist) & (table['State'] == protection_state)]
            
            # 각 상태별로 보간
            return {
                Status.MINOR: cls._linear_interpolate(
                    distance, lower_dist, upper_dist,
                    lower_row['Minor'].iloc[0], upper_row['Minor'].iloc[0]
                ),
                Status.SERIOUS: cls._linear_interpolate(
                    distance, lower_dist, upper_dist,
                    lower_row['Serious'].iloc[0], upper_row['Serious'].iloc[0]
                ),
                Status.CRITICAL: cls._linear_interpolate(
                    distance, lower_dist, upper_dist,
                    lower_row['Critical'].iloc[0], upper_row['Critical'].iloc[0]
                ),
                Status.FATAL: cls._linear_interpolate(
                    distance, lower_dist, upper_dist,
                    lower_row['Fetal'].iloc[0], upper_row['Fetal'].iloc[0]
                )
            }

        # 일반적인 hit probability 테이블 처리
        # 거리가 테이블 범위를 벗어나는 경우
        if distance <= table.index[0]:
            return table.loc[table.index[0], protection_state]
        if distance >= table.index[-1]:
            return table.loc[table.index[-1], protection_state]

        # 거리에 따른 보간
        lower_dist = table.index[table.index <= distance][-1]
        upper_dist = table.index[table.index >= distance][0]
        
        if lower_dist == upper_dist:
            return table.loc[lower_dist, protection_state]
            
        # 선형 보간
        lower_prob = table.loc[lower_dist, protection_state]
        upper_prob = table.loc[upper_dist, protection_state]
        
        return cls._linear_interpolate(distance, lower_dist, upper_dist, lower_prob, upper_prob)

    @staticmethod
    def _linear_interpolate(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0) 