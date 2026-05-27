# Wargame

Python 기반 워게임 시뮬레이션과 지형 데이터 생성 도구를 함께 보관한 저장소입니다.

## 구성

```text
wargame/
├── war-game-modeling/          # Pygame 기반 워게임 시뮬레이션
│   ├── simulation.py           # 메인 실행 파일 (CSV 로깅 / headless / 조기종료)
│   ├── config.yaml             # 모든 하이퍼파라미터 (유닛/지형/확률/작전/자금 등)
│   ├── model/                  # 부대, 탐지, 사격, 이동, 지휘, 자금, 시각화 로직
│   └── database/               # 배경 이미지, DEM, 지형 레이어(참호/도로/하천) CSV
├── vuhledar_terrain_project/   # Vuhledar AOI 지형 격자 생성 도구
│   └── build_vuhledar_terrain.py
├── requirements.txt            # 루트 통합 Python 의존성
└── README.md
```

## 프로젝트 요약

### `war-game-modeling`

RED/BLUE 양측 부대가 전장에서 이동, 탐지, 사격, 피해 판정을 수행하는 Pygame 기반 시뮬레이션입니다.

주요 기능:

- 전차, 대전차, 포병, 드론, **자폭 드론(SELF_DEST_DRONE)**, 보병, 지휘소 단위 모델링
- 탐지선, 사격선, 유효 표적선 시각화 옵션
- **layered terrain**: 고도 + 참호/도로/하천 마스크, 지형별 이동·시야·명중·피해 배율
- **자금(money) 추적**: 사격 비용 + 피해 비용을 팀별로 집계
- **전면 config 기반**: 유닛 능력치, 명중/살상 확률, 작전단계(Phase), 지형, 자금 등 모든 하이퍼파라미터를 `config.yaml`에서 관리 (코드 수정 불필요)
- **CSV 결과 로깅**: 매 tick 모든 유닛 상태를 시간순 CSV로 저장 (아래 스키마 참조)
- **headless 모드**: 창·실시간 페이싱 없이 고속 실행 (데이터 수집용)
- **조기 종료**: 한 팀의 전투 가능 유닛이 0이 되면 승자 판정 후 종료
- 한글 라벨 폰트(Noto Sans CJK KR) 지원

### `vuhledar_terrain_project`

Vuhledar 주변 AOI에 대해 OpenStreetMap 데이터와 DEM을 활용하여 워게임용 지형 격자를 생성합니다.

주요 기능:

- OSM 도로, 건물, 토지이용, 자연 지형, 수계, 철도 레이어 다운로드
- Copernicus DEM 기반 고도, 경사도, hillshade 처리
- 50m 기본 격자 생성 및 지형 유형/이동 계수/은폐 계수 산출
- GeoPackage, CSV, PNG, HTML 지도 출력

기본 AOI:

```text
south=47.64
west=37.05
north=47.92
east=37.45
CRS=EPSG:32637
```

## 설치

Python 3.10 이상을 권장합니다.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 실행

### 워게임 시뮬레이션

```powershell
cd war-game-modeling
python simulation.py
```

옵션 예시:

```powershell
python simulation.py --time-scale 2.0 --sim_speed 1.0 --detection T --eligible_TL T --fire T
```

데이터 수집(고속, 창 없음):

```bash
# Linux 서버 등 디스플레이가 없을 때 SDL_VIDEODRIVER=dummy 권장
SDL_VIDEODRIVER=dummy python simulation.py --headless --no-video --max-time 600 --no-hold
```

주요 옵션:

- `--time-scale`: 영상/시각화 시간 스케일
- `--sim_speed`: 시뮬레이션 속도
- `--detection`: 탐지선 표시 여부 (`T` 또는 `F`)
- `--eligible_TL`: 사격 가능 표적선 표시 여부 (`T` 또는 `F`)
- `--fire`: 사격선 표시 여부 (`T` 또는 `F`)
- `--headless`: 창·실시간 페이싱 끄고 고속 실행 (CSV/영상은 그대로 생성)
- `--no-video`: 이번 실행에서 영상 녹화 비활성화
- `--max-time`: `config.yaml`의 `max_time`을 명령행에서 덮어쓰기
- `--no-hold`: 종료 시 창을 닫고 즉시 종료 (배치 실행용)

