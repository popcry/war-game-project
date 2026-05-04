# Vuhledar Terrain Builder

Python GIS 스크립트로 우크라이나 도네츠크주 부흘레다르/Vuhledar 주변 AOI의 공개 OpenStreetMap 자료와 DEM을 받아 50m 워게임 지형 격자를 생성합니다.

기본 AOI 중심은 lat `47.7798`, lon `37.2490`이며, 기본 bounding box는 다음과 같습니다.

```text
south=47.64
west=37.05
north=47.92
east=37.45
```

작업 CRS는 `EPSG:32637` / UTM Zone 37N입니다.

## 설치

Python 3.10 이상 권장.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Linux/macOS에서는 활성화 명령만 다음처럼 바꾸면 됩니다.

```bash
source .venv/bin/activate
```

## 실행

```bash
python build_vuhledar_terrain.py \
  --south 47.64 \
  --west 37.05 \
  --north 47.92 \
  --east 37.45 \
  --cell-size 50 \
  --output-dir outputs
```

Windows PowerShell에서는 줄바꿈 대신 한 줄로 실행하거나 백틱을 사용합니다.

```powershell
python .\build_vuhledar_terrain.py `
  --south 47.64 `
  --west 37.05 `
  --north 47.92 `
  --east 37.45 `
  --cell-size 50 `
  --output-dir outputs
```

## 생성되는 폴더

- `data_raw/`: OSM 원천 레이어와 자동 다운로드 DEM 타일 저장
- `data_processed/`: 변환된 지형 격자, CSV, 처리 DEM, slope raster 저장
- `outputs/`: PNG, HTML 지도, 검증 리포트 저장

폴더가 없으면 스크립트가 자동으로 생성합니다.

## 다운로드 레이어

OpenStreetMap은 OSMnx/Overpass API를 통해 다음 레이어를 받습니다.
각 GeoPackage는 AOI로 clip한 뒤 `EPSG:32637`로 저장됩니다.

- `data_raw/osm_roads.gpkg`: `highway=*`
- `data_raw/osm_buildings.gpkg`: `building=*`
- `data_raw/osm_landuse.gpkg`: `landuse=*`
- `data_raw/osm_natural.gpkg`: `natural=*`
- `data_raw/osm_waterways.gpkg`: `waterway=*`
- `data_raw/osm_railways.gpkg`: `railway=*`

일부 레이어가 비어 있거나 Overpass 요청이 실패해도 스크립트는 가능한 산출물을 계속 생성하고, 경고를 `outputs/data_validation_report.txt`에 기록합니다.

## DEM 처리

스크립트는 먼저 공개 Copernicus DEM AWS 타일 다운로드를 시도합니다.

1. `copernicus-dem-30m`
2. 실패 시 `copernicus-dem-90m`
3. 그래도 실패하면 `data_raw/dem.tif`

DEM이 없으면 elevation, slope, hillshade 분석은 건너뜁니다. 이때 가짜 고도값은 만들지 않으며 OSM 기반 격자와 지도는 계속 생성됩니다.

수동 DEM을 제공하려면 다음 중 하나를 사용합니다.

```text
data_raw/dem.tif
```

또는 실행 시 직접 지정합니다.

```bash
python build_vuhledar_terrain.py --dem-path C:\path\to\dem.tif
```

DEM에 CRS가 반드시 정의되어 있어야 합니다.

## 출력 파일

- `data_processed/terrain_grid_50m.gpkg`: 50m 지형 격자 GeoPackage
- `data_processed/terrain_grid_50m.csv`: 50m 지형 격자 CSV, geometry는 WKT
- `outputs/vuhledar_osm_layers_map.html`: OSM 레이어 인터랙티브 지도
- `outputs/vuhledar_terrain_grid_map.html`: 지형 격자 인터랙티브 지도
- `outputs/vuhledar_static_map.png`: 정적 지형 지도
- `outputs/vuhledar_contour_map.png`: DEM 기반 등고선 지도, DEM이 있을 때만 생성
- `outputs/vuhledar_terrain_classification_map.png`: terrain_type별 색상 분류 지도
- `outputs/vuhledar_slope_map.png`: slope 지도, DEM이 있을 때만 생성
- `outputs/vuhledar_hillshade.png`: hillshade 이미지, DEM이 있을 때만 생성
- `outputs/data_validation_report.txt`: 자동 검증 리포트

내부 확인용으로 `outputs/vuhledar_terrain_overlay.png`, `data_processed/dem_utm32637.tif`, `data_processed/slope_percent.tif`도 생성될 수 있습니다.

## 격자 속성

각 grid cell에는 다음 필드가 들어갑니다.

```text
cell_id
geometry
centroid_x
centroid_y
elevation_m
slope_percent
slope_class
terrain_type
road_type
building_count
urban_flag
water_obstacle
railway_flag
cover_factor
concealment_factor
mobility_factor_vehicle
mobility_factor_infantry
los_block
```

`terrain_type`은 `urban`, `forest`, `open_field`, `water`, `railway_corridor` 중 하나입니다. 도로가 있는 셀은 water가 아닌 한 차량 이동계수가 최소 `0.8` 이상으로 보정되고, DEM이 있을 경우 slope 구간에 따라 차량/보병 이동계수가 추가 보정됩니다.

## 다운로드가 제대로 되었는지 확인하는 방법

1. `outputs/data_validation_report.txt`를 열어 OSM 레이어별 feature 개수가 0이 아닌지 확인합니다.
2. 같은 리포트에서 `Grid cell count`, `terrain_type cell counts`, `road_type cell counts`가 생성되었는지 확인합니다.
3. `DEM used: yes/no`를 확인합니다. `no`이면 리포트의 warning에 다운로드 실패 이유나 `data_raw/dem.tif` 누락이 기록됩니다.
4. `outputs/vuhledar_osm_layers_map.html`을 브라우저에서 열어 roads/buildings/landuse/natural/waterways/railways 레이어가 켜지고 꺼지는지 확인합니다.
5. `outputs/vuhledar_static_map.png`와 `outputs/vuhledar_terrain_grid_map.html`에서 terrain 색상이 정상적으로 나타나는지 확인합니다.
6. QGIS에서 `data_processed/terrain_grid_50m.gpkg`를 열고 CRS가 `EPSG:32637`인지 확인합니다.
7. `data_raw/osm_*.gpkg` 파일 크기와 feature count를 QGIS 또는 GeoPandas로 확인합니다.

간단한 GeoPandas 확인 예시는 다음과 같습니다.

```python
import geopandas as gpd

grid = gpd.read_file("data_processed/terrain_grid_50m.gpkg")
print(grid.crs)
print(len(grid))
print(grid["terrain_type"].value_counts())
```

## 참고 데이터 소스

- OpenStreetMap: https://www.openstreetmap.org/
- OSMnx documentation: https://osmnx.readthedocs.io/
- Copernicus DEM on AWS Open Data: https://registry.opendata.aws/copernicus-dem/
- Copernicus DEM S3 readme: https://copernicus-dem-30m.s3.amazonaws.com/readme.html
