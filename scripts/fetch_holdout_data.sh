#!/bin/bash
# Fetch the real PM2.5 station observations used by station_holdout_eval.py and
# train_reference_model.py (full 2023: Jan-Aug train / Sep-Oct val / Nov-Dec
# test). Sources: EPA AQS (NYC), CNEMC via quotsoft.net mirror (Nanjing), NEA
# data.gov.sg (Singapore), qwd/LocationList (station coordinates), open-meteo
# archive (daily meteorological drivers), opentopodata (elevations, fetched by
# the eval script).
set -e
cd "$(dirname "$0")/../data/holdout/raw"
mkdir -p cn sg

curl -sL -O "https://aqs.epa.gov/aqsweb/airdata/daily_88101_2023.zip"
curl -sL -o cn_station_list.csv \
  "https://raw.githubusercontent.com/qwd/LocationList/master/POI-Air-Monitoring-Station-List-latest.csv"

for city in "nyc:40.7128:-74.0060" "nanjing:32.06:118.79" "singapore:1.35:103.82"; do
  n=${city%%:*}; rest=${city#*:}; lat=${rest%%:*}; lon=${rest##*:}
  [ -f "meteo_$n.json" ] || curl -s -o "meteo_$n.json" \
    "https://archive-api.open-meteo.com/v1/archive?latitude=$lat&longitude=$lon&start_date=2023-01-01&end_date=2023-12-31&daily=temperature_2m_mean,wind_speed_10m_max,precipitation_sum,surface_pressure_mean,shortwave_radiation_sum,relative_humidity_2m_mean&timezone=auto"
done

d="2023-01-01"
while [ "$d" != "2024-01-01" ]; do
  compact=$(echo "$d" | tr -d -)
  [ -f "cn/china_sites_$compact.csv" ] || \
    curl -s -o "cn/china_sites_$compact.csv" "https://quotsoft.net/air/data/china_sites_$compact.csv"
  [ -f "sg/pm25_$compact.json" ] || \
    curl -s -o "sg/pm25_$compact.json" "https://api.data.gov.sg/v1/environment/pm25?date=$d"
  d=$(date -j -f "%Y-%m-%d" -v+1d "$d" "+%Y-%m-%d" 2>/dev/null || date -d "$d + 1 day" "+%Y-%m-%d")
done
echo "done: $(ls cn | wc -l) CN files, $(ls sg | wc -l) SG files"
