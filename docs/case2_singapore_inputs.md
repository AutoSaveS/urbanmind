# Case 2 (Singapore): verified input inventory

Companion to `docs/data_and_model_config.md` Part 1, specialised to Case 2
(equal-floor-area height redistribution with ground greening, Toa Payoh).
Status: `OK` acquired; `DERIVED` computed by a stated rule; `PENDING` not yet obtained.

Window: one evaluation week (inter-monsoon, low wind), 168 h history + 168 h evaluation.
Parent cells at 500 m.

## 1. Stage 1 observation modalities

### 1.1 Thermal

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| LST day / night | MODIS MOD11A1 / MYD11A1 v061 | LP DAAC, DOI 10.5067/MODIS/MOD11A1.061; relax to ≥3 clear days (equatorial cloud) | 1 km → 500 m, daily | OK |
| T_air, RH, radiation, precipitation | ERA5 single levels | Copernicus CDS | 0.25°, hourly | OK |
| Station cross-check | NEA Historical Air Temperature 2023, `d_370bbfc65de96ad93eaefa182135d1c0` | data.gov.sg; 6.9M rows, 1.1 GB, 17 stations with coordinates; rain set 2279, RH set 2278 | station, 1 min | OK |

### 1.2 Air quality

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| PM2.5 by region, hourly | NEA Historical 1-hr PM2.5, `d_6c0d5fc34838b12472475fdb73c0af29` | data.gov.sg; columns 1hr_pm25,north,south,east,west,central; 2023 complete, 8,760 rows | 5 regions, hourly | OK |
| PM2.5 with region coordinates | NEA Historical PM2.5 (2023), `d_2e5049336e1a6e44b4c236a73e6c7e48` | data.gov.sg collection 2216; 40,200 rows, about 8% hours missing | 5 regions, hourly | OK |
| PM10 / NO2 / O3 / SO2 / CO / PSI | NEA Historical PSI (2023), `d_10501b71361f97dbbbab82095406c9c5` | data.gov.sg; 48,534 rows. NO2, O3, SO2, CO are sliding-window statistics only (1 h max / 8 h max / 24 h), no hourly concentration | 5 regions + national | OK |
| 24 h PSI by region | NEA Historical 24-hr PSI, `d_b4cf557f8750260d229c49fd768e11ed` | data.gov.sg, from 2014-04 | 5 regions, hourly | OK |
| Region geometry | NEA representative points from the PSI / PM2.5 tables | N 103.82/1.41803, S 103.82/1.29587, E 103.94/1.35735, W 103.70/1.35735, C 103.82/1.35735; published representative points, not monitor coordinates | 5 points | OK |
| 500 m PM2.5 field | IDW / nearest region from the 5 points | Derived; no station data, so no kriging | 500 m, hourly | DERIVED |
| Near-real-time | NEA PSI API, `d_fe37906a0182569d891506e815e819b7` | data.gov.sg, from 2016-02 | 5 regions | OK |

### 1.3 Building energy

Singapore has no building-level disclosure; the grid field is reconstructed, and public
statistics stop at planning area × dwelling type.

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| Reconstructed 500 m energy field | Existing dataset (sector totals × LCZ typical EUI) | — | 500 m, daily | OK |
| Sector electricity | EMA Singapore Energy Statistics 2025, ch. 3 | <https://www.ema.gov.sg/resources/singapore-energy-statistics/chapter3>; 2024 national 58 TWh, residential 14.6% (≈8 TWh), commercial 40.2%, industrial 39.4%; 2023 55 TWh | national, annual | OK |
| Household monthly consumption by planning area × dwelling type | EMA SES ch. 3, tables T3.4 and T3.5 | Same XLSX (tabular 1 MB / tidy 5 MB) | planning area (55), annual | OK |
| Same, with geometry (older years) | EMA Average Monthly Household Electricity Consumption by Planning Area & Dwelling Type, `d_47db177174ba5899aa9cee08797d9171` | data.gov.sg GeoJSON; fields PLN_AREA_N, TOTAL, ONE_TO_TWO_RM, THREE_RM, FOUR_RM, FIVE_RM_EXEC_FLATS (kWh per household-month); 2010 / 2012 / 2013 | planning area, 2013 | OK |
| Residential EUI | T3.5 × 12 ÷ typical floor area (3-room 65, 4-room 90, 5-room 110, executive 130 m²) | Derived | planning area | DERIVED |
| Dwelling-type mix | HDB Property Information `1room_sold` … `exec_sold`, `*_rental` | See 1.4 | per block | OK |
| Appliance / AC share | NEA Household Electricity Consumption Profile | Air-conditioning, refrigeration, lighting, water heating and washing ≈80% combined | national | OK |
| CDD | ERA5 T_air, base 26 °C (sensitivity 24 °C) | Derived; no heating term | hourly | DERIVED |

