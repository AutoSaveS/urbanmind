# Case 1 (New York City): verified input inventory

Companion to `docs/data_and_model_config.md` Part 1, specialised to Case 1
(street-tree canopy expansion and cool-roof albedo adjustment). Status: `OK` acquired;
`DERIVED` computed by a stated rule; `PENDING` not yet obtained; `REPORT` documented but
not used as an input.

Window: four seasonal evaluation weeks, each 168 h history + 168 h evaluation. Parent
cells at 500 m. Köppen Dfa.

The inventory below covers Sections 1 and 2 in full and Section 3 as far as it was
specified. Case 1 configuration (Part 2C) and its runtime budget (Part 3) were not
supplied and are marked pending at the end.

## 1. Stage 1 observation modalities

### 1.1 Thermal

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| LST day / night | MODIS MOD11A1 / MYD11A1 v061 | LP DAAC, free Earthdata account, DOI 10.5067/MODIS/MOD11A1.061; ≥4 clear days at week selection | 1 km → 500 m, daily | OK |
| T_air, RH, radiation, precipitation | ERA5 single levels | <https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels>, free ECMWF account | 0.25°, hourly | OK |
| Station cross-check | NOAA ISD 725053 Central Park, 725030 La Guardia, 744860 JFK | `https://www.ncei.noaa.gov/pub/data/noaa/2023/{USAF}-{WBAN}-2023.gz` | station, hourly | OK |

### 1.2 Air quality

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| PM2.5 hourly (FEM, param 88101) | EPA AQS pre-generated hourly tables | <https://aqs.epa.gov/aqsweb/airdata/download_files.html>; `hourly_88101_2023.zip`, 9,350,315 rows, 75 MB, 2026-06-25 edition; filter State 36, County 005 / 047 / 061 / 081 / 085 | station, hourly | OK |
| PM2.5 hourly (non-FEM TEOM, 88502) | Same | `hourly_88502_2023.zip`, 1,896,251 rows, 14.8 MB | station, hourly | OK |
| PM2.5 daily (week selection, smoke-day screening) | Same | `daily_88101_2023.zip`, 847,162 rows, 9.9 MB; FRM 24 h and T640 daily | station, daily | OK |
| Site / monitor metadata | Same | `aqs_sites.zip` (20,994 rows), `aqs_monitors.zip` (370,090 rows) | site | OK |
| API backup | EPA AQS Data Mart | <https://aqs.epa.gov/data/api/>; free key via `signup?email=`; `sampleData/bySite`, `dailyData/byCounty`, `monitors/byCounty`, ≤1,000,000 rows per call | station, hourly / daily | OK |
| Monitors present in 2023 | EPA AQS | Bronx 36-005-0110 IS 52 (FRM + T640), 36-005-0112 IS 74 (T640), 36-005-0133 Pfizer Lab (FRM); Queens 36-081-0124 Queens College 2, 36-081-0125 Queens College Near Road (FRM + TEOM); Manhattan 36-061-0079 IS 45, 36-061-0128 PS 19; Brooklyn 36-047-0052 PS 314, 36-047-0118 PS 274, 36-047-0122 JHS 126; Staten Island 36-085-0055 Richmond Post Office. 88502 hourly also at 36-005-0080, 36-061-0115, 36-061-0135, 36-081-0120, 36-085-0111 | site | OK |
| 500 m PM2.5 field | Hourly stations → 500 m kriging / IDW (≥10 stations available) | Derived | 500 m, hourly | DERIVED |
| Annual PM2.5 spatial structure (prior / cross-check) | NYC DOHMH NYCCAS Air Pollution Rasters, NYC Open Data `q68s-8qxv` | `AnnAvg_1_16_300m.zip`, 8.4 MB, ESRI grid 300 m, NAD83 NY Long Island ft; years 1–16 = 2008-12 to 2024-12; `aa15_pm300m` = 2022-12 to 2023-12, `aa16_pm300m` = 2023-12 to 2024-12; also NO2 / NO / BC annual, O3 summer (`s15_o3300m` = Jun–Aug 2023), SO2 winter (years 1–8). Land-use-regression surface, not measurements | 300 m, annual | OK |

### 1.3 Building energy

