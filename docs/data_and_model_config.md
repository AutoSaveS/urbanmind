# Model inputs and run configuration

Operational companion to manuscript §3.1 and Appendix A.2. Status: `OK` = acquired
and used as provided; `DERIVED` = computed from the listed inputs by a stated rule.

## Part 1 — Inputs by component

### 1. Stage 1 observation modalities x^(m,t)

500 m parent cells, hourly. Each evaluation window: 168 h history + 168 h evaluation.

**1.1 Thermal**

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| LST, day / night | MODIS MOD11A1 / MYD11A1 | Existing 500 m dataset; LP DAAC cloud cover checked at week selection | 1 km → 500 m, daily | OK |
| T_air, RH, radiation, precipitation | ERA5 single levels | Copernicus CDS, free ECMWF account | 0.25°, hourly | OK |

**1.2 Air quality**

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| PM2.5, NO2, O3 station-hourly | CNEMC via quotsoft.net | `https://quotsoft.net/air/data/china_sites_YYYYMMDD.csv`, from 2014-05-13; station coordinates included | stations → 500 m kriging, hourly | OK |

**1.3 Building energy**

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| Reconstructed energy field | Existing dataset (yearbook sector totals × LCZ typical EUI) | — | 500 m, daily | OK |
| Sector electricity | Nanjing Statistical Yearbook 2024, Tables 1-9, 7-14, 7-15 | <https://tjj.nanjing.gov.cn/material/njnj_2024/index.html>; 2023 total 7,472,669 ×10⁴ kWh; urban residents 920,638 ×10⁴ kWh | city, annual | OK |
| Residential EUI | Table 1-9 ÷ Tables 3-1/3-6 ÷ Table 4-1 | Derived | city | DERIVED |
| AC ownership per 100 households | Table 4-4 | As above | city | OK |
| HDD / CDD | ERA5 T_air, base 18 / 26 °C | Derived | hourly | DERIVED |

**1.4 Urban morphology**

| Item | Source | Access | Resolution | Status |
| --- | --- | --- | --- | --- |
| Footprints | OSM | Geofabrik Jiangsu `jiangsu-latest.osm.pbf` (76 MB) | vector | OK |
| Height | CNBH-10m (Wu et al. 2023) | Zenodo 10.5281/zenodo.7923866, CC-BY | 10 m, 2020 | OK |
| Height, cross-check | 3D-GloBFP Asia | Zenodo 10.5281/zenodo.11397014 | per building, 2020 | OK |
| Floors, floor area | h ÷ 2.9 m; footprint × floors | Derived | per building | DERIVED |
| LCZ | WUDAPT | Existing dataset | 100 m → 500 m | OK |
| NDVI / FVC | Sentinel-2 L2A summer composite, endmembers 0.15 / 0.85 | Copernicus Data Space | 10 m | OK |
| Canopy height | Meta/WRI global canopy height | `s3://dataforgood-fb-data/forests/v1/alsgedi_global_v6_float/`, unsigned access, CC-BY | 1 m | OK |
| Land use | EULUC-China 2.0 (2022) | Zenodo 10.5281/zenodo.15180905 / 10.5281/zenodo.16794007 | parcel | OK |
| Construction year | WSF Evolution 1985–2015 | DLR geoservice; tiles `118_30`, `118_32` | 30 m | OK |
| Construction year, cross-check | GAIA 1985–2018 | Star Cloud 13 or GEE `Tsinghua/FROM-GLC/GAIA/v10` (≥19 ⇔ ≤2000) | 30 m | OK |
| Availability mask p^(m) | Modality gaps | Derived | — | DERIVED |

### 2. Graph structure G