### 1.4 Urban morphology

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| Building footprints, island | OSM | Geofabrik malaysia-singapore-brunei, 252 MB, 2026-10-20; clip to boundary | vector | OK |
| HDB block footprints | HDB Existing Building, `d_16b157c52ed637edd6ba1232e026258d` | data.gov.sg GeoJSON, BLK_NO / ST_COD / POSTAL_COD, bi-monthly | per block | OK |
| Building height / floors (HDB) | HDB Property Information, `d_17f5382f26140b1fdae0ba2ef6239d2f` | data.gov.sg CSV, 939 KB, 13.4k rows, quarterly; `max_floor_lvl`, `year_completed`, dwelling mix columns | per block | OK |
| Building height (all types) | 3D-GloBFP Asia, grid 2058 | Zenodo 10.5281/zenodo.11397014; file `2058_102.5_0.0_105.0_2.5_ID_MY_SN.zip`, 142.9 MB, PART IX | per building, 2020 | OK |
| Height raster check 1 | GHSL GHS-BUILT-H R2023A R9_C29 | JRC, 6.9 MB, Mollweide | 100 m, 2018 | OK |
| Height raster check 2 | DLR WSF 3D v02 BuildingHeight | <https://download.geoservice.dlr.de/WSF3D/files/global/WSF3D_V02_BuildingHeight.tif>; 2.14 GB, Range-read by window, Int16 gain 0.1 m | 90 m, ~2019 | OK |
| Floors, floor area | HDB `max_floor_lvl`; otherwise GloBFP height ÷ 2.9 m; floor area = footprint × floors | Derived | per building | DERIVED |
| LCZ | WUDAPT; cross-check Global LCZ map (Demuzere et al.), Zenodo 10.5281/zenodo.6364594 | Existing dataset | 100 m → 500 m | OK |
| NDVI / FVC | Sentinel-2 L2A annual median composite (equatorial cloud), endmembers 0.15 / 0.85 | Copernicus Data Space | 10 m | OK |
| Canopy height | Meta/WRI 1 m CHM, tiles 132232231 and 132232213 | `s3://dataforgood-fb-data/forests/v1/alsgedi_global_v6_float/chm/`, unsigned | 1 m | OK |
| Land use | URA Master Plan 2019 Land Use, `d_90d86daa5bfaa371668b84fa5f01424f` | data.gov.sg GeoJSON 166 MB; LU_DESC, GPR, WHI_Q_MX. Amendment `d_c0e06af6b1a36e6a82223f67c1e17fbd` (170 MB, 2025-09) | parcel | OK |
| Construction year (HDB) | HDB `year_completed` | As above | per block | OK |
| Construction year (all types) | WSF Evolution `WSFevolution_v1_102_0.tif` (3.4 MB) + `WSFevolution_v1_104_0.tif` (1.7 MB) | <https://download.geoservice.dlr.de/WSF_EVO/files/> | 30 m | OK |
| Availability mask p^(m) | Modality gaps | Derived | — | DERIVED |

Not used: CNBH-10m does not cover Singapore.

## 2. Graph structure G

