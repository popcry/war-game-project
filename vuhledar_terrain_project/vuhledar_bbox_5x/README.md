# Vuhledar AOI 5x

This output set keeps the original Vuhledar AOI center and expands the north-south and east-west bbox size by 5x. The resulting mapped area is approximately 25x the original AOI.

Original corners:

- Upper-left: `47.783300, 37.227027`
- Lower-right: `47.744339, 37.306495`

Expanded build parameters:

- Center: `47.7638195, 37.2667610`
- Bounding box: `south=47.6664170`, `west=37.0680910`, `north=47.8612220`, `east=37.4654310`
- Grid: `30m x 30m`
- Grid-index extent: `1009 x 744`
- CRS: `EPSG:32637`

Key outputs:

- `data_processed/terrain_grid_30m.gpkg`
- `data_processed/terrain_grid_30m.csv`
- `vuhledar_terrain_classification_grid_index_30m.png`
- `vuhledar_contour_map_grid_index_30m.png`
- `vuhledar_static_map_grid_index_30m.png`
- `vuhledar_slope_map_grid_index_30m.png`
- `vuhledar_hillshade_grid_index_30m.png`
- `vuhledar_terrain_classification_map_30m.png`
- `vuhledar_static_map_30m.png`
- `vuhledar_contour_map.png`
- `vuhledar_osm_layers_map.html`
- `vuhledar_terrain_grid_map_30m.html`
- `data_validation_report_30m.txt`