New York has building-level disclosure (LL84) but only above 25,000 ft² private /
10,000 ft² municipal, so low-rise 1–3 family fabric is almost uncovered. The window
baseline uses ZIP-level UER monthly electricity / gas with LL84 multifamily cross-check;
the grid field stays a reconstructed field.

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| Reconstructed 500 m energy field | Existing dataset (sector electricity × LCZ typical EUI) | — | 500 m, daily | OK |
| ZIP monthly electricity / gas by sector | NYSERDA Utility Energy Registry Monthly ZIP Code Energy Use, data.ny.gov `g2x3-izm4` | CSV export; fields year, month, zip_code, utility, data_class, data_field_display_name, value, unit, number_of_accounts; NYC ZIPs only (Con Edison / National Grid); e.g. ZIP 10459 July 2023 residential electricity 6,148 MWh / 16,525 accounts; 2016–2021 in `tzb9-c2c6` | ZIP, monthly | OK |
| Building-level annual energy (≥25,000 ft²) | NYC DOB LL84 disclosure, `5zyy-y8am` | report_year 2022–2024 (2023: 33,684 rows; 265 columns); key fields `nyc_borough_block_and_lot`, `nyc_building_identification`, `primary_property_type`, `year_built`, `property_gfa_self_reported`, `site_eui_kbtu_ft`, `weather_normalized_site_eui`, `site_energy_use_kbtu`, `electricity_use_grid_purchase`, `natural_gas_use_kbtu`, `fuel_oil_*_use_kbtu`, `district_steam_use_kbtu`, `latitude`; join on BBL to PLUTO / Footprints, BIN to Footprints | per building, annual | OK |
| Building-level monthly energy | NYC DOB LL84 Monthly, `fvp3-gcb2` | calendar_year 2018–2021, 2023, 2024 (no 2022; 2023: 404,208 rows); `property_id`, month, electricity / gas / steam / fuel oil kBtu; join `property_id` to the annual table for BBL, BIN, GFA | per building, monthly | OK |
| Residential EUI | UER ZIP residential monthly electricity × 12 ÷ ZIP residential floor area (PLUTO `resarea` summed by ZIP); cross-check against LL84 `site_eui_kbtu_ft` median for walk-up multifamily | Derived | ZIP / per building | DERIVED |
| HDD / CDD | ERA5 T_air, base 18 / 26 °C (heating-dominated January week, cooling-dominated July week) | Derived | hourly | DERIVED |

### 1.4 Urban morphology

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| Building footprints (official, with roof height and construction year) | NYC OTI Building Footprints, NYC Open Data `5zhs-2jue` | Weekly, 2026-10-19; fields `bin`, `base_bbl`, `mappluto_bbl`, `construction_year`, `height_roof` (ft above ground), `ground_elevation` (ft NAVD88), `feature_code`, `shape_area`, `geom_source`, `the_geom`; covers buildings >400 ft² and >12 ft; field documentation in the nyc-geo-metadata repository | per building, vector | OK |
| Footprints cross-check / roads package | OSM | Geofabrik new-york-latest.osm.pbf, 497.8 MB, 2026-10-18; clip to the city boundary | vector | OK |
| Parcel attributes: year built, floors, floor area, land use, lot area, units | NYC DCP PLUTO, `64uk-42ks` | 26v2, 2026-08-24, quarterly, 108 columns; `bbl`, `yearbuilt`, `yearalter1/2`, `numfloors`, `bldgarea`, `resarea`, `comarea`, `lotarea`, `landuse`, `bldgclass`, `unitsres`, `unitstotal`, `zonedist1`, `builtfar`, `lotfront`, `lotdepth`, `latitude`, `longitude`, `xcoord`, `ycoord`; MapPLUTO geometry via `f888-ni5f` | parcel | OK |
| Height raster check 1 | GHSL GHS-BUILT-H R2023A (ANBH, E2018) | Mollweide tile R5_C12, 24.9 MB | 100 m, 2018 | OK |
| Height per building check 2 | 3D-GloBFP Americas | Zenodo 10.5281/zenodo.15459025 (CC-BY 4.0); `world_grid.zip` for the grid id, `data_links.txt` for the figshare parts | per building, 2020 | OK |
| Floors, floor area | PLUTO `numfloors` / `bldgarea`; when missing, `height_roof` ÷ 3.0 m × footprint area | Derived | per building | DERIVED |
| LCZ | WUDAPT; cross-check Global LCZ map (Zenodo 10.5281/zenodo.6364594) | Existing dataset | 100 m → 500 m | OK |
| NDVI / FVC | Sentinel-2 L2A summer composite, endmembers 0.15 / 0.85 | Copernicus Data Space | 10 m | OK |
| Canopy height | Meta/WRI global 1 m CHM | `s3://dataforgood-fb-data/forests/v1/alsgedi_global_v6_float/`, unsigned, CC-BY | 1 m | OK |
| Land cover and tree canopy | TNC & UVM SAL, NYC Land Cover / Tree Canopy Change / Tree Location 2021 | Zenodo 10.5281/zenodo.14053441 (CC-BY-NC-SA 4.0): `landcover_nyc_2021_6in.tif` (1.74 GB, COG, EPSG:2263, 0.15 m; 8 classes: canopy, grass/shrub, bare, water, building, road, other impervious, rail); `treecanopychange_nyc_2017_2021_6in.tif` (1.24 GB); `Trees_Centroids_Crown_Objects_2021.gdb.zip` (1.97 GB, per-tree crown polygons). 2017 edition on NYC Open Data `he6d-2qns` | 0.15 m, 2021 | OK |
| Land use | PLUTO `landuse` / `bldgclass` | As above | parcel | OK |
| Zoning (use and FAR caps) | NYC DCP Zoning GIS, `mm69-vrje` | version 202606, monthly; layers `nyzd`, `nyco`, `nysp`, `nylh`, `nyzma` | parcel polygons | OK |
| Construction year | PLUTO `yearbuilt` (parcel) / Footprints `construction_year` (building) | As above | parcel / building | OK |
| Availability mask p^(m) | Modality gaps | Derived | — | DERIVED |

