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
import heapq
import argparse
import os
class Simulation:
    def __init__(self, config_file: str, time_scale: float = 1.0, sim_speed: float = 1.0, 
                 show_detection: bool = False, show_eligible_targets: bool = False, show_fire: bool = False):
        """시뮬레이션 초기화"""
        self.config = self._load_config(config_file)
        self.units = []
        self.events = []
        self.current_time = 0.0
        self.time_scale = time_scale
        self.sim_speed = sim_speed

        self.show_detection = show_detection
        self.show_eligible_targets = show_eligible_targets
        self.show_fire = show_fire
        
        # 비디오 설정
        self.record_video = self.config.get('video', {}).get('enabled', False)
        self.output_path = self.config.get('video', {}).get('output_path', 'simulation.mp4')
        self.video_fps = self.config.get('video', {}).get('fps', 30)
        
        print(f"Video recording: {'enabled' if self.record_video else 'disabled'}")  # 로그 추가
        if self.record_video:
            print(f"Output path: {self.output_path}")  # 로그 추가
            print(f"Video FPS: {self.video_fps}")  # 로그 추가
        
        # 시뮬레이션 시간 설정
        self.max_time = self.config.get('max_time', 100.0)
        
        # 모델 컴포넌트 초기화
        self.movement = Movement()
        self.fire = Fire()
        self.detect = Detect()
        
        # 명령 초기화
        self.commands = {
            Team.RED: Command.create_phase_1_command(Team.RED),
            Team.BLUE: Command.create_phase_1_command(Team.BLUE)
        }
        
        # 시각화 초기화
        self.visualizer = Visualizer(800, 450, show_detection=self.show_detection, show_eligible_targets=self.show_eligible_targets, show_fire=self.show_fire, record_video=self.record_video, output_path=self.output_path)
        self.visualizer.fire = self.fire  # Fire 객체 공유
        self.visualizer.commands = self.commands  # Command 정보 공유
        
        # 초기 유닛 로드
        self._load_initial_units()
        
        # 초기 이벤트 스케줄링
        self._schedule_initial_events()

    def _load_config(self, config_file: str) -> dict:
        """설정 파일 로드"""
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)

    def _load_initial_units(self):
        """초기 유닛 로드"""
        unit_id = 0
        
        def create_units_for_team(team: Team, unit_type: UnitType, positions: List[List[int]], num_units: int):
            nonlocal unit_id
            # 사용 가능한 위치 수 확인
            available_positions = len(positions)
            if available_positions < num_units:
                print(f"Warning: Not enough positions for {team.value} {unit_type.value}. Requested {num_units}, but only {available_positions} positions available.")
                num_units = available_positions
            
            # 지정된 수만큼 위치를 가져옴
            for pos in positions[:num_units]:
                position = (int(pos[0]), int(pos[1]))
                self.units.append(Unit(
                    id=unit_id,
                    team=team,
                    position=position,
                    unit_type=unit_type
                ))
                unit_id += 1
        
        # RED 팀 유닛 생성
        create_units_for_team(Team.RED, UnitType.ARTILLERY, self.config['initial_positions']['RED']['ARTILLERY'], self.config['num_artillery_red'])
        create_units_for_team(Team.RED, UnitType.DRONE, self.config['initial_positions']['RED']['DRONE'], self.config['num_drone_red'])
        create_units_for_team(Team.RED, UnitType.TANK, self.config['initial_positions']['RED']['TANK'], self.config['num_tank_red'])
        create_units_for_team(Team.RED, UnitType.ANTI_TANK, self.config['initial_positions']['RED']['ANTI_TANK'], self.config['num_at_red'])
        create_units_for_team(Team.RED, UnitType.RIFLE, self.config['initial_positions']['RED']['RIFLE'], self.config['num_infantry_red'])
        create_units_for_team(Team.RED, UnitType.COMMAND_POST, self.config['initial_positions']['RED']['COMMAND_POST'], self.config['num_cp_red'])
        
        # BLUE 팀 유닛 생성
        create_units_for_team(Team.BLUE, UnitType.ARTILLERY, self.config['initial_positions']['BLUE']['ARTILLERY'], self.config['num_artillery_blue'])
        create_units_for_team(Team.BLUE, UnitType.DRONE, self.config['initial_positions']['BLUE']['DRONE'], self.config['num_drone_blue'])
        create_units_for_team(Team.BLUE, UnitType.TANK, self.config['initial_positions']['BLUE']['TANK'], self.config['num_tank_blue'])
        create_units_for_team(Team.BLUE, UnitType.ANTI_TANK, self.config['initial_positions']['BLUE']['ANTI_TANK'], self.config['num_at_blue'])
        create_units_for_team(Team.BLUE, UnitType.RIFLE, self.config['initial_positions']['BLUE']['RIFLE'], self.config['num_infantry_blue'])
        create_units_for_team(Team.BLUE, UnitType.COMMAND_POST, self.config['initial_positions']['BLUE']['COMMAND_POST'], self.config['num_cp_blue'])

    def _get_command_for_team(self, team: Team) -> Command:
        """팀에 대한 명령 반환"""
        return self.commands[team]

    def _schedule_initial_events(self):
        """초기 이벤트 스케줄링"""
        # 먼저 모든 유닛의 탐지 상태와 사격 가능 타겟 목록 업데이트
        for unit in self.units:
            unit.clear_targets()  # 이전 탐지 목록 초기화
        for unit in self.units:
            self.detect.update_detection(unit, self.units)
            self.fire.update_eligible_targets(unit, self.units)

        # 이벤트 스케줄링
        for unit in self.units:
            command = self._get_command_for_team(unit.team)
            # 이동 이벤트 스케줄링
            if unit.can_move():
                # 드론은 TAI로 이동, 다른 유닛은 maneuver_objective가 있을 때만 이동
                if unit.unit_type == UnitType.DRONE or command.maneuver_objective is not None:
                    event = self.movement.move(unit, command, self.current_time, self.units)
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

    def run_simulation(self, max_time: float = None):
        """시뮬레이션 실행"""
        if max_time is None:
            max_time = self.max_time
            
        print(f"Starting simulation with max_time: {max_time}")
        last_visualization_time = 0.0
        visualization_interval = 1 / self.time_scale  # Match simulation speed with visualization

        # 프레임 디렉토리 초기화
        if self.record_video:
            import shutil
            if os.path.exists(self.visualizer.frame_dir):
                shutil.rmtree(self.visualizer.frame_dir)
            os.makedirs(self.visualizer.frame_dir)


        while self.current_time < max_time:
            # pygame 이벤트 처리
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.visualizer.close()
                    return 
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self.visualizer.paused = not self.visualizer.paused


            if self.visualizer.paused:
                self.visualizer.show_pause_screen()
                continue

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
                
                # 각 이벤트 처리 후 모든 유닛의 탐지 상태와 사격 가능 타겟 목록 업데이트
                for unit in self.units:
                    unit.clear_targets()  # 이전 탐지 목록 초기화
                for unit in self.units:
                    self.detect.update_detection(unit, self.units)
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
                
                # (b) 이동 이벤트 예약
                if unit.unit_type == UnitType.TANK: #Tank는 이동사격 가능
                    if unit.objective:
                        move_event = self.movement.move(unit, command, self.current_time, self.units)
                    if move_event:
                        heapq.heappush(self.events, move_event)
                elif unit.action != Action.FIRE and unit.objective:
                    move_event = self.movement.move(unit, command, self.current_time, self.units)
                    if move_event:
                        heapq.heappush(self.events, move_event)

            # 시각화 업데이트 (일정 간격으로만)
            if self.current_time - last_visualization_time >= visualization_interval:
                self.visualizer.current_time = self.current_time
                self.visualizer.last_frame_time = last_visualization_time
                self.visualizer.events = current_events  # 현재 시간의 이벤트들을 전달
                self.visualizer.draw_frame(self.units, self.current_time)
                last_visualization_time = self.current_time
                time.sleep(visualization_interval)

            # 시간 증가
            self.current_time += self.sim_speed

            
        # 시뮬레이션 종료 후 마지막 상태 표시
        self.visualizer.current_time = self.current_time
        self.visualizer.draw_frame(self.units, self.current_time)
        
        # 비디오 녹화가 활성화된 경우 비디오 생성
        if self.record_video:
            print("Simulation ended, creating video...")
            self.visualizer.create_video(self.output_path, self.video_fps)
            # 비디오 생성 후 프레임 디렉토리 정리
            if os.path.exists(self.visualizer.frame_dir):
                shutil.rmtree(self.visualizer.frame_dir)
        
        # 창 유지
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

    args = parser.parse_args()
    
    simulation = Simulation(
        "config.yaml",  # 기본 설정 파일 사용
        time_scale=args.time_scale,
        show_detection=(args.detection == 'T'),
        show_eligible_targets=(args.eligible_TL == 'T'),
        show_fire=(args.fire == 'T'),
        sim_speed=args.sim_speed
    )
    simulation.run_simulation() 