| Edge class | Item | Source | Status |
| --- | --- | --- | --- |
| E_adj | Grid adjacency | Existing dataset | OK |
| E_wind (primary) | 1-min wind speed / direction, nearest station | NEA `d_de9a32cc338823ee9d58c3b7576fa267` (knots) and `d_c9a10c59294e89a8233562435f81b221` (degrees); collections 2280 / 2281, 2016–2024, 17 stations; aggregate to hourly; NEA notes no climate QC | OK |
| E_wind (backup) | NOAA ISD 486980 Changi (1.350 N, 103.994 E, 6.7 m) | <https://www.ncei.noaa.gov/pub/data/noaa/> | OK |
| E_wind (further) | ISD 486940 Paya Lebar, 486990 Seletar | Same | OK |
| E_road | Centrelines and class | OSM highway tags, same Geofabrik package | OK |
| E_road weight | Segment hourly flow by road class | LTA DataMall Traffic Flow API, free AccountKey; quarterly representative month 07:00–09:00 | OK |
| E_road weight | Junction turning counts by vehicle class | LTA DataMall Traffic Count, 15-min, 518 MB, annual | OK |
| E_road weight | Vehicle population by type | LTA Annual Vehicle Statistics, `d_2873f3b1b2a836103f51f696350b98fa`; 2023 year-end 996,732 (cars 651,302; taxis 13,620; motorcycles 143,488; goods and other 143,960; buses 17,833; exempt 26,529) | OK |
| E_road weight | Annual km per vehicle | `d_bdc4c6434e47b055de4b5f2fde10c1af` (2005–2018): 2018 car 17,500 km, LGV 29,500, HGV 39,500, motorcycle 13,000, school bus 44,800, private bus 43,100 | OK |
| E_road weight | Emission factors | No official fleet EF. Use NTU open thesis <https://hdl.handle.net/10356/169224> (KPE tunnel 2015 fleet mean NOx 0.28 g/veh-km, CO 1.46) and EMEP/EEA Guidebook 2023 by Euro class | PENDING substitution |
| E_road weight | Road-class flow ratio | Computed from Traffic Flow API by CAT class; no assumed 1.0 / 0.5 / 0.25 | DERIVED |
| E_road check | Annual arterial daily volume and mean speed | LTA DataMall Road Traffic Conditions, annual | OK |

## 3. Context vector c and sub-cell features c_sub

| Vector | Component | Source | Status |
| --- | --- | --- | --- |
| c | LCZ | WUDAPT, cross-check global LCZ map | OK |
| c | Köppen | Af, constant | OK |
| c | H_bldg | HDB `max_floor_lvl` × storey height plus GloBFP per building, footprint-weighted cell mean; GHSL / WSF3D raster check | OK / DERIVED |
| c | SVF | OSM / HDB footprints + per-building height; recomputed for both arms of Case 2 | DERIVED |
| c | λ_p | Footprint area ÷ cell area, baseline vs redistribution arm | DERIVED |
| c_sub | H/W | Height ÷ road width (OSM width / lanes; class defaults below) | DERIVED |
| c_sub | Road width defaults | LTA Code of Practice on Street Work Proposals v2.0 (2019-04) Table 2.5: expressway 45.5 / 52.9; major arterial 38.6 / 45.4; secondary 4-lane divided 31.8; primary access 26.2 / 22.5 / 18.8; local access 18.0; landed housing 16.0; service 7.6 / 10. OSM mapping: motorway 45.5, trunk/primary 38.6, secondary 31.8, tertiary 26.2, residential/unclassified 18.0, service 10 | OK |
| c_sub | Wind angle | Road orientation vs weekly wind from the nearest NEA station; ISD 486980 backup | DERIVED |
| c_sub | Albedo | Sentinel-2 L2A broadband albedo, 10–20 m → 50 m cell mean (annual low-cloud median) | OK |
| c_sub | Construction year | HDB `year_completed` / WSF Evolution | OK |
| c_sub | Population | WorldPop 2020 constrained 100 m, `sgp_ppp_2020_constrained.tif` (205 KB) and unadjusted (193 KB); cross-check SingStat planning-area table (388 KB) and data.gov.sg Census 2020 `d_7f243956483d5901f237e6f87b096636` | OK |
| c_sub | Planning-area boundaries | OneMap API `/api/public/popapi/getAllPlanningarea?year=2019`, free token | OK |

## 4. Scenario vector a (Case 2)

Only ΔV_f is activated. Height redistribution does not enter through a: it enters through
node morphology features (H_bldg, SVF, λ_p, H/W), through c and c_sub re-retrieval, and
through the E_wind shadow weights.