## 2. Graph structure G

| Edge class | Item | Source | Access | Status |
| --- | --- | --- | --- | --- |
| E_adj | Grid adjacency | Existing dataset | — | OK |
| E_wind (primary) | Hourly wind speed and direction | NOAA ISD 725053 / WBAN 94728 Central Park (KNYC, 40.779 N 73.969 W, 42.7 m, from 2005-01-01) | `https://www.ncei.noaa.gov/pub/data/noaa/`; `isd-history.txt` 2025-08; note the 1943–1997 period used 725033 and a duplicate 725060 appears 2010-08 to 2012-04 — use 725053 for 2023 | OK |
| E_wind (airport backups) | Hourly wind | ISD 725030 / 14732 La Guardia (40.779 N 73.880 W, 3.0 m, from 1973), 744860 / 94789 JFK (40.639 N 73.764 W, 2.7 m, from 1973), 725020 / 14734 Newark (40.683 / −74.169, 2.0 m), 725025 / 94741 Teterboro (40.859 / −74.056) | Same; take the nearest station per window (Bronx: LGA ≈4 km or Central Park; Queens: LGA ≈5 km or JFK) | OK |
| E_wind (state Mesonet) | 5-min stations | NYS Mesonet, 126 stations including all five boroughs | `https://nysmesonet.org/weather/requestdata`; Data Access Policy 2024-02-08: free data for educational exploratory research on application, licence terms, no redistribution; US$200 one-off for the real-time stream. Approval-and-licence, not open download | REPORT |
| E_road | Centrelines, class, width, direction | NYC DCP LION, `2v4z-66xt` | `nyclion.zip`, 46 MB, quarterly, 2026-05; fields `StreetWidth_Min` / `StreetWidth_Max` (ft), `TrafDir` (W / A / T / P), `Number_Travel_Lanes`, `Number_Park_Lanes`, `Number_Total_Lanes`, `RW_TYPE`, `POSTED_SPEED`, `SegmentID`; CRS NAD83 NY Long Island ft | OK |
| E_road cross-check | Centrelines | OSM highway tags, same Geofabrik package | As in 1.4 | OK |
| E_road weight | 15-min automatic counts (ATR) | NYC DOT Automated Traffic Volume Counts, `7ym2-wayt` | Fields `requestid, boro, yr, m, d, hh, mm, vol, segmentid, wktgeom, street, fromst, tost, direction`; 2023: 85,106 rows, 127 segments; sampled, not year-round; history `btm5-ppia` | OK |
| E_road weight | Hourly counts by vehicle class | NYC DOT Vehicle Classification Counts 2011–2025, `96ay-ea4r` | Fields `segmentid, roadway_name, from, to, direction, date, veh_class_type`, 24 hourly columns | OK |
| E_road weight | AADT, truck AADT, truck share | NYSDOT Traffic Data Viewer | <https://dot.ny.gov/tdv>; ArcGIS service `.../Roadways/Traffic_Monitoring/MapServer`; GDB `NYSDOT_GDB_AADT_2023.zip`, `GDB_Shapefile_AADT_2024-2025.gdb.zip`; short and continuous counts by region (Region 11 = NYC, from 2010); data.ny.gov `6amx-2pbv` (AADT 1977–2020 only) | OK |
| E_road weight | Emission factors | EPA MOVES6 (2026-10) | <https://www.epa.gov/moves/latest-version-motor-vehicle-emission-simulator-moves>; g/veh-mi for NOx and primary PM2.5 by county (Bronx / Queens), 2023, by road type | OK |
| E_road check | County on-road emissions | EPA 2020 NEI | `2020nei_onroad_byregion.zip` (54 MB), `2020neiMar_county_tribe_allsector.zip`; Bronx 36005, Queens 36081 | OK |
| E_road weight | Vehicle population by class | NYS DMV registrations, data.ny.gov `w4pv-hbkt` | Per-vehicle records, 2026-10-02; `record_type`, `registration_class`, `county`, `body_type`, `fuel_type`, `unladen_weight`, `maximum_gross_weight`; aggregate by `county='BRONX'/'QUEENS'` (BRONX valid VEH 274,082) | OK |
| E_road weight | Road-class flow ratio | ATR `vol` grouped by LION `RW_TYPE` / `Number_Travel_Lanes`, plus NYSDOT AADT; no assumed 1.0 / 0.5 / 0.25 | Derived | DERIVED |

