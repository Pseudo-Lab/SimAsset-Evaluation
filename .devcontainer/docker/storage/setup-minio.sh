#!/bin/sh
# [관리자 전용, 처음 한 번] MinIO 버킷과 버킷 전용 공용 계정을 만듭니다.
#
# 1. 프로젝트 루트 .env의 MINIO_ACCESS_KEY·MINIO_SECRET_KEY에 MinIO 관리자 키를 잠시 넣습니다.
# 2. 실행:  .devcontainer/docker/storage/setup-minio.sh
# 3. 확인을 모두 통과하면 그 두 줄이 버킷 전용 키로 바뀝니다. 관리자 키는 .env에 남지 않습니다.
#
# 선택:  MINIO_TEAM_USER=<계정 이름>  (기본 <버킷>-team)
#        MINIO_ROTATE=1                (같은 계정의 키를 다시 발급)
#
# 컨테이너는 .env에서 MINIO_* 값만 읽습니다. 비밀 값은 출력하지 않습니다.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
if [ ! -f "$root/.env" ]; then
  echo "$root/.env 가 없습니다. .env.sample 을 복사해 MINIO_* 값을 채워주세요." >&2
  exit 1
fi
docker build -q -t simasset-storage:local -f "$here/storage.Dockerfile" "$here" >/dev/null
exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e MINIO_TEAM_USER -e MINIO_ROTATE \
  -v "$root:/workspace" \
  simasset-storage:local python -I /workspace/.devcontainer/docker/storage/setup_minio.py