| Component | Case 2 value | Baseline | Source | Status |
| --- | --- | --- | --- | --- |
| ΔV_f | released ground × 0.8 ÷ window area, converted to FVC increment via mature crown | Released ground = baseline footprint − redistributed tower footprint (equal GFA); plantable = released ground ∪ WorldCover grass / bare − existing canopy | HDB / OSM, HDB floors, Sentinel-2 FVC, Meta/WRI, WorldCover | OK / DERIVED |
| ΔV_f land-cover baseline | ESA WorldCover 2021 v200 | `ESA_WorldCover_10m_2021_v200_N00E102_Map.tif`, 36.5 MB, covers whole island; Zenodo 10.5281/zenodo.7254221 | 10 m | OK |
| ΔV_f → tree count | Green area ÷ mature crown area | Crown width per species from NParks Flora & Fauna Web; tree / lawn ratio a design input | public | OK / DERIVED |
| Prevailing wind (tower orientation) | MSS Climate of Singapore | NE monsoon Dec–early Mar (strongest Jan–Feb); SW monsoon Jun–Sep; inter-monsoon Apr–May and Oct–Nov weak and variable; annual mean ≈2 m/s; 1991–2020 Changi wind rose | climatology | OK |
| Δα_r | 0 (inactive) | Sentinel-2 albedo, retained in c_sub | — | OK |
| ΔR_wall | 0 (inactive) | Construction year retained in c_sub | — | OK |
| ΔS_emit | 0 (inactive) | E_road weights unchanged | — | OK |

## 5. Stage 2 knowledge libraries

| Library | Coverage to check for Case 2 |
| --- | --- |
| Domain Knowledge (319) | Af × LCZ 1 / 4 entries by energy balance, dispersion (ventilation corridors, building wake), building energy, vegetation cooling |
| Downscaling δ_k | T / PM / E under Af × LCZ 1/4 × evaluation-week wind angle (NE / SE–S / inter-monsoon) × material |
| Intervention Outcomes (208) | Af-matched form-redistribution, wind-aligned tower and ground-greening cases with effect sizes |
| C_prior, ρ | Trained version identifiers |

## 6. Stage 3 decoding and BCI

**6.1 Reference effects** — identical to the shared definition: T_surf 2.5 °C reduction
positive (Singapore is cooling-season all year, so the week counts), PM2.5 10 µg/m³
reduction positive, E 20% reduction positive, coverage 8 pp increase positive.

**6.2 Cost side**

| Item | Source | Value | Status |
| --- | --- | --- | --- |
| Residential construction cost (S$/m² CFA, Q1 2025) | RLB Rider's Digest 2025 – Singapore | Condominium mid 2,900–3,570 (building 2,440–2,910 + M&E 460–660); good 3,590–4,520; international table "Residential Multi Storey" 3,000–4,300; excludes land, fees, GST | OK |
| Same, Q1 2024 cross-check | RLB Rider's Digest 2024 | Condominium mid 3,150–3,570 | OK |
| High-rise cross-check (Q2 2025) | Arcadis Quarterly Construction Cost Review | "Apartments, high rise, average standard, full fit" USD 2,040–2,385/m² CFA ≈ S$2,650–3,100 at S$1.30/USD | OK |
| Mass-market cross-check (4Q2021) | Surbana Jurong Market Review & Outlook 2022-03 | Residential mass market S$2,500–2,750/m² CFA | OK |
| Public housing cost per unit (official) | HDB / MND BTO disclosure 2023-12 | FY2021/22: 13,506 units, construction S$2.08 bn (land S$3.17 bn separate) → ≈S$154,000/unit; at ≈95–100 m² GFA per unit ≈ S$1,550–1,700/m² GFA | OK / DERIVED |
| High-rise premium | RLB Singapore and Regional Report Dec 2024 | Office 10–25 storeys 3,010–4,940 vs 26–40 storeys 4,410–5,700 (mid +27%); prestige +15%. No residential value published, so used as proxy: main +20%, sensitivity +10% / +30% | proxy |
| Incremental build cost | Window GFA × unit cost (main S$3,200/m² CFA; sensitivity 1,600 = HDB official) × high-rise premium (only GFA above baseline floors) | Derived | DERIVED |
| Cost index | BCA tender price index, HDB flats (2010 = 100): 2023 134.1, 2024p 135.6 | As reproduced in the RLB report | OK |
| Tree unit cost | NParks Garden City Fund Plant-A-Tree | Minimum S$300 per tree, including stock and planting | OK |
| Ground-cover unit cost | No Singapore public price | Open literature, sensitivity parameter | PENDING |
| Greening cost | Released ground × 0.8 × (trees × S$300 + cover area × literature price) | Derived | DERIVED |

