---
name: pr-prep
description: Prepare a SimAsset-Evaluation pull request from a branch or working diff. Use when choosing its title, writing or reviewing its body, or checking what to verify before opening the PR.
---

# PR 준비

1. [저장소 사용 안내](../../../CONTRIBUTING.md)와 [PR 양식](../../../.github/pull_request_template.md)을 읽습니다. 기준 브랜치와 작업 트리 상태를 확인하고, PR에 들어갈 커밋과 아직 커밋되지 않은 변경을 살펴봅니다. 다른 사람이 작업한 변경이나 개인 설정이 섞여 있으면 범위를 확인합니다.
2. [커밋과 PR의 범위](../../../CONTRIBUTING.md#커밋과-pr의-범위)를 적용합니다. 변경 이유가 여럿이면 커밋 단위를 살펴보고, 별도로 검토·병합할 목적이 섞였으면 PR별 범위와 병합 순서를 제안합니다. 하나의 동작을 설명하고 확인하는 데 필요한 구현·테스트·문서는 같은 PR에 둡니다. 각 PR을 병합한 상태에서 기존 동작을 유지할 수 있는지 확인합니다.
3. 주된 작업을 보고 `[Feat]`, `[Fix]`, `[Docs]` 등으로 제목을 시작합니다. 요약에는 작업의 목적을 적고, 배경과 작업 내용에는 리뷰어가 알아야 할 구현·수정 범위를 남깁니다. 관련 이슈나 논의가 있으면 연결합니다.
4. 변경에 맞는 확인 방법을 선택합니다. 기능은 실행이나 테스트, 버그는 재현과 회귀 확인, 문서는 링크나 예시 명령 대조가 출발점입니다. 명령·화면·설정·출력 형식이 달라졌다면 [`docs-update`](../docs-update/SKILL.md) 절차로 관련 문서를 대조합니다. 실제로 확인한 내용과 추가 확인이 필요한 부분을 PR에 적습니다.
5. 제목, 본문, 확인한 범위를 준비합니다. 커밋·푸시·PR 게시·병합은 요청받은 범위에서 진행하고 GitHub에서 결과를 확인합니다. 팀의 기존 흐름대로 `main` 반영은 PR을 거칩니다.
