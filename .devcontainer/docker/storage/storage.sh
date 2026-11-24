#!/bin/sh
# MinIO 공유 버킷과 결과 폴더(review/evidence)를 맞춥니다. 팀원 모두 사용합니다.
#
#   .devcontainer/docker/storage/storage.sh push      # 로컬에만 있거나 바뀐 파일을 올림
#   .devcontainer/docker/storage/storage.sh pull      # 버킷에만 있거나 바뀐 파일을 받음 (SHA-256 검증)
#   .devcontainer/docker/storage/storage.sh list      # 버킷 내용 요약
#   옵션: --prefix runs/simasset-env-v4.2/   일부만,  --dry-run   세기만
#
# 양쪽 모두 지우지 않습니다. 접속 정보는 프로젝트 루트 .env의 MINIO_* 값을 씁니다.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
settings="$root/.env"
data="${STORAGE_DIR:-$root/review/evidence}"
if [ ! -f "$settings" ]; then
  echo "$settings 가 없습니다. .env.sample 을 복사해 MINIO_* 값을 채워주세요." >&2
  exit 1
fi
mkdir -p "$data"
mode=rw
[ "${1:-}" = pull ] || mode=ro
docker build -q -t simasset-storage:local -f "$here/storage.Dockerfile" "$here" >/dev/null
exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$settings:/config/project-settings:ro" \
  -v "$here:/opt/storage:ro" \
  -v "$(cd "$data" && pwd):/data:$mode" \
  simasset-storage:local python -I /opt/storage/sync.py "$@"