**6.3 Cost reference C_ref**

| Item | Source | Value | Status |
| --- | --- | --- | --- |
| Standard comprehensive retrofit per unit | HDB Home Improvement Programme | 2024-07: >53,000 units, >S$742 M → ≈S$14,000/unit; 2007–2024 cumulative ≈370,000 units, ≈S$4 bn → ≈S$10,800; 2026-05 ≈409,000 units ≈S$5 bn → ≈S$12,200, latest batch 18,000 units S$253 M → ≈S$14,100 | OK / DERIVED |
| HIP government share by flat type | gov.sg explainer 2024-06-08, HDB HIP page | 1–3 room S$11,390.50 (95%), 4-room S$11,090.75 (92.5%), 5-room S$10,791.00 (90%), executive S$10,491.25 (87.5%), incl. 9% GST; essential items fully funded and not itemised | OK |
| Typical floor areas | HDB dwelling descriptions | 3-room 60–65, 4-room 90–93, 5-room 110–112, executive ≈130 m²; 4-room 90 m² as the conversion basis | OK |
| Unit conversion | S$14,000 ÷ 90 m² ≈ S$156/m² (cumulative basis S$10,800 ÷ 90 ≈ S$120/m²) | Derived | DERIVED |
| C_ref | S$156/m² × window floor area | Window ≈750,000 m² → ≈S$117 M | DERIVED |
| Alternative C_ref | Neighbourhood Renewal Programme | S$6,100 per unit, rising to about S$6,600 (MND, 2025-04); previous S$4,700 (building/precinct 3,400 + repair 1,300); batch 16: 17 precincts, >25,000 units, >S$165 M | OK |

**6.4 BCI** — as defined in the shared configuration: equal weights by default with
T-weight sensitivity 0.4, clipping at the aggregate level only, one-off undiscounted cost,
interval from a common Monte Carlo sample.

## 7. Baseline comparison only

| Item | Source | Status |
| --- | --- | --- |
| Landsat 8/9 C2 L2 LST, low-cloud scene in the evaluation week | USGS EarthExplorer, free account | OK |
| Window-area daily mean PM2.5 in the evaluation week | NEA Historical 1-hr PM2.5, or PSI `pm25_twenty_four_hourly` | OK |
| Planning-area household monthly consumption (order-of-magnitude check) | EMA SES T3.5 | OK |

## 8. Source substitutions

| Original source | Problem | Replacement | Effect |
| --- | --- | --- | --- |
| OneMap API building footprints | Themes are POI points plus planning-area polygons; no building footprint or height layer | HDB Existing Building GeoJSON + OSM; OneMap retained for planning-area boundaries only | none |
| CNBH-10m height | China only | HDB `max_floor_lvl` + 3D-GloBFP grid 2058; GHSL R9_C29 and WSF3D as raster checks | HDB floors are higher quality |
| NParks Trees.sg inventory | No bulk download or public API; site backend is not published as open data | Meta/WRI 1 m CHM + Sentinel-2 FVC; data.gov.sg layers for heritage trees, parks and tree conservation areas | no per-tree attributes (species, DBH); canopy represented as CHM |
| Station-level PM2.5 kriging (as done for Nanjing) | NEA publishes five regional values and no station coordinates; NO2 / O3 / SO2 / CO only as window statistics | NEA 1-hr PM2.5 by region, IDW / nearest region; other pollutants for cross-check only | air-quality modality is PM2.5 only, at 10–15 km regional scale |
| NEA / LTA official fleet emission factors | Not published (only VES bands) | NTU open thesis tunnel measurement + EMEP/EEA Guidebook 2023 by Euro class | slightly higher uncertainty in emission weights, partly offset by measured traffic flows |
| data.gov.sg planning-area × dwelling consumption (GeoJSON) | Only 2010 / 2012 / 2013 | EMA SES 2025 T3.4 / T3.5 XLSX to 2024; 2013 GeoJSON for geometry only | none |
| WSF3D tiled distribution | `tiles/` holds 453 sample tiles, none for Singapore | Global single file read by window with HTTP Range | none |
| BCA public housing unit cost table | BCA does not publish HDB cost per m² | RLB / Arcadis / Surbana Jurong public PDFs + HDB official per-unit cost | unit cost taken as a range with sensitivity |
| Residential high-rise cost premium | No published Singapore value by storey band | RLB Dec 2024 office 10–25 vs 26–40 storey ratio as proxy (+15% to +27%) | proxy parameter, sensitivity applied |
| GeBIZ award prices (Nanjing-style lot basis) | Requires login; no citable lot found | HIP per-unit budget (HDB), NRP per-unit budget (MND), GCF per tree | cost reference changes from lot unit price to official programme per-unit budget |
| Ground-cover unit price | No Singapore public price | Open literature, sensitivity parameter | tree cost anchored, ground cover not |

