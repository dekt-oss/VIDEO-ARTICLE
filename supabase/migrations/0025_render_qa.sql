-- 렌더 QA 게이트 (수정지시서 v2 §7) — docs/deviation-hook-retention-v2.md
-- engine.render 가 렌더 직후 실제 mp4 를 ffprobe/ffmpeg 로 실검한 결과를 render_jobs.qa 에 저장한다.
-- 대시보드 ⑥ 렌더 결과가 이 값을 읽어 하드 실패/경고 배지를 보여준다(사람이 발행 전 확인).
--
-- qa 형식: {"passed": bool, "hard_fail": [문자열], "warnings": [문자열], "signals": {duration_sec, has_audio, ...}}
-- nullable — 기존 렌더 잡은 null(하위호환), 신규 렌더부터 채워진다.

alter table render_jobs add column if not exists qa jsonb;