| Edge class | Item | Source | Status |
| --- | --- | --- | --- |
| E_adj | Grid adjacency | Existing dataset | OK |
| E_wind | Hourly wind speed and direction | NOAA ISD 582380 LUKOU (31.742°N 118.862°E); only Nanjing station in ISD | OK |
| E_road | Centrelines, class | OSM `highway` tags, Jiangsu extract | OK |
| E_road weight | Emission factors, default VKT | MEE Announcement 2014 No. 92, Annex 3, Table 4: min/small passenger 18,000 km, taxi 120,000, bus 60,000, min/light truck 30,000 | OK |
| E_road weight | Vehicle stock by class | Yearbook Table 8-6; 2024 year-end 3.5969 ×10⁶ | OK |
| E_road weight | Road-class flow ratio | Nanjing 2014 RFID (DOI 10.13227/j.hjkx.201608065): arterial 1.0 / secondary 0.5 / local 0.25 (local assumed) | DERIVED |
| E_road check | Gridded transport emissions | MEIC v1.4, 0.25°, 2020, CC BY-NC-ND | OK |

### 3. Context vector c and sub-cell features c_sub

| Vector | Component | Source | Status |
| --- | --- | --- | --- |
| c | LCZ | WUDAPT | OK |
| c | Köppen | Cfa, constant | OK |
| c | H_bldg | Parent-cell mean of CNBH-10m | OK |
| c | SVF | OSM footprints + CNBH-10m heights | DERIVED |
| c | λ_p | Footprint area ÷ cell area | DERIVED |
| c_sub | H/W | Height ÷ road width (OSM `width`/`lanes`; class defaults arterial 35 / secondary 25 / local 15 / residential 8 m) | DERIVED |
| c_sub | Wind angle | Road orientation vs ISD 582380 weekly direction | DERIVED |
| c_sub | Albedo | Sentinel-2 L2A broadband, 10–20 m → 50 m cell mean | OK |

### 4. Scenario vector a and baseline (Case 3)

| Component | Value | Baseline | Source | Status |
| --- | --- | --- | --- | --- |
| ΔV_f | +0.02 | Current FVC; plantable = sidewalk buffer ≥3 m ∪ WorldCover 2021 grass/bare − current canopy | Sentinel-2, Meta/WRI, OSM, WorldCover | OK / DERIVED |
| ΔV_f → tree count | ÷ crown area | *Platanus* 80–150 m²; *C. camphora* 60–100 m² | Literature | OK |
| Δα_r | 0 | Sentinel-2 albedo (retained in c_sub) | As in 3 | OK |
| ΔR_wall | → 2.0 m²K/W | ≤2000: K ≈ 2.0 (R 0.5); 2001–2010: JGJ 134-2001 K ≤ 1.5 (R 0.67); >2010: JGJ 134-2010 Table 4.0.4 K ≤ 1.0 (R 1.0) | WSF Evolution / GAIA; JGJ 134-2010 | OK / DERIVED |
| ΔR_wall surface | Buildings ≤2000 in window | Facade area = perimeter × height × 0.75 | OSM + CNBH-10m | DERIVED |
| ΔS_emit | −40% to −50% | E_road weights (§2) | §2 | OK |
| ΔS_emit extent | All district road edges | District road length | OSM | DERIVED |

### 5. Stage 2 knowledge libraries

| Library | Case 3 coverage check |
| --- | --- |
| Domain Knowledge (319) | Cfa × LCZ 2–3 × mid-rise high-density entries by energy balance / dispersion / building energy / vegetation cooling |
| Downscaling δ_k | Entry count for T / PM / E under Cfa × LCZ 2–3 × four weekly wind angles × material |
| Intervention Outcomes (208) | Cfa-matched combined / retrofit / LEZ / greening counts and effect sizes |
| C_prior, ρ | Trained version identifiers |

### 6. Stage 3 decoding and BCI

Decoders D_m take no additional external input.

**6.1 Reference effects ref_m**

| Domain | ref_m | Sign |
| --- | --- | --- |
| T_surf | 2.5 °C | Reduction positive; cooling season only, December main week zero |
| PM2.5 | 10 µg/m³ | Reduction positive |
| E | 20% | Reduction positive |
| Coverage | 8 pp | Increase positive |

**6.2 Cost side Cost_A**