## 9. Case 2 configuration

Sections A (shared), B (rule fixed, values vary) and D (invariants) are as in
`docs/data_and_model_config.md`. Case-specific overrides:

| Item | Singapore setting | Why |
| --- | --- | --- |
| Subgraph | Window parents + adjacency L = 2 + wind-reachable + halo, ≈50–100 cells | Morphology intervention acts on the window |
| Weeks | 1 | Af rule |
| Main week | 2023 inter-monsoon low-wind (Apr–May or Oct–Nov) | Ventilation effect most measurable |
| LoRA adapter | Singapore | per city |
| Active components | ΔV_f (derived: released ground × 0.8 ÷ window area); Δα_r = ΔR_wall = ΔS_emit = 0 | Case 2 definition |
| Height entry path | Morphology node features (re-encode) + c H_bldg / SVF (re-retrieve K_i) + c_sub H/W / SVF (re-retrieve δ_k) + E_wind shadow weights; not via a | Height is not in a |
| V_mod | Window cells | intervention footprint |
| Re-encoding | Window parents (height, λ_p, FVC changed) | morphology change |
| Runtime geometry | Yes: generate tall slim massing, recompute SVF / H/W / λ_p, released-ground greening area, c; baseline geometry offline | intervention changes building geometry |
| E_wind data | Nearest NEA 1-min station, ISD 486980 backup | local stations available |
| T convention | Daytime surface primary, night reported alongside | shading and SVF effects are diurnal |
| E output | Total energy = cooling, % of reconstructed baseline | year-round cooling, no building disclosure |
| T in BCI | Counted (year-round cooling season) | shared rule triggers here |
| PM baseline | NEA five regions, 500 m field nearly constant; spatial structure from δ_k^(PM) | only five regional values |
| Retrieval context | Af × LCZ 1 / 4 | sparsest cell, wider PI expected |
| Edit script | Height +20 / +30 / +40%; gap orientation parallel / perpendicular to prevailing wind; greening ratio 0.6 / 0.8 / 1.0 | case parameters |
| C_ref | HIP ≈S$14,000 per unit ÷ 90 m² ≈ S$156/m² × window floor area | one public retrofit price per city |

## 10. Runtime budget (Case 2)

| Module | Item | Parameters | GPU busy (s) | Cumulative (s) |
| --- | --- | --- | --- | --- |
| io | tensors to device | 5 MB | 0.01 | 0.01 |
| stage2 | retrieval embed + cosine | 100×1×2 queries | 0.02 | 0.03 |
| stage1 | warmup, cudnn autotune | N = 100, W = 168 | 0.50 | 0.53 |
| stage1 | encode | two morphology inputs | 0.10 | 0.63 |
| stage1 | rollout, baseline arm | 168 steps, 5 projections | 0.45 | 1.08 |
| stage1 | rollout, scenario arm | 168 steps, E_wind weights recomputed | 0.45 | 1.53 |
| stage1 | C^(loc) accumulation | 168 steps | 0.08 | 1.61 |
| stage3 | decode + MC | 100×336×4×30 | 0.25 | 1.86 |
| stage3 | downscale | 100 sub-cells, K = 5 | 0.04 | 1.90 |
| stage3 | closure audit | 100×336×30 | 0.20 | 2.10 |
| total | — | wall 19.2 s, GPU 2.1 s, 11% busy | — | 2.10 |
