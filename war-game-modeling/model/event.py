from dataclasses import dataclass
from typing import Callable, Any, List, Optional, Tuple
from enum import Enum
import heapq

class EventType(Enum):
    MOVE = "MOVE"
    FIRE = "FIRE"

@dataclass
class Event:
    time: float  # 이벤트 발생 시간
    event_type: EventType
    source_id: int  # 이벤트를 발생시킨 유닛의 ID
    target_id: Optional[int] = None  # 이벤트의 대상 유닛 ID (있는 경우)
    position: Optional[Tuple[float, float]] = None  # 이동 이벤트에서 사용
    data: Any = None  # 추가 데이터

    def __lt__(self, other):
        """시간을 기준으로 비교"""
        return self.time < other.time

class EventQueue:
    def __init__(self):
        self._queue: List[Event] = []
        self._current_time: float = 0.0

    def schedule(self, event: Event):
        """새로운 이벤트를 큐에 추가"""
        heapq.heappush(self._queue, (event.time, event))

    def get_next_event(self) -> Event:
        """다음 이벤트를 가져옴"""
        if not self._queue:
            return None
        _, event = heapq.heappop(self._queue)
        self._current_time = event.time
        return event

    def peek_next_event(self) -> Event:
        """다음 이벤트를 확인만 하고 제거하지 않음"""
        if not self._queue:
            return None
        return self._queue[0][1]

    def get_current_time(self) -> float:
        """현재 시뮬레이션 시간 반환"""
        return self._current_time

    def is_empty(self) -> bool:
        """이벤트 큐가 비어있는지 확인"""
        return len(self._queue) == 0 