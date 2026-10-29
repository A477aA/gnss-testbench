#!/usr/bin/env bash
# Запись лога с реального приёмника и анализ по критериям.
#
#   scripts/capture.sh -p /dev/ttyUSB0 -d 300 -c criteria/rtk_static.toml -r 55.6948,37.36125
#
# Лог и отчёты складываются в logs/<дата>_<порт>/, чтобы прогоны не затирали друг друга.
set -euo pipefail

port=/dev/ttyUSB0
baud=115200
duration=120
criteria=""
reference=""

usage() {
  sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
  echo "Ключи: -p порт, -b скорость, -d секунд, -c критерии.toml, -r lat,lon"
  exit "${1:-0}"
}

while getopts "p:b:d:c:r:h" opt; do
  case $opt in
    p) port=$OPTARG ;;
    b) baud=$OPTARG ;;
    d) duration=$OPTARG ;;
    c) criteria=$OPTARG ;;
    r) reference=$OPTARG ;;
    h) usage 0 ;;
    *) usage 2 ;;
  esac
done

[[ -e $port ]] || { echo "порт $port не найден. Подключённые: $(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo нет)" >&2; exit 2; }
[[ -r $port && -w $port ]] || { echo "нет прав на $port — добавь пользователя в группу dialout" >&2; exit 2; }
command -v gnss-testbench >/dev/null || { echo "не установлен gnss-testbench: pip install -e ." >&2; exit 2; }

dir="logs/$(date +%Y%m%d_%H%M%S)_$(basename "$port")"
mkdir -p "$dir"
log="$dir/receiver.nmea"

echo "▶ Запись $port @ $baud бод, $duration с -> $log"
gnss-testbench capture --port "$port" --baud "$baud" --duration "$duration" -o "$log"

analyze=(analyze "$log" --markdown "$dir/report.md" --json "$dir/report.json" --quiet)
[[ -n $criteria ]] && analyze+=(--criteria "$criteria" --junit "$dir/junit.xml")
[[ -n $reference ]] && analyze+=(--reference "$reference")

set +e
gnss-testbench "${analyze[@]}"
code=$?
set -e

echo "▶ Отчёт: $dir/report.md"
grep -m1 "Итог приёмки" "$dir/report.md" || true
exit "$code"