| Item | Source | Value | Status |
| --- | --- | --- | --- |
| External insulation | Nanjing PRTC lot GLFJ2500704-01SGGH | Facade 49,778 m², award CNY 10,957,472.44 → ≈220 CNY/m²; main case 250, sensitivity 200–350 | OK |
| Nursery stock | Huai'an HURD, *2024 Market Price Information No. 1* | *Platanus* 12/15 cm: 450 / 820 CNY per tree; planting ×1.0 | OK |
| LEZ enforcement | Nanjing procurement, 2023 remote-sensing O&M | 16 units, CNY 800,000/yr; apportioned window ÷ district road length | OK |
| District road length | OSM | Apportionment base | DERIVED |

**6.3 Cost reference**

| Item | Source | Value | Status |
| --- | --- | --- | --- |
| Standard retrofit unit price | Nanjing PRTC lot JYFJ2600124-03SGGH | 85,200 m², award CNY 16,838,820.08 → ≈198 CNY/m² | OK |
| C_ref | 198 CNY/m² × window floor area | ≈CNY 8.0 ×10⁷ (400,000 m²) | DERIVED |

**6.4 BCI**

| Item | Definition |
| --- | --- |
| Effect score | B = Σ_m w_m · clip(Δȳ^(m) / ref_m, −1, 1), Σ w_m = 1 |
| Cost ratio | c = Cost_A / C_ref |
| Index | BCI = max(B, 0) / (max(B, 0) + c) |
| Anchor | 0.5 ⇔ weighted effect equals standard-retrofit cost ratio |
| Weights | Equal; sensitivity w_T = 0.4 |
| Clipping | Aggregate level only; within-domain negatives retained |
| Cost basis | One-off, undiscounted, excl. maintenance and repainting |
| Interval | Common MC sample; median with 2.5 / 97.5 percentiles |

### 7. Baseline comparison only (not model inputs)

| Item | Source | Status |
| --- | --- | --- |
| Landsat 8/9 C2 L2 LST, one winter and one summer scene | USGS EarthExplorer | OK |
| Nearest CNEMC station, four-week daily mean PM2.5 | §1.2 | OK |

## Part 2 — Configuration

### A. Fixed across cases

| Parameter | Value |
| --- | --- |
| Weights | Single checkpoint θ; per-city LoRA adapter (Eq. 17) as used in Exp. 1–3, no retraining |
| Architecture | W = 168 h; Transformer 6 layers, d = 256; GAT 8 heads; three edge classes; wind-reachability rule |
| Rollout | H = 168 h; coarsening hourly → 6 h → 72 h → daily |
| Paired arms | Common anchored initial state; no re-anchoring in either arm |
| Boundary | Evaluation weeks within 2023 observations; halo ring from encoded Z^(t); no city-scale baseline run |
| Grounding | Eq. 8–9 projection on both arms; batched; fixed 5 iterations; no per-step tolerance sync; residuals reported post hoc (A.10) |
| Downscaling | Eq. 10, K = 5, shared δ_k |
| Decoding | Four domains always emitted |
| Uncertainty | MC T = 30, α = 0.05; single sample set across domains and BCI; low confidence = PI contains zero |
| BCI | ref_m per §6.1; C_ref per city; signs per §6.1; clipping per §6.4 |
| Week selection | Af 1 week; Cfa / Dfa 4 seasonal weeks; main week = season with active primary pathway; MODIS ≥4 clear days, no heavy-haze day, no missing wind |
| Subgraph | Intervention footprint + adjacency L = 2 + wind-reachable; window-level → window parents, district policy → all district cells |
| Geometry | SVF, H/W, λ_p, c_sub prepared offline; runtime recomputes only intervention-modified geometry |
| Runtime protocol | 5 warm-up + 30 valid edits; cold-start full evaluation ×5; per-stage wall-clock and GPU (CUDA events, synchronise per stage); stages Grasshopper → IPC → geometry → retrieval → encoding → rollout → projection → downscaling → rendering; preview (1 week, T = 10) vs submitted (rule weeks, T = 30); timings from submitted |