시뮬레이션 세부 값은 `war-game-modeling/config.yaml`에서 조정합니다.

### CSV 결과 로깅

`config.yaml`의 `csv.enabled: true`이면 매 tick마다 모든 유닛 상태가 `csv.output_path`(기본 `results/simulation.csv`)에 시간순으로 기록됩니다.

| 컬럼 | 설명 |
|---|---|
| `timestamp` | 시뮬레이션 시간 (초) |
| `team` | `red` / `blue` |
| `agent_type` | `infantry`/`tank`/`artillery`/`antitank`/`drone`/`self_dest_drone`/`command_post` |
| `agent_id` | 유닛 고유 ID (예: `blue_tnk_1`) |
| `x`, `y`, `z` | 위치 (m). `y`=고도, `x`/`z`=평면 좌표 |
| `yaw` | 진행 방향(heading, radian) |
| `alive` | 상태 분류: `alive`/`m_kill`/`f_kill`/`mf_kill`/`k_kill` |
| `event` | 해당 tick의 이벤트 (예: `fire`) |
| `target` | 이벤트 대상 유닛의 `agent_id` |

### 조기 종료 기준

매 tick 평가하여, 한 팀의 **전투 유닛(`simulation.combat_unit_types`, 기본 보병/대전차/전차/포병)** 중 사격 가능한 유닛이 0이 되면 그 팀이 패배하고 시뮬레이션이 즉시 종료됩니다. 아무도 못 이기면 `max_time`까지 진행합니다.

### `config.yaml`에서 관리하는 항목

모든 튜닝 가능한 값이 `config.yaml` 한 곳에 모여 있어 코드 수정 없이 실험할 수 있습니다.

| 섹션 | 내용 |
|---|---|
| `simulation` | 픽셀-미터 스케일, 맵 크기, 치사반경, 드론 고도, 산악 탐지확률, 전투유닛 타입 |
| `scaling` | 사거리/속도 변환 보정 계수 |
| `detection` | LOS 샘플 간격 |
| `fire` | 포병 공산오차, 방호 판정 지형 |
| `probabilities` | **명중/살상 확률 테이블** (거리 × 방호상태) — 구 `database/*.csv`에서 이전 |
| `movement` / `drone` | 이동·도달 거리, 드론 정찰 격자/주기/순회 패턴 |
| `units` | 유닛별 탐지·사거리·피탐지성·속도·사격간격 |
| `phases` / `phase_transitions` | 팀·단계별 TAI/사격우선순위/기동목표, 단계 전환 조건 |
| `terrain` | layered terrain 파일 경로 및 지형별 이동/시야/명중/피해 배율 |
| `money` | 사격 비용, 유닛 가치, 상태별 피해 비율 |
| `video` / `csv` | 영상·CSV 출력 설정 |

### Vuhledar 지형 데이터 생성

```powershell
cd vuhledar_terrain_project
python build_vuhledar_terrain.py
```

AOI나 격자 크기를 바꿔 실행할 수도 있습니다.

'''
python build_vuhledar_terrain.py  --south 47.64  --west 37.05  --north 47.92  --east 37.45  --cell-size 50 --output-dir outputs
```

DEM 파일을 직접 지정하려면:

```powershell
python build_vuhledar_terrain.py --dem-path C:\path\to\dem.tif
```

## 출력물

`war-game-modeling` 실행 시:

- `frames/`: 영상 저장용 프레임
- `results/`: 시뮬레이션 결과 이미지/영상

`vuhledar_terrain_project` 실행 시:

- `data_raw/`: OSM/DEM 원천 데이터
- `data_processed/`: 처리된 DEM, 경사도, 지형 격자
- `outputs/`: PNG/HTML 지도와 검증 리포트

이 출력물들은 용량이 커질 수 있어 루트 `.gitignore`에서 기본적으로 제외했습니다.
