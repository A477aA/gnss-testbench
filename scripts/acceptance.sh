#!/usr/bin/env bash
# Прогон сценария на виртуальном стенде с проверкой ожидаемого вердикта.
#
#   scripts/acceptance.sh <сценарий> <критерии> <pass|fail> [каталог отчётов]
#
# EXPECT=fail — негативная проверка самого стенда: сценарий с внесёнными
# дефектами ОБЯЗАН провалить приёмку. Если он вдруг прошёл — значит, стенд
# перестал ловить дефекты, и это ошибка конвейера.
set -euo pipefail

scenario=${1:?укажи файл сценария}
criteria=${2:?укажи файл критериев}
expect=${3:?укажи ожидание: pass или fail}
out=${4:-reports}

[[ $expect == pass || $expect == fail ]] || { echo "ожидание должно быть pass или fail, получено: $expect" >&2; exit 2; }
[[ -f $scenario ]] || { echo "нет сценария: $scenario" >&2; exit 2; }
[[ -f $criteria ]] || { echo "нет критериев: $criteria" >&2; exit 2; }

name=$(basename "$scenario" .toml)
mkdir -p "$out"

args=(run "$scenario" --criteria "$criteria" --quiet
      --markdown "$out/$name.md" --json "$out/$name.json" --save-log "$out/$name.nmea")
# JUnit публикуем только для позитивных сценариев: ожидаемые провалы
# не должны краснеть во вкладке Tests у merge request
[[ $expect == pass ]] && args+=(--junit "$out/$name.junit.xml")

set +e
gnss-testbench "${args[@]}"
code=$?
set -e

case "$expect:$code" in
  pass:0) echo "✅ $name: приёмка пройдена, как и ожидалось" ;;
  fail:1) echo "✅ $name: стенд поймал дефект, приёмка провалена, как и ожидалось" ;;
  pass:1) echo "❌ $name: приёмка НЕ пройдена (см. $out/$name.md)" >&2; exit 1 ;;
  fail:0) echo "❌ $name: дефекты внесены, но приёмка прошла — стенд их не видит" >&2; exit 1 ;;
  *)      echo "❌ $name: ошибка запуска (код $code)" >&2; exit "$code" ;;
esac
