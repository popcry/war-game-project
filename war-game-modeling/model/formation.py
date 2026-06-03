"""쐐기형(wedge) 진형 오프셋 정의.

각 squad/team의 size에 따라 N개의 (dx_m, dy_m) 오프셋을 반환.
좌표계는 local frame: +y = 전진 방향, +x = 우측.
0번 인덱스 = 리더(보통 첫 유닛, 진형 정점 또는 선두).

다른 size는 가까운 표준 진형으로 매핑 (1, 2, 3, 5, 9, 15 정의).
필요 시 새 size를 추가하면 됨.
"""
from typing import List, Tuple

# 진형 간격 (실측은 10-30m 군 표준이나 25 m/px 맵에서 가시화를 위해 다소 과장)
FILE_SPACING_M = 200.0   # 좌우 간격 (8 px @25 m/px)
RANK_SPACING_M = 300.0   # 앞뒤 간격 (12 px @25 m/px)


def _wedge(rank_counts: List[int]) -> List[Tuple[float, float]]:
    """각 rank별 유닛 수 리스트(rank_counts)를 받아 쐐기형 오프셋 산출.

    rank 0(선두): rank_counts[0]개. rank 1: rank_counts[1]개. ...
    각 rank는 -y 방향으로 RANK_SPACING_M만큼 후방.
    각 rank 내에서는 좌우대칭으로 FILE_SPACING_M 간격.
    """
    offsets = []
    for rank_idx, n in enumerate(rank_counts):
        y = -rank_idx * RANK_SPACING_M
        # rank 내 좌우 배치: n=1이면 x=0, n=3이면 x=-d,0,+d, ...
        for file_idx in range(n):
            # 중앙 정렬: file_idx가 0~n-1일 때 x = (file_idx - (n-1)/2) * spacing
            x = (file_idx - (n - 1) / 2.0) * FILE_SPACING_M
            offsets.append((x, y))
    return offsets


# size → 진형. 0번 = 진형 정점(리더).
_WEDGE_PATTERNS = {
    1:  [(0.0, 0.0)],                                            # 단독
    2:  _wedge([1, 1]),                                          # 종대 2 (선두-후속)
    3:  _wedge([1, 2]),                                          # 작은 쐐기 (1+2)
    5:  _wedge([1, 2, 2]),                                       # 5명 쐐기
    9:  _wedge([1, 3, 5]),                                       # 표준 9명 쐐기 (1+3+5)
    15: _wedge([1, 2, 3, 4, 5]),                                 # 큰 쐐기 (1+2+3+4+5)
}


def get_offsets(squad_size: int) -> List[Tuple[float, float]]:
    """squad_size에 대한 진형 오프셋 리스트(0번 = 리더)."""
    if squad_size in _WEDGE_PATTERNS:
        return _WEDGE_PATTERNS[squad_size]
    # 미정의 size는 정사각형에 가까운 쐐기로 fallback
    # 가까운 적당한 분할: 1, 2, 3, 4, ... 순으로 누적해서 size에 도달
    counts = []
    remaining = squad_size
    width = 1
    while remaining > 0:
        take = min(width, remaining)
        counts.append(take)
        remaining -= take
        width += 1
    return _wedge(counts)
