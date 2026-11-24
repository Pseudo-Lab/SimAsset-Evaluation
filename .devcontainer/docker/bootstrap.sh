#!/bin/sh
# DB 스키마와 Grafana 읽기 전용 구성을 준비합니다. 저장소의 기존 명령을 그대로 호출합니다.
set -eu
cd /workspace/review

simasset-review init-db

# grafana_readonly.py는 실행할 때마다 읽기 전용 계정 비밀번호를 회전합니다.
# 구성 파일과 DB 계정이 모두 있으면 다시 실행하지 않습니다.
# 강제로 다시 만들려면 GRAFANA_RECONFIGURE=1 (예: compose.sh run --rm -e GRAFANA_RECONFIGURE=1 bootstrap).
datasource="$SIMASSET_STATE_DIR/grafana/provisioning/datasources/simasset.yaml"
role=$(psql "$SIMASSET_DATABASE_URL" -tAc "SELECT 1 FROM pg_roles WHERE rolname='simasset_grafana_reader'")
if [ ! -f "$datasource" ] || [ "$role" != "1" ] || [ "${GRAFANA_RECONFIGURE:-0}" = "1" ]; then
  python scripts/grafana_readonly.py
else
  echo 'Grafana 읽기 전용 구성 유지'
fi
