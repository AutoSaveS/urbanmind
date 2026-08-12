#!/bin/bash
# Fetch the real PM2.5 station observations used by station_holdout_eval.py
# (Nov-Dec 2023 test window). Sources: EPA AQS (NYC), CNEMC via quotsoft.net
# mirror (Nanjing), NEA data.gov.sg (Singapore), qwd/LocationList (station
# coordinates), opentopodata (elevations, fetched by the eval script).
set -e
cd "$(dirname "$0")/../data/holdout/raw"
mkdir -p cn sg

curl -sL -O "https://aqs.epa.gov/aqsweb/airdata/daily_88101_2023.zip"
curl -sL -o cn_station_list.csv \
  "https://raw.githubusercontent.com/qwd/LocationList/master/POI-Air-Monitoring-Station-List-latest.csv"

d="2023-11-01"
while [ "$d" != "2024-01-01" ]; do
  compact=$(echo "$d" | tr -d -)
  [ -f "cn/china_sites_$compact.csv" ] || \
    curl -s -o "cn/china_sites_$compact.csv" "https://quotsoft.net/air/data/china_sites_$compact.csv"
  [ -f "sg/pm25_$compact.json" ] || \
    curl -s -o "sg/pm25_$compact.json" "https://api.data.gov.sg/v1/environment/pm25?date=$d"
  d=$(date -j -f "%Y-%m-%d" -v+1d "$d" "+%Y-%m-%d" 2>/dev/null || date -d "$d + 1 day" "+%Y-%m-%d")
done
echo "done: $(ls cn | wc -l) CN files, $(ls sg | wc -l) SG files"
