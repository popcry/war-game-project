import yaml
import time
import pygame
from typing import List, Dict, Optional
from model.unit import Unit, Team, UnitType, Status, Action
from model.visualization import Visualizer
from model.event import Event, EventType
from model.fire import Fire
from model.detect import Detect
from model.movement import Movement
from model.command import Command, Phase
from model.money import MoneyTracker
from model.terrain import Terrain
from model.formation import get_offsets as get_formation_offsets
import csv
import heapq
import argparse
import os
import shutil
import stat


def _remove_readonly(func, path, exc_info):
    """Windows read-only 비트를 해제하고 삭제를 재시도."""
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    func(path)


def _reset_directory(path: str) -> None:
    """디렉토리를 삭제 후 재생성 (Windows read-only 폴더 포함)."""
    if os.path.isdir(path):
        shutil.rmtree(path, onerror=_remove_readonly)
    elif os.path.exists(path):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        os.remove(path)
    os.makedirs(path, exist_ok=True)


def _safe_rmtree(path: str) -> None:
    """생성 디렉토리에 대한 best-effort 재귀 삭제."""
    if os.path.exists(path):
        shutil.rmtree(path, onerror=_remove_readonly)

UNIT_TYPE_NAME = {
    UnitType.DRONE: "drone",
    UnitType.SELF_DEST_DRONE: "self_dest_drone",
    UnitType.TANK: "tank",
    UnitType.RIFLE: "infantry",
    UnitType.ARTILLERY: "artillery",
    UnitType.ANTI_TANK: "antitank",
    UnitType.COMMAND_POST: "command_post",
}

UNIT_TYPE_ABBR = {
    UnitType.DRONE: "drn",
    UnitType.SELF_DEST_DRONE: "sdd",
    UnitType.TANK: "tnk",
    UnitType.RIFLE: "inf",
    UnitType.ARTILLERY: "art",
    UnitType.ANTI_TANK: "at",
    UnitType.COMMAND_POST: "cp",
}

# (정보용) 차량·보병 상태 체계가 다릅니다:
#   - TANK/ARTILLERY/DRONE: alive / m_kill / f_kill / mf_kill / k_kill
#   - RIFLE/ANTI_TANK/COMMAND_POST: alive / minor / serious / critical / fatal
DEAD_STATUSES = {Status.K_KILL, Status.FATAL}

# 조기종료 판정 대상(전투유닛) — config에서 읽음
with open('config.yaml', 'r', encoding='utf-8') as _f:
    _COMBAT_TYPES_CFG = yaml.safe_load(_f)['simulation'].get(
        'combat_unit_types', ['RIFLE', 'ANTI_TANK', 'TANK', 'ARTILLERY'])
COMBAT_UNIT_TYPES = {UnitType[name] for name in _COMBAT_TYPES_CFG}


# unit.status(9종) → kill 분류(5종) 매핑
#   차량(TANK/ARTILLERY/DRONE)은 kill 타입을 그대로 사용
#   보병(RIFLE/ANTI_TANK/COMMAND_POST)은 부상 단계를 kill 타입으로 환산
#     MINOR(경상)=전투가능 → alive,  SERIOUS·CRITICAL(중상·중증)=이동·사격불가 → mf_kill,  FATAL(사망) → k_kill
_STATUS_TO_KILL = {
    Status.ALIVE: "alive",
    Status.M_KILL: "m_kill",
    Status.F_KILL: "f_kill",
    Status.MF_KILL: "mf_kill",
    Status.K_KILL: "k_kill",
    Status.MINOR: "alive",
    Status.SERIOUS: "mf_kill",
    Status.CRITICAL: "mf_kill",
    Status.FATAL: "k_kill",
}


def _kill_status(unit) -> str:
    """유닛 상태를 kill 분류(alive / m_kill / f_kill / mf_kill / k_kill)로 변환."""
    return _STATUS_TO_KILL[unit.status]


