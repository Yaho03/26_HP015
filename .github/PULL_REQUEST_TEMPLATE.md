## 요약

<!--이 PR이 해결하는 문제와 주요 변경 사항을 1~3문장으로-->

## 관련 이슈

<!--Closes / Fixes / Resolves #NNN-->

- Closes #NNN

## 변경 내용

<!--주요 변경 파일과 내용을 bullet으로-->

-

## 스키마 변경 (해당 시)

- [ ] JSON Schema 수정 시 `additionalProperties: false` 유지 확인
- [ ] schema version 업데이트 (필드 추가 시 minor bump)
- [ ] `python3 -c "import json; json.load(open('FILE'))"` 검증 완료
- [ ] `docs/04_DATA_CONTRACT.md`와 일치

## 안전 영향 (해당 시)

<!--경보 임계값, Hysteresis, 진동 패턴, 좌표 변환 등 safety-critical 코드 변경 시 영향 분석-->

- [ ] 본 변경은 safety-critical 코드에 영향을 줌
- [ ] `docs/06_ALERT_RULES.md`와 일치 확인

## 체크리스트

- [ ] 관련 문서 업데이트 완료
- [ ] 코드에 하드코딩된 임계값 없음 (설정 파일 / DB 참조)
- [ ] `as any`, `@ts-ignore`, `@ts-expect-error` 미사용
- [ ] LSP diagnostic 에러 없음
- [ ] 빌드 / 테스트 통과

## 스크린샷 / 로그 (해당 시)

<!--대시보드 변경, 3D 트윈 변경, MQTT 메시지 캡처 등-->
