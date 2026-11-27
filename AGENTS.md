# 저장소 작업 지침

- 작업을 시작할 때 [저장소 사용 안내](CONTRIBUTING.md)에서 실행 환경과 PR 절차를 확인합니다.
- 리뷰 화면과 결과 가져오기는 [review 안내](review/README.md)를, 검사 출력 형식은 [공통규약 v4](docs/검사환경-공통규약-전체본_v4.md)를 따릅니다. 컨테이너와 MinIO 작업은 [컨테이너 안내](.devcontainer/README.md)를 먼저 확인합니다.
- 결과를 가져오거나 테스트할 때는 전용 로컬 DB와 허용된 샘플을 사용합니다. 팀 서버나 원본 데이터를 변경하는 작업은 범위를 먼저 확인합니다.
- PR 제목은 `[Feat]`, `[Fix]`, `[Docs]`처럼 작업 유형으로 시작합니다. 작업에 맞는 방법으로 확인하고, PR 본문에 확인한 범위와 추가 확인이 필요한 부분을 남깁니다.
- PR을 준비할 때는 [`pr-prep` 스킬](.agents/skills/pr-prep/SKILL.md)을 참고합니다.
- 저장소 문서를 작성하거나 기존 안내를 점검할 때는 [`docs-update` 스킬](.agents/skills/docs-update/SKILL.md)을 참고합니다.
- 검사 결과 묶음의 누락·중복·충돌을 확인할 때는 [`result-audit` 스킬](.agents/skills/result-audit/SKILL.md)을 참고합니다.