class Simulation:
    def __init__(self, config_file: str, time_scale: float = 1.0, sim_speed: float = 1.0,
                 show_detection: bool = False, show_eligible_targets: bool = False, show_fire: bool = False,
                 headless: bool = False, record_video: Optional[bool] = None):
        """시뮬레이션 초기화"""
        self.config = self._load_config(config_file)
        self.units = []
        self.events = []
        self.current_time = 0.0
        self.time_scale = time_scale
        self.sim_speed = sim_speed
        self.headless = headless

        self.show_detection = show_detection
        self.show_eligible_targets = show_eligible_targets
        self.show_fire = show_fire

        # 비디오 설정 — config 기본값, record_video 인자로 오버라이드 가능
        # (headless에서도 frames 저장 후 ffmpeg 합성 가능; SDL_VIDEODRIVER=dummy 렌더링)
        configured_record_video = self.config.get('video', {}).get('enabled', False)
        self.record_video = configured_record_video if record_video is None else record_video
        self.output_path = self.config.get('video', {}).get('output_path', 'simulation.mp4')
        self.video_fps = self.config.get('video', {}).get('fps', 30)

        # CSV 로깅 설정
        csv_cfg = self.config.get('csv', {})
        self.csv_enabled = csv_cfg.get('enabled', True)
        self.csv_path = csv_cfg.get('output_path', 'results/simulation.csv')
        self.money_csv_path = csv_cfg.get('money_output_path', 'results/money.csv')
        self.csv_rows: List[dict] = []
        self.money_csv_rows: List[dict] = []
        self.agent_id_map: Dict[int, str] = {}
        self.pixel_to_meter = self.config['simulation']['pixel_to_meter_scale']
        self.drone_elevation_m = self.config['simulation']['drone_elevation']
        self.terrain = Terrain()
        
        print(f"Headless mode: {'enabled' if self.headless else 'disabled'}")
        print(f"Video recording: {'enabled' if self.record_video else 'disabled'}")
        if self.record_video:
            print(f"Output path: {self.output_path}")
            print(f"Video FPS: {self.video_fps}")

        # 시뮬레이션 시간 설정
        self.max_time = self.config.get('max_time', 100.0)

        # 맵 크기 — config 기반
        self.map_width = self.config['simulation']['map_width_px']
        self.map_height = self.config['simulation']['map_height_px']

        # 모델 컴포넌트 초기화
        self.money_tracker = MoneyTracker(
            self.config.get('money', {}),
            self.config.get('platform_overrides', {}),
        )
        self.movement = Movement()
        self.fire = Fire(self.money_tracker)
        self.detect = Detect()

        # 명령 초기화
        self.commands = {
            Team.RED: Command.create_phase_1_command(Team.RED),
            Team.BLUE: Command.create_phase_1_command(Team.BLUE)
        }

        # 시각화 초기화
        # - headless 아닐 때: 항상 초기화 (윈도우 표시 + 옵션상 frames 저장)
        # - headless + record_video: frames 저장 위해서만 초기화 (윈도우는 SDL dummy로 숨김)
        # - headless + 비디오 없음: 완전 스킵 (가장 빠름)
        if not self.headless or self.record_video:
            self.visualizer = Visualizer(
                self.map_width, self.map_height,
                show_detection=self.show_detection,
                show_eligible_targets=self.show_eligible_targets,
                show_fire=self.show_fire,
                record_video=self.record_video,
                output_path=self.output_path,
                money_tracker=self.money_tracker,
            )
            self.visualizer.fire = self.fire
            self.visualizer.commands = self.commands
        else:
            self.visualizer = None
        
        # 초기 유닛 로드
        self._load_initial_units()

        # 지휘소(CP) 위치를 지형 장애물로 등록 — 다른 유닛이 통과 못 함, BFS도 우회
        for unit in self.units:
            if unit.unit_type == UnitType.COMMAND_POST:
                self.terrain.add_obstacle(unit.position, radius=2)  # ±2 셀 = 50m

        # 종료 조건용 — 초기 전투 유닛 수 스냅샷 (이후 모든 유닛 시작 시 살아있으므로
        # = "초기 사격 가능 수"와 동일). _check_termination이 현재 사격 가능 수와 비교.
        self._initial_combat_count = {
            Team.RED: sum(1 for u in self.units
                          if u.team == Team.RED and u.unit_type in COMBAT_UNIT_TYPES),
            Team.BLUE: sum(1 for u in self.units
                           if u.team == Team.BLUE and u.unit_type in COMBAT_UNIT_TYPES),
        }
        self._defeat_combat_ratio = float(
            self.config['simulation'].get('defeat_combat_ratio', 0.0))

        # agent_id 매핑 생성 (예: "blue_drn_1")
        self._build_agent_id_map()

        # 초기 이벤트 스케줄링
        self._schedule_initial_events()

    def _load_config(self, config_file: str) -> dict:
        """설정 파일 로드"""
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _load_initial_units(self):
        """초기 유닛 로드 — squad_id / is_leader / formation_offset 자동 할당.

        같은 (team, unit_type)의 positions 리스트를 squad_size 단위로 잘라서
        한 분대로 묶음. 각 분대의 0번 = 리더(진형 정점), 나머지는 진형 오프셋 보유.
        """
        unit_id = 0
        squad_sizes_cfg = self.config.get('squad_sizes', {})

        def create_units_for_team(team: Team, unit_type: UnitType, positions: List[List[int]], num_units: int):
            nonlocal unit_id
            available_positions = len(positions)
            if available_positions < num_units:
                print(f"Warning: Not enough positions for {team.value} {unit_type.value}. "
                      f"Requested {num_units}, but only {available_positions} positions available.")
                num_units = available_positions
            if num_units == 0:
                return

            # 이 (team, type)의 squad_size 와 진형 오프셋
            squad_size = squad_sizes_cfg.get(team.value, {}).get(unit_type.name, 1)
            offsets = get_formation_offsets(squad_size)
            abbr = UNIT_TYPE_ABBR.get(unit_type, 'unk')
            team_low = team.value.lower()

            for i, pos in enumerate(positions[:num_units]):
                position = (int(pos[0]), int(pos[1]))
                squad_idx = i // squad_size + 1            # 1-based 분대 번호
                in_squad_idx = i % squad_size              # 분대 내 위치
                squad_id = f"{team_low}_{abbr}_{squad_idx}"
                is_leader = (in_squad_idx == 0)
                offset = offsets[in_squad_idx] if in_squad_idx < len(offsets) else (0.0, 0.0)

                self.units.append(Unit(
                    id=unit_id,
                    team=team,
                    position=position,
                    unit_type=unit_type,
                    squad_id=squad_id,
                    is_leader=is_leader,
                    formation_offset=offset,
                ))
                unit_id += 1
        
        # RED 팀 유닛 생성
        create_units_for_team(Team.RED, UnitType.ARTILLERY, self.config['initial_positions']['RED']['ARTILLERY'], self.config['num_artillery_red'])
        create_units_for_team(Team.RED, UnitType.DRONE, self.config['initial_positions']['RED']['DRONE'], self.config['num_drone_red'])
        create_units_for_team(Team.RED, UnitType.TANK, self.config['initial_positions']['RED']['TANK'], self.config['num_tank_red'])
        create_units_for_team(Team.RED, UnitType.ANTI_TANK, self.config['initial_positions']['RED']['ANTI_TANK'], self.config['num_at_red'])
        create_units_for_team(Team.RED, UnitType.RIFLE, self.config['initial_positions']['RED']['RIFLE'], self.config['num_infantry_red'])
        create_units_for_team(Team.RED, UnitType.COMMAND_POST, self.config['initial_positions']['RED']['COMMAND_POST'], self.config['num_cp_red'])
        create_units_for_team(Team.RED, UnitType.SELF_DEST_DRONE, self.config['initial_positions']['RED']['SELF_DEST_DRONE'], self.config['num_self_dest_drone_red'])  # 자폭 드론

        # BLUE 팀 유닛 생성
        create_units_for_team(Team.BLUE, UnitType.ARTILLERY, self.config['initial_positions']['BLUE']['ARTILLERY'], self.config['num_artillery_blue'])
        create_units_for_team(Team.BLUE, UnitType.DRONE, self.config['initial_positions']['BLUE']['DRONE'], self.config['num_drone_blue'])
        create_units_for_team(Team.BLUE, UnitType.TANK, self.config['initial_positions']['BLUE']['TANK'], self.config['num_tank_blue'])
        create_units_for_team(Team.BLUE, UnitType.ANTI_TANK, self.config['initial_positions']['BLUE']['ANTI_TANK'], self.config['num_at_blue'])
        create_units_for_team(Team.BLUE, UnitType.RIFLE, self.config['initial_positions']['BLUE']['RIFLE'], self.config['num_infantry_blue'])
        create_units_for_team(Team.BLUE, UnitType.COMMAND_POST, self.config['initial_positions']['BLUE']['COMMAND_POST'], self.config['num_cp_blue'])
        create_units_for_team(Team.BLUE, UnitType.SELF_DEST_DRONE, self.config['initial_positions']['BLUE']['SELF_DEST_DRONE'], self.config['num_self_dest_drone_blue'])  # 자폭 드론

        # 초기 yaw를 진격방향(Phase 1 maneuver_objective)으로 정렬
        # — 진형 추종원이 시작 시 "빽도"하는 것 방지
        self._init_unit_yaw()

    def _init_unit_yaw(self):
        """팀별 Phase 1 maneuver_objective를 향한 방향으로 모든 유닛 yaw 초기 설정.

        리더 yaw가 0(동쪽 고정)이면 squad follower가 진형 오프셋대로 옆/뒤로 샜다가
        다시 정렬되어 후퇴처럼 보이는 문제 해결.
        """
        import math
        phases_cfg = self.config.get('phases', {})
        for team in (Team.RED, Team.BLUE):
            mo = (phases_cfg.get(team.value, {}).get('phase_1', {}) or {}).get('maneuver_objective')
            target = mo[0] if mo else None
            for u in self.units:
                if u.team != team:
                    continue
                if target is not None:
                    dx = target[0] - u.position[0]
                    dy = target[1] - u.position[1]
                else:
                    dx, dy = 0.0, (-1.0 if team == Team.RED else 1.0)
                if dx * dx + dy * dy > 1e-9:
                    u.yaw = math.atan2(dy, dx)

    def _build_agent_id_map(self):
        """유닛 id → 'team_abbr_idx' 형태의 agent_id 매핑 생성"""
        counters: Dict[tuple, int] = {}
        for unit in self.units:
            key = (unit.team, unit.unit_type)
            counters[key] = counters.get(key, 0) + 1
            team_str = unit.team.value.lower()
            abbr = UNIT_TYPE_ABBR[unit.unit_type]
            self.agent_id_map[unit.id] = f"{team_str}_{abbr}_{counters[key]}"

    def _record_tick(self, current_events: List[Event]):
        """현재 시점 모든 유닛의 상태 + 이번 tick에 발생한 이벤트 + 팀별 누적 자금을 CSV 버퍼에 기록"""
        if not self.csv_enabled:
            return

        # 이번 tick에 발생한 FIRE 이벤트 수집 (source_id → target_id)
        fire_events: Dict[int, int] = {}
        for ev in current_events:
            if ev.event_type == EventType.FIRE:
                fire_events[ev.source_id] = ev.target_id

        # 팀별 누적 자금 스냅샷 (RED, BLUE 한 줄씩)
        if self.money_tracker is not None:
            ts = round(self.current_time, 3)
            for team in (Team.RED, Team.BLUE):
                s = self.money_tracker.get_team_summary(team)
                self.money_csv_rows.append({
                    "timestamp": ts,
                    "team": team.value.lower(),
                    "fire_cost": round(s["fire"], 2),
                    "damage_cost": round(s["damage"], 2),
                    "total": round(s["total"], 2),
                })

        for unit in self.units:
            x_m = unit.position[0] * self.pixel_to_meter
            z_m = unit.position[1] * self.pixel_to_meter

            if unit.unit_type in (UnitType.DRONE, UnitType.SELF_DEST_DRONE):
                y_m = self.drone_elevation_m
            else:
                elev_pixels = self.terrain.get_elevation(
                    (int(unit.position[0]), int(unit.position[1]))
                )
                y_m = elev_pixels * self.pixel_to_meter

            # kill 분류: alive / m_kill / f_kill / mf_kill / k_kill
            status_str = _kill_status(unit)

            event_str = ""
            target_str = ""
            if unit.id in fire_events:
                event_str = "fire"
                tgt_id = fire_events[unit.id]
                target_str = self.agent_id_map.get(tgt_id, "")

            # 이번 tick에 상태를 변화시킨 객체의 agent_id (없으면 빈 문자열)
            damaged_by_str = ""
            if unit.damaged_by_id is not None:
                damaged_by_str = self.agent_id_map.get(unit.damaged_by_id, "")

            self.csv_rows.append({
                "timestamp": round(self.current_time, 3),
                "team": unit.team.value.lower(),
                "agent_type": UNIT_TYPE_NAME[unit.unit_type],
                "agent_id": self.agent_id_map[unit.id],
                "squad_id": unit.squad_id or "",
                "is_leader": int(unit.is_leader),
                "x": round(x_m, 2),
                "y": round(y_m, 2),
                "z": round(z_m, 2),
                "yaw": round(unit.yaw, 4),
                "alive": status_str,
                "event": event_str,
                "target": target_str,
                "damaged_by": damaged_by_str,
            })

    def _check_termination(self) -> Optional[str]:
        """전투 종료 여부 판단.

        Returns:
            "RED" / "BLUE" / "DRAW" — 종료 조건 충족
            None — 계속 진행

        한 팀의 (사격 가능 전투 유닛 / 초기 전투 유닛 수) 비율이
        config의 defeat_combat_ratio (기본 0.30 = 30%) 미만이면 그 팀 패배.
        ratio = 0.0 이면 전멸까지 가야 종료.
        """
        red_can_fire = sum(
            1 for u in self.units
            if u.team == Team.RED
            and u.unit_type in COMBAT_UNIT_TYPES
            and u.can_fire()
        )
        blue_can_fire = sum(
            1 for u in self.units
            if u.team == Team.BLUE
            and u.unit_type in COMBAT_UNIT_TYPES
            and u.can_fire()
        )
        red_init  = self._initial_combat_count[Team.RED]  or 1
        blue_init = self._initial_combat_count[Team.BLUE] or 1
        red_ratio  = red_can_fire  / red_init
        blue_ratio = blue_can_fire / blue_init
        thr = self._defeat_combat_ratio

        red_defeated  = red_ratio  < thr
        blue_defeated = blue_ratio < thr
        if red_defeated and blue_defeated:
            return "DRAW"
        if red_defeated:
            return "BLUE"
        if blue_defeated:
            return "RED"
        return None

    def _save_csv(self, quiet: bool = False):
        """버퍼된 CSV 행을 파일로 저장 (simulation.csv + money.csv)"""
        if not self.csv_enabled or not self.csv_rows:
            return

        out_dir = os.path.dirname(self.csv_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        fieldnames = ["timestamp", "team", "agent_type", "agent_id",
                      "squad_id", "is_leader",
                      "x", "y", "z", "yaw", "alive", "event", "target", "damaged_by"]
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.csv_rows)
        if not quiet:
            print(f"CSV saved: {self.csv_path} ({len(self.csv_rows)} rows)")

        # money.csv 저장 — 매 tick 팀별 누적 자금 추이
        if self.money_csv_rows:
            money_dir = os.path.dirname(self.money_csv_path)
            if money_dir:
                os.makedirs(money_dir, exist_ok=True)
            money_fields = ["timestamp", "team", "fire_cost", "damage_cost", "total"]
            with open(self.money_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=money_fields)
                writer.writeheader()
                writer.writerows(self.money_csv_rows)
            if not quiet:
                print(f"Money CSV saved: {self.money_csv_path} ({len(self.money_csv_rows)} rows)")

    def _get_command_for_team(self, team: Team) -> Command:
        """팀에 대한 명령 반환"""
        return self.commands[team]

    def _schedule_initial_events(self):
        """초기 이벤트 스케줄링"""
        # 먼저 모든 유닛의 탐지 상태와 사격 가능 타겟 목록 업데이트
        for unit in self.units:
            unit.clear_targets()  # 이전 탐지 목록 초기화
        for unit in self.units:
            self.detect.update_detection(unit, self.units, self.sim_speed)
            self.fire.update_eligible_targets(unit, self.units)

        # 이벤트 스케줄링
        for unit in self.units:
            command = self._get_command_for_team(unit.team)
            # 이동 이벤트 스케줄링
            if unit.can_move():
                # 드론·자폭드론은 TAI로 이동, 그 외엔 maneuver_objective가 있을 때만 이동
                if unit.unit_type in (UnitType.DRONE, UnitType.SELF_DEST_DRONE) or command.maneuver_objective is not None:
                    event = self.movement.move(unit, command, self.current_time, self.units, self.sim_speed)
                    if event:
                        heapq.heappush(self.events, event)
            # 사격 이벤트 스케줄링
            if unit.can_fire():
                event = self.fire.schedule_fire_event(unit, self.units, command, self.current_time)
                if event:
                    heapq.heappush(self.events, event)

    def handle_event(self, event: Event) -> Optional[Event]:
        """이벤트 처리
        MOVE 이벤트는 move 메서드로 예약된 이벤트이고, move 메서드에서 unit.action와 unit.objective를 업데이트 해준다.
                    objective와 충분히 가까우면 unit.action을 STOP으로 하고, 멀면 MOVE로 업데이트 해준다.
        FIRE 이벤트는 schedule_fire_event 메서드로 예약된 이벤트이고
                     schedule_fire_event 메서드에서 unit.action을 FIRE로 업데이트 해준다.
                     fire 메서드는 사격을 실행하여 성공시 target의 상태를 업데이트 하고 unit.action을 STOP으로 업데이트 해준다.
        """
        if event.event_type == EventType.MOVE:
            unit = next((u for u in self.units if u.id == event.source_id), None)
            if unit and unit.can_move():
                # 유닛의 위치 업데이트
                unit.update_position(event.position)

        elif event.event_type == EventType.FIRE:
            attacker = next((u for u in self.units if u.id == event.source_id), None)
            target = next((u for u in self.units if u.id == event.target_id), None)
            if attacker and target:
                return self.fire.fire(attacker, target, self.units, self.commands[attacker.team], self.current_time)
        return None

    def print_money_summary(self):
        """Print final money totals for both teams."""
        print("Money summary:")
        print(self.money_tracker.format_team_summary(Team.RED))
        print(self.money_tracker.format_team_summary(Team.BLUE))

    def run_simulation(self, max_time: float = None, hold_open: bool = True):
        """시뮬레이션 실행"""
        if max_time is None:
            max_time = self.max_time
            
        print(f"Starting simulation with max_time: {max_time}", flush=True)
        start_wall_time = time.perf_counter()
        tick_count = 0
        total_ticks = max(1, int((max_time - self.current_time + self.sim_speed - 1e-9) / self.sim_speed))
        last_visualization_time = 0.0
        visualization_interval = 1 / self.time_scale  # Match simulation speed with visualization

        # 프레임 디렉토리 초기화 (Windows read-only 폴더 안전 처리)
        if self.record_video:
            _reset_directory(self.visualizer.frame_dir)


        while self.current_time < max_time:
            tick_count += 1
            if tick_count % 10 == 0:
                elapsed = time.perf_counter() - start_wall_time
                reported_time = min(max_time, self.current_time + self.sim_speed)
                progress = min(100.0, (reported_time / max_time) * 100.0) if max_time else 0.0
                print(
                    f"Progress: tick {tick_count}/{total_ticks} "
                    f"(t={reported_time:.1f}/{max_time:.1f}s, {progress:.1f}%) "
                    f"elapsed={elapsed:.1f}s",
                    flush=True,
                )
            # pygame 이벤트 처리 (headless가 아닐 때만)
            if not self.headless:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._save_csv()
                        self.visualizer.close()
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_SPACE:
                            self.visualizer.paused = not self.visualizer.paused

                if self.visualizer.paused:
                    self.visualizer.show_pause_screen()
                    continue

            # 이번 tick에 상태 변화시킨 공격자 정보 클리어 (이번 tick 이벤트가 새로 채움)
            for u in self.units:
                u.damaged_by_id = None

            # 현재 시간에 발생할 모든 이벤트 수집
            current_events = []
            while self.events and self.events[0].time <= self.current_time:
                event = heapq.heappop(self.events)
                current_events.append(event)
            
            # 현재 시간의 모든 이벤트 처리
            for event in current_events:
                next_event = self.handle_event(event)
                if next_event:
                    heapq.heappush(self.events, next_event)

            # 탐지/사격가능은 모든 이벤트 처리 후 1번만 갱신
            # (handle_event는 detection을 안 씀 — fire는 event.target_id로 직접 처리)
            # 이벤트마다 반복하던 N²×M 비용 → N²로 감소 (수 ~ 수십 배 가속)
            if current_events:
                for unit in self.units:
                    unit.clear_targets()
                for unit in self.units:
                    self.detect.update_detection(unit, self.units, self.sim_speed)
                for team in [Team.RED, Team.BLUE]:
                    self.detect.share_info(team, self.units)
                for unit in self.units:
                    self.fire.update_eligible_targets(unit, self.units)

            # 지휘소 상황평가
            for team in [Team.RED, Team.BLUE]:
                command_posts = [unit for unit in self.units if unit.team == team and unit.unit_type == UnitType.COMMAND_POST]
                if command_posts:  # 지휘소가 있는 경우에만
                    self.commands[team].evaluate_situation(command_posts[0], self.units)  # 지휘소와 모든 유닛 전달
                    
                    # 작전단계가 변경된 경우 유닛들의 objective 업데이트
                    command = self.commands[team]
                    if command.maneuver_objective:
                        for unit in self.units:
                            if unit.team == team :
                                unit.update_objective(command.maneuver_objective[0])
                                unit.update_action(Action.MOVE)
        
            # 다음 이벤트 예약
            for unit in self.units:
                command = self._get_command_for_team(unit.team)
                
                # (a) 사격 이벤트 예약
                if unit.action != Action.FIRE and unit.eligible_target_list:
                    fire_event = self.fire.schedule_fire_event(unit, self.units, command, self.current_time)
                    if fire_event:
                        unit.update_action(Action.FIRE)
                        heapq.heappush(self.events, fire_event)
                
                # (b) 이동 이벤트 예약 — objective(이동 목표)가 있을 때만 이동
                move_event = None
                if unit.unit_type == UnitType.TANK:  # 전차는 이동사격: 목표 있으면 사격 중에도 계속 전진
                    if unit.objective:
                        move_event = self.movement.move(unit, command, self.current_time, self.units, self.sim_speed)
                elif unit.action != Action.FIRE and unit.objective:
                    move_event = self.movement.move(unit, command, self.current_time, self.units, self.sim_speed)
                if move_event:
                    heapq.heappush(self.events, move_event)

            # CSV 기록 (매 tick 모든 유닛 상태 + 이번 tick의 FIRE 이벤트)
            self._record_tick(current_events)
            if tick_count % 100 == 0:
                self._save_csv(quiet=True)

            # 조기 종료 검사 — 한 팀의 전투 가능 유닛이 0이 되면 종료
            winner = self._check_termination()
            if winner is not None:
                print(f"Simulation ended at t={self.current_time:.1f}s — winner: {winner}")
                break

            # 시각화 업데이트
            # - headless + record_video: 화면 표시는 없지만 draw_frame으로 frames 저장 (sleep 없이 빠르게)
            # - headless + 비디오 없음: 완전 스킵
            # - 비-headless: 화면 표시 + 옵션상 frames 저장 + 실시간 sleep
            should_render = (
                self.visualizer is not None
                and self.current_time - last_visualization_time >= visualization_interval
            )
            if should_render:
                self.visualizer.current_time = self.current_time
                self.visualizer.last_frame_time = last_visualization_time
                self.visualizer.events = current_events
                self.visualizer.draw_frame(self.units, self.current_time)
                last_visualization_time = self.current_time
                if not self.headless:
                    time.sleep(visualization_interval)

            # 시간 증가
            self.current_time += self.sim_speed


        # 시뮬레이션 종료 후 마지막 상태 표시
        if not self.headless:
            self.visualizer.current_time = self.current_time
            self.visualizer.draw_frame(self.units, self.current_time)

        # CSV 저장
        self._save_csv()

        # 비디오 녹화가 활성화된 경우 비디오 생성
        if self.record_video:
            print("Simulation ended, creating video...")
            self.visualizer.create_video(self.output_path, self.video_fps)
            # 비디오 생성 후 프레임 디렉토리 정리 (Windows read-only 안전 처리)
            _safe_rmtree(self.visualizer.frame_dir)

        self.print_money_summary()
        if not hold_open:
            if self.visualizer is not None:
                self.visualizer.close()
            return

        # 창 유지 — headless에서는 즉시 종료
        if self.headless:
            return

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.visualizer.close()
                    return
            time.sleep(0.1)

        

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='War Game Simulation')
    parser.add_argument('--time-scale', type=float, default=5.0, help='Video speed')
    parser.add_argument('--detection', type=str, choices=['T', 'F'], default='F', help='Show detection lines (T/F)')
    parser.add_argument('--eligible_TL', type=str, choices=['T', 'F'], default='F', help='Show eligible target lines (T/F)')
    parser.add_argument('--fire', type=str, choices=['T', 'F'], default='F', help='Show fire lines (T/F)')
    parser.add_argument('--sim_speed', type=float, default=1.0, help='Simulation speed')
    parser.add_argument('--max-time', type=float, default=None, help='Override max simulation time')
    parser.add_argument('--no-hold', action='store_true', help='Close the simulation window at the end')
    parser.add_argument('--no-video', action='store_true', help='Disable video recording for this run')
    parser.add_argument('--headless', action='store_true', help='Disable visualization & real-time pacing (CSV-only fast mode)')

    args = parser.parse_args()

    simulation = Simulation(
        "config.yaml",
        time_scale=args.time_scale,
        show_detection=(args.detection == 'T'),
        show_eligible_targets=(args.eligible_TL == 'T'),
        show_fire=(args.fire == 'T'),
        sim_speed=args.sim_speed,
        headless=args.headless,
        record_video=False if args.no_video else None,
    )
    simulation.run_simulation(max_time=args.max_time, hold_open=not args.no_hold)
