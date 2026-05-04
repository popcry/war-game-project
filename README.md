# Wargame

Python 기반 워게임 시뮬레이션과 지형 데이터 생성 도구를 함께 보관한 저장소입니다.

## 구성

```text
wargame/
├── war-game-modeling/          # Pygame 기반 워게임 시뮬레이션
│   ├── simulation.py           # 메인 실행 파일
│   ├── config.yaml             # 시뮬레이션 설정
│   ├── model/                  # 부대, 탐지, 사격, 이동, 지휘, 시각화 로직
│   └── database/               # 배경 이미지, DEM, 명중/피해 확률 CSV
├── vuhledar_terrain_project/   # Vuhledar AOI 지형 격자 생성 도구
│   └── build_vuhledar_terrain.py
├── requirements.txt            # 루트 통합 Python 의존성
└── README.md
```

## 프로젝트 요약

### `war-game-modeling`

RED/BLUE 양측 부대가 전장에서 이동, 탐지, 사격, 피해 판정을 수행하는 Pygame 기반 시뮬레이션입니다.

주요 기능:

- 전차, 대전차, 포병, 드론, 보병, 지휘소 단위 모델링
- 탐지선, 사격선, 유효 표적선 시각화 옵션
- `config.yaml`을 통한 초기 위치, 부대 수량, 시간, 영상 저장 설정
- `database/*.csv` 기반 명중률/피해 확률 계산

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

주요 옵션:

- `--time-scale`: 영상/시각화 시간 스케일
- `--sim_speed`: 시뮬레이션 속도
- `--detection`: 탐지선 표시 여부 (`T` 또는 `F`)
- `--eligible_TL`: 사격 가능 표적선 표시 여부 (`T` 또는 `F`)
- `--fire`: 사격선 표시 여부 (`T` 또는 `F`)

시뮬레이션 세부 값은 `war-game-modeling/config.yaml`에서 조정합니다.

### Vuhledar 지형 데이터 생성

```powershell
cd vuhledar_terrain_project
python build_vuhledar_terrain.py
```

AOI나 격자 크기를 바꿔 실행할 수도 있습니다.

```powershell
python build_vuhledar_terrain.py `
  --south 47.64 `
  --west 37.05 `
  --north 47.92 `
  --east 37.45 `
  --cell-size 50 ` (미터 단위)
  --output-dir outputs
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

## Git 업로드 참고

- 가상환경(`.venv`), 캐시, `__pycache__`, 실행 결과물은 Git에 올리지 않는 것을 권장합니다.
- `vuhledar_terrain_project/data_processed/terrain_grid_50m.gpkg`처럼 100MB를 넘는 파일은 일반 GitHub push가 실패할 수 있습니다.
- 대용량 데이터나 결과 영상까지 공유해야 한다면 Git LFS, Release artifact, 외부 스토리지 중 하나를 사용하는 편이 좋습니다.
- 현재 `war-game-modeling/` 안에는 별도 `.git` 폴더가 있습니다. 루트 `wargame` 저장소 하나로 합쳐 올릴 계획이라면 내부 저장소를 유지할지, 제거하고 일반 폴더로 올릴지 먼저 정리해야 합니다.