## 3. Context vector c and sub-cell features c_sub

Specified in the source inventory as follows; the table was truncated at this point, so
the entries below are those stated and the remainder is pending confirmation.

| Vector | Component | Source | Status |
| --- | --- | --- | --- |
| c | LCZ | WUDAPT / global LCZ map; window expected LCZ 3 (compact low-rise) or LCZ 6 (open low-rise) | OK |
| c | Köppen | Dfa, constant | OK |
| c | H_bldg | Footprints `height_roof` (ft → m), footprint-weighted parent mean; GHSL R5_C12 / 3D-GloBFP cross-check | OK |
| c | SVF | Footprints + `height_roof` | DERIVED |
| c | λ_p | Footprint area ÷ cell area | DERIVED |
| c_sub | H/W | `height_roof` ÷ LION `StreetWidth_Min` (ft → m); if empty, `Number_Total_Lanes` × 3.0 m; else `RW_TYPE` default (expressway / arterial 24 m, street 9 m) | DERIVED |
| c_sub | Wind angle | LION segment orientation vs weekly wind from ISD 725053 / 725030 | DERIVED |
| c_sub | Albedo | Sentinel-2 L2A broadband albedo, 10–20 m → 50 m cell mean (summer low-cloud median) | OK |
| c_sub | Construction year | PLUTO `yearbuilt` / Footprints `construction_year` | OK |
| c_sub | Land use / building class | PLUTO `landuse`, `bldgclass` (A one-family, B two-family, C walk-up), Zoning `nyzd` (R4 / R5 / R6) | OK |
| c_sub | Population (exposure weight) | US Census 2020 PL 94-171 New York file, 72.6 MB, no login (table P1 total population, H1 housing units, block level); or Census API `https://api.census.gov/data/2020/dec/pl?get=P1_001N&for=block:*&in=state:36 county:005 tract:*`; geometry from NYC DCP 2020 Census Blocks `wmsu-5muw` | OK |
| c_sub | Population (raster backup) | WorldPop 2020 constrained 100 m, `usa_ppp_2020_constrained.tif` (494 MB, windowed read) and the unadjusted variant; the `maxar_v1/USA/` path does not exist | OK |

## 4. Pending items for Case 1

The supplied inventory covers Sections 1 and 2 completely and Section 3 in part. The
following are not yet specified and must be filled before the case is runnable:

- Remaining Section 3 rows beyond population (c_sub albedo is stated; any further
  c_sub components, if intended).
- Section 4: scenario vector values and baseline for Case 1 (ΔV_f and Δα_r activation
  levels, plantable-area rule, roof-area rule).
- Section 5: Stage 2 library coverage checks for Dfa × LCZ 3 / 6.
- Section 6: effect references, cost side (coating unit cost, tree cost), C_ref, and any
  Case 1-specific BCI treatment.
- Section 7: baseline-comparison-only items.
- Part 2C: Case 1 configuration overrides (subgraph, weeks, adapter, V_mod, re-encoding,
  runtime geometry, edit script, C_ref).
- Part 3: runtime budget.

Sections A (shared), B (rule fixed, values vary) and D (invariants) of the model
configuration follow `docs/data_and_model_config.md` unchanged.
