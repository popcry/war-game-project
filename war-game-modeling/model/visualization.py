import pygame
import os
import sys
import math
import subprocess
from typing import List, Dict, Tuple, Optional
from .unit import Unit, Team, UnitType, Status
from .terrain import Terrain
from .fire import Fire
from .event import EventType
from .function import calculate_distance
import yaml





# Sound 삽입
# 초기화 (visualization.py 상단에 추가)
pygame.mixer.init()
#pygame.mixer.music.set_volume(1.0)  # 최대 볼륨

# 사운드 파일 로딩
sound_files = {
    'RIFLE': pygame.mixer.Sound(os.path.join('database', 'rifle.wav')),
    'TANK': pygame.mixer.Sound(os.path.join('database', 'tank.wav')),
    'ARTILLERY': pygame.mixer.Sound(os.path.join('database', 'artillery.wav')),
}

# 유닛 유형별 매핑
unit_sound_map = {
    UnitType.RIFLE: 'RIFLE',
    UnitType.COMMAND_POST: 'RIFLE',
    UnitType.ANTI_TANK: 'TANK',
    UnitType.TANK: 'TANK',
    UnitType.ARTILLERY: 'ARTILLERY'

}


# Load config
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

class Visualizer:
    def __init__(self, width: int = 1600, height: int = 900, show_detection: bool = False, show_eligible_targets: bool = False, show_fire: bool = False, record_video: bool = False, output_path: str = "simulation.mp4"):
        pygame.init()
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("War Game Simulation")
        self.show_detection = show_detection
        self.show_eligible_targets = show_eligible_targets
        self.show_fire = show_fire
        
        # 이벤트와 시간 정보
        self.events = []
        self.current_time = 0.0
        self.last_frame_time = 0.0  # 이전 프레임 시간 추가
        self.paused = False
        # Frame saving settings
        self.frame_dir = "frames"
        self.frame_count = 0
        self.save_frames = record_video
        self.output_path = output_path
        os.makedirs(self.frame_dir, exist_ok=True)
        
        # Load background image
        self.background = pygame.image.load(os.path.join("database", "background.png"))
        self.background = pygame.transform.scale(self.background, (width, height))
        
        # Colors
        self.colors = {
            Team.RED: (255, 0, 0),
            Team.BLUE: (0, 0, 255),
            'background': (255, 255, 255),  # 흰색
            'grid': (200, 200, 200),    # 회색
            'text': (0, 0, 0),          # 검은색
            'panel_bg': (255, 255, 255)    # 패널 배경색
        }
        
        # 폰트 초기화
        pygame.font.init()
        self.font = pygame.font.SysFont('malgungothic', 12)
        self.panel_font = pygame.font.SysFont('malgungothic', 16)
        self.team_count_font = pygame.font.SysFont('malgungothic', 12)  # 팀 카운트용 작은 폰트 추가
        
        # 시뮬레이션 속도 조절
        self.update_interval = 1.0  # 1초마다 업데이트
        self.last_update = 0
        
        # Unit symbols
        self.symbols = {
            UnitType.RIFLE: "I",
            UnitType.ANTI_TANK: "AT",
            UnitType.TANK: "T",
            UnitType.ARTILLERY: "A",
            UnitType.DRONE: "D",
            UnitType.COMMAND_POST: "CP"
        }
        
        # 유닛 크기
        self.unit_size = 10

        self.terrain = Terrain()
        self.fire = Fire()

    def draw_frame(self, units: List[Unit], current_time: float):
        """한 프레임 그리기"""
        # 배경 이미지 그리기
        self.screen.blit(self.background, (0, 0))
        
        # 오래된 이벤트 정리 (현재 시간보다 1초 이상 이전의 이벤트 제거)
        self.events = [event for event in self.events if current_time - event.time <= 1.0]
         
        # 유닛 그리기
        for unit in units:
            self.draw_unit(unit)
            
            # 탐지선 그리기
            if self.show_detection:
                self.draw_detection_lines(unit, units)
            
            # 사격 가능 타겟선 그리기
            if self.show_eligible_targets:
                self.draw_eligible_target_lines(unit, units)
            
            # 사격선 그리기
            if self.show_fire:
                self.draw_fire_lines(unit, units)
        
        # 현재 시간 표시
        font = pygame.font.Font(None, 36)
        time_text = font.render(f"Time: {current_time:.1f}", True, (0, 0, 0))
        self.screen.blit(time_text, (650, 10))
        
        # Draw unit count panel
        self.draw_unit_count_panel(units)
        
        pygame.display.flip()
        
        # 비디오 녹화가 활성화된 경우 프레임 저장
        if self.save_frames:
            self.save_frame()

    def draw_unit_count_panel(self, units: List[Unit]):
        """생존 유닛 수를 보여주는 패널 그리기"""
        # 패널 크기와 위치 설정
        panel_width = 200
        panel_height = 180  # 높이를 늘려서 로그 공간 확보
        panel_x = 10  # 왼쪽으로 이동
        panel_y = 10
        
        # 패널 배경 그리기
        panel_surface = pygame.Surface((panel_width, panel_height))
        panel_surface.fill(self.colors['panel_bg'])
        panel_surface.set_alpha(200)  # 반투명 효과
        self.screen.blit(panel_surface, (panel_x, panel_y))
        
        # 각 팀의 생존 유닛 수와 전체 유닛 수 계산
        red_count = sum(1 for unit in units if unit.team == Team.RED and unit.status.value in ["ALIVE", "M_KILL"])
        blue_count = sum(1 for unit in units if unit.team == Team.BLUE and unit.status.value in ["ALIVE", "M_KILL"])
        red_count_total = sum(1 for unit in units if unit.team == Team.RED)
        blue_count_total = sum(1 for unit in units if unit.team == Team.BLUE)
        
        # 패널 제목 렌더링
        title_text = self.panel_font.render("생존유닛 수", True, (0, 0, 0))
        self.screen.blit(title_text, (panel_x + 10, panel_y + 5))
        
        # 텍스트 렌더링 (작은 폰트 사용)
        red_text = self.team_count_font.render(f"Red : {red_count} / {red_count_total}", True, self.colors[Team.RED])
        blue_text = self.team_count_font.render(f"Blue : {blue_count} / {blue_count_total}", True, self.colors[Team.BLUE])
        
        # 텍스트 위치 계산
        red_text_x = panel_x + 10
        red_text_y = panel_y + 30
        blue_text_x = panel_x + 10
        blue_text_y = panel_y + 60
        
        # 텍스트 그리기
        self.screen.blit(red_text, (red_text_x, red_text_y))
        self.screen.blit(blue_text, (blue_text_x, blue_text_y))
        
        # 로그 영역 구분선 그리기
        separator_y = panel_y + 90
        pygame.draw.line(
            self.screen,
            (100, 100, 100),  # 회색 구분선
            (panel_x + 5, separator_y),
            (panel_x + panel_width - 5, separator_y),
            1
        )

        # 작전단계 표시
        phase_title = self.panel_font.render("작전단계", True, (0, 0, 0))
        self.screen.blit(phase_title, (panel_x + 10, separator_y + 10))

        # 작전단계 한글 이름 매핑
        phase_names = {
            "Deep_fires": "1단계(종심깊은 화력운용)",
            "Degrade_enemy_forces": "2단계(적 전투력 약화)",
            "CLOSE_COMBAT": "3단계(근접전투)"
        }

        # RED 팀 작전단계
        red_phase = phase_names.get(self.commands[Team.RED].phase.name, self.commands[Team.RED].phase.name)
        red_phase_text = self.team_count_font.render(f"Red : {red_phase}", True, self.colors[Team.RED])
        self.screen.blit(red_phase_text, (panel_x + 10, separator_y + 35))

        # BLUE 팀 작전단계
        blue_phase = phase_names.get(self.commands[Team.BLUE].phase.name, self.commands[Team.BLUE].phase.name)
        blue_phase_text = self.team_count_font.render(f"Blue : {blue_phase}", True, self.colors[Team.BLUE])
        self.screen.blit(blue_phase_text, (panel_x + 10, separator_y + 60))

    def draw_unit(self, unit: Unit):
        """유닛 그리기"""
        # 유닛 위치 계산
        x, y = unit.position
        
        # 유닛 색상 설정
        if unit.team == Team.RED:
            base_color = (255, 0, 0)  # 빨간색
            m_kill_color = (255, 165, 0)  # 주황색
        else:  # BLUE
            base_color = (0, 0, 255)  # 파란색
            m_kill_color = (100, 149, 237)  # 하늘색
            
        # 상태에 따른 색상 선택
        if unit.status == Status.ALIVE:
            fill_color = base_color
        elif unit.status in [Status.M_KILL, Status.MINOR]:
            fill_color = m_kill_color
        else:
            # 심각한 피해 상태는 테두리만 그리기
            pygame.draw.circle(self.screen, base_color, (x, y), 10, 2)  # 두께 2의 테두리
            # 유닛 심볼 표시 (검은색)
            font = pygame.font.Font(None, 20)
            text = font.render(self.symbols[unit.unit_type], True, (0, 0, 0))
            text_rect = text.get_rect(center=(x, y))
            self.screen.blit(text, text_rect)
            return
            
        # 일반 상태는 채워서 그리기
        pygame.draw.circle(self.screen, fill_color, (x, y), 10)
        pygame.draw.circle(self.screen, base_color, (x, y), 10, 2)  # 두께 2의 테두리
        
        # 유닛 심볼 표시 (흰색)
        font = pygame.font.Font(None, 20)
        text = font.render(self.symbols[unit.unit_type], True, (255, 255, 255))
        text_rect = text.get_rect(center=(x, y))
        self.screen.blit(text, text_rect)

    def draw_detection_lines(self, unit: Unit, all_units: List[Unit]):
        """탐지된 적을 점선으로 표시"""
        if unit.status.value not in ["ALIVE", "M_KILL","MINOR"]:
            return
            
        for target_id in unit.target_list:
            target = next((u for u in all_units if u.id == target_id), None)
            if target and target.status.value in ["ALIVE", "M_KILL"]:
                start_pos = unit.position
                end_pos = target.position
                if unit.team == Team.RED:
                    start_pos = (start_pos[0]-5, start_pos[1] - 5)
                    end_pos = (end_pos[0]-5, end_pos[1] - 5)
                line_color = (255, 165, 0) if unit.team == Team.RED else (100, 149, 237)
                self._draw_dashed_line(start_pos, end_pos, line_color)

    def draw_eligible_target_lines(self, unit: Unit, all_units: List[Unit]):
        """사격 가능한 타겟을 점선으로 표시"""
        if unit.status.value not in ["ALIVE", "M_KILL","MINOR"]:
            return
            
        for target_id in unit.eligible_target_list:
            target = next((u for u in all_units if u.id == target_id), None)
            if target and target.status.value in ["ALIVE", "M_KILL"]:
                start_pos = unit.position
                end_pos = target.position
                if unit.team == Team.RED:
                    start_pos = (start_pos[0]-5, start_pos[1] - 5)
                    end_pos = (end_pos[0]-5, end_pos[1] - 5)
                line_color = (255, 165, 0) if unit.team == Team.RED else (100, 149, 237)
                self._draw_dashed_line(start_pos, end_pos, line_color)

    def draw_fire_lines(self, unit: Unit, all_units: List[Unit]):
        """사격선 그리기"""    
        if unit.status.value not in ["ALIVE", "M_KILL","MINOR"]:
            return
            
        # 이전 프레임부터 현재 프레임까지의 사격 이벤트에 대해 선 그리기
        for event in self.events:
            if (event.event_type == EventType.FIRE and 
                event.source_id == unit.id and 
                self.last_frame_time < event.time <= self.current_time):  # 이전 프레임 이후부터 현재까지의 이벤트
                target = next((u for u in all_units if u.id == event.target_id), None)
                if target and target.status in [Status.ALIVE, Status.M_KILL, Status.MINOR]:
                    # 사격선 색상 설정 (팀 색상)
                    color = self.colors[unit.team]
                    
                    # Artillery인 경우
                    if unit.unit_type == UnitType.ARTILLERY:
                        # 탄착지점 계산
                        distance = calculate_distance(unit, target)
                        impact_point = self.fire.calculate_impact_point(target.position, distance)
                        
                        # 사격선 그리기 (포병 -> 탄착지점)
                        pygame.draw.line(
                            self.screen,
                            color,
                            unit.position,
                            impact_point,
                            3  # 선 두께
                        )
                        
                        # 살상반경 원 그리기 (반투명 주황색)
                        lethal_radius = config['simulation']['lethal_radius']  # 치사반경 (m)
                        PIXEL_TO_METER_SCALE = config['simulation']['pixel_to_meter_scale']
                        lethal_radius_pixels = 2*lethal_radius / PIXEL_TO_METER_SCALE  # 픽셀 단위로 변환 (시각화 목적으로 2배로 키웠음)
                        lethal_surface = pygame.Surface((lethal_radius_pixels * 2, lethal_radius_pixels * 2), pygame.SRCALPHA)
                        pygame.draw.circle(
                            lethal_surface,
                            (255, 165, 0, 128),  # RGBA: 주황색, 50% 투명도
                            (lethal_radius_pixels, lethal_radius_pixels),
                            lethal_radius_pixels
                        )
                        self.screen.blit(
                            lethal_surface,
                            (impact_point[0] - lethal_radius_pixels, impact_point[1] - lethal_radius_pixels)
                        )
                        
                        # 화살표 표시 (포병 -> 탄착지점)
                        self.draw_arrow(unit.position, impact_point, color)
                        sound_key = unit_sound_map.get(unit.unit_type)
                        if sound_key:
                            sound_files[sound_key].play()
                    else:
                        # 일반 유닛의 경우 기존처럼 처리
                        pygame.draw.line(
                            self.screen,
                            color,
                            unit.position,
                            target.position,
                            3  # 선 두께
                        )
                        self.draw_arrow(unit.position, target.position, color)

                        sound_key = unit_sound_map.get(unit.unit_type)
                        if sound_key:
                            sound_files[sound_key].play()



    def _draw_dashed_line(self, start_pos, end_pos, line_color):
        dash_length = 5
        gap_length = 5
        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        distance = math.sqrt(dx*dx + dy*dy)
        if distance > 0:
            steps = int(distance / (dash_length + gap_length))
            for i in range(steps):
                start = (
                    start_pos[0] + (dx * i * (dash_length + gap_length)) / distance,
                    start_pos[1] + (dy * i * (dash_length + gap_length)) / distance
                )
                end = (
                    start_pos[0] + (dx * (i * (dash_length + gap_length) + dash_length)) / distance,
                    start_pos[1] + (dy * (i * (dash_length + gap_length) + dash_length)) / distance
                )
                pygame.draw.line(self.screen, line_color, start, end, 1)
                
    def draw_arrow(self, start: Tuple[int, int], end: Tuple[int, int], color: Tuple[int, int, int]):
        """화살표 그리기"""
        # 화살표 크기 계산
        arrow_size = 10
        
        # 화살표 방향 벡터 계산
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = (dx**2 + dy**2)**0.5
        
        if length == 0:
            return
            
        # 정규화
        dx /= length
        dy /= length
        
        # 화살표 끝점에서의 수직 벡터
        perp_x = -dy
        perp_y = dx
        
        # 화살표 끝점
        arrow_end = end
        
        # 화살표 날개 점들
        wing1 = (
            int(end[0] - arrow_size * dx + arrow_size * 0.5 * perp_x),
            int(end[1] - arrow_size * dy + arrow_size * 0.5 * perp_y)
        )
        wing2 = (
            int(end[0] - arrow_size * dx - arrow_size * 0.5 * perp_x),
            int(end[1] - arrow_size * dy - arrow_size * 0.5 * perp_y)
        )
        
        # 화살표 그리기
        pygame.draw.polygon(self.screen, color, [arrow_end, wing1, wing2])

    def update_fire_info(self, unit_id: int, target_id: int):
        """사격 정보 업데이트"""
        self.last_fire_info[unit_id] = target_id

    def close(self):
        pygame.quit()

    def save_frame(self):
        """Save current frame as an image"""
        frame_path = os.path.join(self.frame_dir, f"frame_{self.frame_count:04d}.png")
        pygame.image.save(self.screen, frame_path)
        self.frame_count += 1

    def create_video(self, output_path: str = None, fps: int = 30):
        """Create video from saved frames using ffmpeg"""
        if self.frame_count == 0:
            print("No frames to create video from")
            return

        # Use instance output_path if not specified
        if output_path is None:
            output_path = self.output_path

        print(f"Creating video from {self.frame_count} frames...")  # 로그 추가
        print(f"Output path: {output_path}")  # 로그 추가

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # ffmpeg command to create video from frames
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output file if it exists
            '-framerate', str(fps),
            '-i', os.path.join(self.frame_dir, 'frame_%04d.png'),
            '-c:v', 'libx264',
            '-pix_fmt', 'yuv420p',
            output_path
        ]

        print(f"Running command: {' '.join(cmd)}")  # 로그 추가

        try:
            subprocess.run(cmd, check=True)
            print(f"Video created successfully: {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"Error creating video: {e}")
        except FileNotFoundError:
            print("Error: ffmpeg not found. Please make sure ffmpeg is installed and in your system PATH")

    def start_frame_capture(self):
        """Start saving frames"""
        self.save_frames = True
        self.frame_count = 0

    def stop_frame_capture(self):
        """Stop saving frames"""
        self.save_frames = False 

    def show_pause_screen(self):
        """일시정지 상태를 처리 - 화면 고정, SPACE로 재개"""
        font = pygame.font.SysFont(None, 48)
        text = font.render("Paused - Press SPACE to Resume", True, (255, 255, 255))
        text_rect = text.get_rect(center=(self.screen.get_width() // 2, self.screen.get_height() // 2))
        
        self.screen.blit(text, text_rect)
        pygame.display.flip()





        




