---
name: result-audit
description: Audit a SimAsset-Evaluation result bundle before import. Use to check submitted result folders for missing files or runs, unsupported formats, duplicate IDs, or conflicts and prepare an import handoff.
---

# 검사 결과 묶음 점검

1. [결과 묶음 점검 안내](../../../review/docs/결과_묶음_점검.md)를 읽습니다. 사용자가 지정한 결과 폴더와 별도로 마련한 예상 실행 목록을 확인합니다. 목록이 없으면 현재 있는 파일만 점검할 수 있다고 기록합니다.
2. `review/`에서 `simasset-review audit`를 실행하고 JSON과 종료 상태를 확인합니다. 예상 실행 대비 확인 범위, 유효·무효 개수, 문제 경로와 오류 코드, 경고를 정리합니다. 예상 목록이 없거나 예외로 요약 필드가 없을 때는 확인 범위를 그대로 적습니다.
3. 누락한 파일이나 실행, 동일한 파일의 중복, 같은 실행 ID의 내용 충돌을 구분합니다. 충돌하는 원본은 보존하고 어떤 묶음이 맞는지 확인할 수 있는 경로와 식별자를 제공합니다. 파일의 형식 검증과 에셋의 품질 판정은 구분해 적습니다.
4. 적재 담당자에게 묶음 위치, 예상 목록, 점검 결과, 예정 `namespace`와 `origin`을 전달할 수 있게 정리합니다. 이 스킬의 결과는 적재 전 점검입니다. 적재를 별도로 요청받으면 로컬은 [결과 검토 안내](../../../review/README.md#팀-결과-가져오기), 팀 서버는 [운영 안내](../../../.devcontainer/README.md#결과-가져오기와-테스트)로 이어갑니다.
