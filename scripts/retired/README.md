# 은퇴한 텔레그램 스크립트 (2026-11-22 정리)

스윙 매매 은퇴(§22.AO-67) 뒤에도 cron 으로 돌며 스윙 시절 지표를 재서 텔레그램을 보내던 스크립트들이다.
2026-11-21 `exit_watch` 가 설계상 100% 투자인 코어+J 에 "🔴 투자율 100% 상한 초과 — max_total_exposure_pct 가
안 먹고 있다" 오탐을 보낸 것이 계기. 지울 수도 있었지만 스윙 재개 시 참고용으로 남긴다.
각 `.sh`/`.py` 첫머리에 즉시 종료 가드가 있어 실수로 실행해도 아무것도 보내지 않는다.

| 스크립트 | 하던 일 | cron | 대체 |
|---|---|---|---|
| exit_watch.sh / .py | §22.AO-43 출구 교정 전진검증, 투자율 45% 대역, 진입 공급 | 6시간마다 | `scripts/core_daily.sh summary` (매일 07:15) |
| payoff_weekly_review.sh | 2026-07 손익비 실험(take_profit 0.20→0.50) 주간 검증 | 월 09:03 | 없음 — 실험 종료 |
| ao26_weekly_review.sh | §22.AO-26 (A-1 rsi2 보유일·A-3 시간청산·B 사이징) 주간 검증 | 목 09:05 | 없음 — §22.AO-43 으로 전진 해소 |
| events_scan_report.sh | 이벤트 스캔 결과 보고 | (cron 없음) | 없음 — events_scan 잡 은퇴 |
| exit_check_report.sh | 청산 점검 보고 | (cron 없음) | 없음 — 스윙 청산 없음 |
| ic_remeasure_20260702.sh | 2026-07-02 1회성 IC 재측정 | (cron 없음) | 없음 |
| rsi2_exit_review_20260708.sh | 2026-07-08 1회성 rsi2 청산 검토 | (cron 없음) | 없음 |
| send_batch_report.sh | 배치 결과 수동 발송 | (cron 없음) | 없음 |

상태·결과 파일(`.exit_watch_state`, `ao26_review_result.txt`, `payoff_review_result.txt`)도 함께 옮겼다 —
매 실행마다 갱신돼 git 작업트리를 계속 더럽히던 파일들이다.

## 지금 남아 있는 텔레그램 (2026-11-22 기준)
- **코어 배분** — 엔진 core_allocate(화~토 00:30): 주문이 있을 때 주문·추세·J 교체 내역
- **코어 배분 점검** — `core_daily.sh alloc`(화~토 00:50): 미실행·실패면 🔴, 주문이 있었으면 요약
- **코어 일일 보고** — `core_daily.sh summary`(화~토 07:15): 총자산(재시작·총 실투입 대비), 추세·다음 판정 예상, 비중, 섀도, 경보
- **엔진 오류** — daily_pipeline 실패(notify_error), 자가진단 위반(토 11:00, 위반 시만), 보유 시세 결손
- **입출금 기록**, **모드 변경** — 사용자 조작 시
- **워치리스트** — 강한 신호 시(참고용 문구 포함, 매매 경로 아님)
- **실행 공백 감지** — `gap_watch.sh`(5분), **재부팅 후 검증** — `verify_v31_after_reboot.sh`(@reboot)
- **봇 명령** — /status /positions /last /perf /regime /analyze /queue (/signals 폐지)

스윙을 재개하면(`swing_entries_enabled=true` + 재시작) 엔진의 스윙 알림(📡 Pipeline 요약·시그널·사후분석 다이제스트)은
자동으로 다시 나간다(`SwingScheduler._swing_retired`). 이 폴더의 스크립트는 그때 필요하면 가드를 지우고 cron 에 다시 건다.