### B. Rule fixed, values case-dependent

| Parameter | Rule |
| --- | --- |
| V_mod | Set by intervention type |
| N^(L)(V_mod) | Adjacency L = 2 + wind-reachable |
| Re-encoding | Cells with changed input modality only |
| K_i, δ_k | Matched from c, c_sub |
| Main week | Per A |

### C. Case 3 (Nanjing) overrides

| Parameter | Value | Rationale |
| --- | --- | --- |
| Subgraph | District cells + L = 2 + wind-reachable + halo, ≈250–400 parents | District-level ΔS_emit covers all road cells |
| Weeks | 4 (December main; March, June, September) | Cfa rule |
| Adapter | Nanjing | Per-city |
| Active components | ΔS_emit, ΔR_wall, ΔV_f; Δα_r = 0 | Case definition |
| Edge attributes | District E_road × (1 − \|ΔS_emit\|); NOx and primary PM scaled equally | Emissions enter via edge attributes + FiLM |
| V_mod | District road cells ∪ window cells | Compound intervention |
| Re-encoding | 1–4 parent cells with canopy change | S_emit, R_wall not observation modalities |
| Runtime geometry | None; 100 sub-cell canopy fractions updated; baseline geometry offline | Building geometry unchanged |
| Week condition | Exclude daily mean PM2.5 > 115 µg/m³ | Winter haze |
| Retrieval context | Cfa × LCZ 2–3 × mid-rise high-density | Per-city |
| Energy output | Total % primary; cooling / heating % separate | Both seasons active |
| Energy baseline | Reconstructed field, % of model baseline | No building-level disclosure |
| T in BCI | December main week zero | Winter cooling not a benefit |
| PM basis | Includes secondary chemistry (ΔS_emit → NOx) | Primary contribution 7–8% |
| Window candidates | Gulou: Zhongyangmen, Hehui–Sanpailou; Xuanwu: Liaojiaxiang (282 Zhongyang Rd) | 2023 retrofit list; near Shanxi Road station |
| Edit script | ΔS_emit 30–60%; ΔR_wall 1.5 / 2.0 / 2.5; ΔV_f 0–0.04; two replanting layouts | Case parameters |
| Cost base | District road length (OSM) | District policy |
| C_ref | 198 CNY/m² × window floor area | JYFJ2600124-03SGGH |

### D. Invariant for Case 3

H, T, α, grounding thresholds, δ_k library, BCI definition and its three elements,
re-anchoring, and the low-confidence criterion are shared across cases. Case-specific
overrides would invalidate the single-checkpoint claim and cross-case BCI comparability.

## Part 3 — Runtime ledger (Case 3, Nanjing)

| Module | Item | Parameters | GPU busy (s) | Cumulative (s) |
| --- | --- | --- | --- | --- |
| io | tensors to device | 86 MB, pinned H2D | 0.10 | 0.10 |
| stage2 | retrieval embed + cosine | 400×4 × 1,319 | 0.10 | 0.20 |
| stage1 | warmup, cudnn autotune | N = 400, W = 168 | 0.70 | 0.90 |
| stage1 | encode | CNN + GAT + Transformer, 4 weeks | 0.30 | 1.20 |
| stage1 | rollout, baseline arm | 672 steps, 5 projections, ≈22 launches/step | 1.90 | 3.10 |
| stage1 | rollout, scenario arm | as above | 1.90 | 5.00 |
| stage1 | C^(loc) accumulation | 672 steps | 0.30 | 5.30 |
| stage3 | decode + MC | 400×1,344×4×30 | 0.40 | 5.70 |
| stage3 | downscale | 100 sub-cells, K = 5 | 0.10 | 5.80 |
| stage3 | closure audit | 400×1,344×30 | 0.50 | 6.30 |
| total | — | wall 26.5 s, GPU 6.3 s, 24% busy | — | 6.30 |
