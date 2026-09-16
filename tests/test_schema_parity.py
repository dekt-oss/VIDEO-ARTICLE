"""스키마 정합성 가드 — 코드가 쓰는 컬럼이 DB 에 실제로 있는가.

왜 이 파일이 있는가(실측 사고): `engine/report_draft.generate_report_draft` 는 반환 dict 를
`report_db.upsert_report_draft` 가 **그대로** PostgREST 로 보낸다. 그래서 dict 에 컬럼이 아닌
키가 하나라도 있으면 워커가 `42703` 으로 죽는다.

실제로 `video_flow` 가 0019 에서 누락된 채 계속 있었고, `report_drafts` 21행 중 파이썬 워커가
만든 행은 **0건**이었다(전부 Edge Function 산출물). 순수 함수 테스트가 39개나 통과하는 동안
파이프라인의 마지막 한 걸음이 조용히 실패하고 있었다.

이 테스트는 마이그레이션 파일에서 컬럼을 파싱해 코드와 대조한다 — DB 접속 없이 돈다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))


def columns_of(table: str) -> set[str]:
    """마이그레이션 전체를 훑어 해당 테이블의 컬럼 집합을 만든다.

    `create table` 본문 + 이후의 `alter table ... add column` 을 누적한다. 컬럼을 지우는
    마이그레이션은 이 저장소에 아직 없어서 다루지 않는다(생기면 여기에 추가해야 한다).
    """
    cols: set[str] = set()
    create_re = re.compile(
        rf"create\s+table\s+(?:if\s+not\s+exists\s+)?{table}\s*\((.*?)\n\);",
        re.S | re.I)
    alter_re = re.compile(
        rf"alter\s+table\s+{table}\s+add\s+column\s+(?:if\s+not\s+exists\s+)?(\w+)",
        re.I)
    for path in MIGRATIONS:
        sql = path.read_text(encoding="utf-8")
        for body in create_re.findall(sql):
            for line in body.splitlines():
                line = line.split("--")[0].strip()
                if not line or line.lower().startswith(
                        ("primary key", "unique", "constraint", "foreign key", "check")):
                    continue
                m = re.match(r"(\w+)\s+", line)
                if m:
                    cols.add(m.group(1))
        cols.update(m.lower() for m in alter_re.findall(sql))
    return cols


def test_migration_parser_finds_known_columns():
    """파서 자체가 맞는지 먼저 확인한다 — 파서가 비면 아래 검사가 전부 공허하게 통과한다."""
    cols = columns_of("report_drafts")
    assert {"report_id", "fact_sheet", "script_md", "scenes", "self_check",
            "compliance"} <= cols
    assert "존재하지않는컬럼" not in cols


def test_report_draft_row_keys_all_exist_as_columns():
    """★ 이 검사가 있었으면 video_flow 누락이 CI 에서 걸렸다."""
    from engine import report_draft

    src = (ROOT / "engine" / "report_draft.py").read_text(encoding="utf-8")
    body = src.split("def generate_report_draft")[1].split("\ndef ")[0]
    # `return {` 블록의 최상위 문자열 키만 뽑는다.
    ret = body.split("return {")[1]
    keys = set(re.findall(r'^\s{8}"(\w+)":', ret, re.M))
    assert keys, "반환 dict 키를 못 읽었다 — 이 테스트가 무력하다"

    cols = columns_of("report_drafts")
    missing = sorted(keys - cols)
    assert not missing, (
        f"report_drafts 에 없는 컬럼을 쓰고 있다: {missing}. "
        f"마이그레이션을 추가하거나 반환 dict 에서 키를 빼라 — 안 그러면 워커가 42703 으로 죽는다."
    )
    assert report_draft.generate_report_draft  # import 가 실제로 되는지


@pytest.mark.parametrize("table,reader", [
    ("report_drafts", "get_report_draft"),
    ("report_directives", "get_report_directive"),
])
def test_report_db_select_lists_reference_real_columns(table, reader):
    """select 목록에 없는 컬럼을 적으면 조회가 통째로 400 이 된다."""
    src = (ROOT / "engine" / "report_db.py").read_text(encoding="utf-8")
    block = src.split(f"def {reader}")[1].split("\ndef ")[0]
    m = re.search(r'\.select\(\s*((?:"[^"]*"\s*)+)\)', block, re.S)
    assert m, f"{reader} 의 select 목록을 못 읽었다"
    # 인접 문자열 리터럴이 이어붙은 형태다 — 리터럴만 꺼내 이은 뒤 콤마로 나눈다.
    joined = "".join(re.findall(r'"([^"]*)"', m.group(1)))
    selected = {c.strip() for c in joined.split(",") if c.strip()}
    missing = sorted(selected - columns_of(table))
    assert not missing, f"{reader} 가 {table} 에 없는 컬럼을 조회한다: {missing}"


def test_report_sources_columns_match_engine_writes():
    """원문 보관 행(engine/report_source.store_packet)의 키도 같은 방식으로 고정한다."""
    src = (ROOT / "engine" / "report_source.py").read_text(encoding="utf-8")
    block = src.split("def store_packet")[1].split("\ndef ")[0]
    keys = set(re.findall(r'^\s{8}"(\w+)":', block, re.M))
    assert keys, "store_packet 의 키를 못 읽었다"
    missing = sorted(keys - columns_of("report_sources"))
    assert not missing, f"report_sources 에 없는 컬럼을 쓴다: {missing}"


def test_draft_request_queue_carries_mode():
    """[재검사]가 워커로 가려면 큐에 mode 가 있어야 한다(0035).

    ★ 세 곳이 동시에 맞아야 동작한다 — 마이그레이션 컬럼 / 워커의 select / Next 라우트의
      insert. 하나만 빠지면 재검사 요청이 조용히 '초안 전체 재생성'이 되거나 400 이 된다.
    """
    assert "mode" in columns_of("report_draft_requests")

    db = (ROOT / "engine" / "report_db.py").read_text(encoding="utf-8")
    claim = db.split("def claim_report_draft_requests")[1].split("\ndef ")[0]
    assert "mode" in claim, "워커가 mode 를 조회하지 않는다"

    worker = (ROOT / "engine" / "report_draft.py").read_text(encoding="utf-8")
    assert 'mode == "recheck"' in worker, "워커가 recheck 를 분기하지 않는다"
    assert "recheck_compliance(r[\"report_id\"])" in worker

    route = (ROOT / "web/app/api/report-compliance-check/route.ts").read_text(encoding="utf-8")
    assert 'mode: "recheck"' in route, "재검사 라우트가 mode 를 적재하지 않는다"
    assert "functions/v1/generate-report-draft" not in route, (
        "재검사가 아직 엣지를 부른다 — 엣지에는 근거 게이트 재계산이 없다")


def test_draft_request_queue_carries_instruction():
    """④ 화면의 "세부 수정 요청"이 워커까지 가야 한다(0038).

    ★ 실제로 끊겨 있었다 — 라우트가 instruction 을 읽어만 두고 큐에 넣지 않았고, 큐 테이블에
      담을 칸도 없었다. 그래서 무엇을 적든 초안이 똑같이 나왔다(논문 라인은 엣지로 넘겨 동작).
      마이그레이션 컬럼 / 라우트의 insert / 워커의 select·전달, 네 곳이 다 맞아야 한다.
    """
    assert "instruction" in columns_of("report_draft_requests")

    route = (ROOT / "web/app/api/report-generate-draft/route.ts").read_text(encoding="utf-8")
    insert = route.split(".insert(")[1].split(";")[0]
    assert "instruction" in insert, "라우트가 instruction 을 큐에 넣지 않는다"

    db = (ROOT / "engine" / "report_db.py").read_text(encoding="utf-8")
    claim = db.split("def claim_report_draft_requests")[1].split(chr(10) + "def ")[0]
    assert "instruction" in claim, "워커가 instruction 을 조회하지 않는다"

    worker = (ROOT / "engine" / "report_draft.py").read_text(encoding="utf-8")
    assert 'process_report(r["report_id"], str(r.get("instruction") or ""))' in worker, (
        "워커가 instruction 을 생성 단계로 넘기지 않는다")
    assert "report_scriptgen.generate(fact_sheet, instruction" in worker, (
        "대본 생성이 instruction 을 받지 않는다")


def test_draft_request_queue_carries_version_types():
    """초안 요청의 "이어서 만들 지시서 버전"이 워커까지 가야 한다(0046, 설계안 v2).

    컬럼 / 두 라우트의 insert / 두 워커의 select·전달 — 어느 하나가 빠지면 버튼은 버전을
    받는데 지시서는 안 만들어지고, 화면은 "만드는 중"을 영영 보여준다.
    """
    for table in ("draft_requests", "report_draft_requests"):
        assert "version_types" in columns_of(table), table

    for name in ("generate-draft", "report-generate-draft"):
        route = (ROOT / f"web/app/api/{name}/route.ts").read_text(encoding="utf-8")
        insert = route.split(".insert(")[1].split(";")[0]
        assert "version_types" in insert, f"{name} 라우트가 version_types 를 큐에 넣지 않는다"

    db = (ROOT / "engine" / "db.py").read_text(encoding="utf-8")
    claim = db.split("def claim_draft_requests")[1].split(chr(10) + "def ")[0]
    assert "version_types" in claim, "논문 워커가 version_types 를 조회하지 않는다"
    rdb = (ROOT / "engine" / "report_db.py").read_text(encoding="utf-8")
    rclaim = rdb.split("def claim_report_draft_requests")[1].split(chr(10) + "def ")[0]
    assert "version_types" in rclaim, "리포트 워커가 version_types 를 조회하지 않는다"

    for name in ("draft", "report_draft"):
        worker = (ROOT / "engine" / f"{name}.py").read_text(encoding="utf-8")
        assert "requested_versions(r)" in worker and "chain_directives(" in worker, (
            f"{name} 워커가 초안 뒤 지시서를 잇지 않는다")


def test_script_fingerprint_contract_matches_between_engine_and_web():
    """지문 계약이 갈리면 "검증 이후 수정됨" 경고가 **항상** 켜져 늑대소년이 된다."""
    ts = (ROOT / "web/lib/scriptRevision.ts").read_text(encoding="utf-8")
    assert 'createHash("sha256")' in ts
    assert 'digest("hex").slice(0, 16)' in ts
    py = (ROOT / "engine/script_revision.py").read_text(encoding="utf-8")
    assert "hashlib.sha256" in py
    assert "hexdigest()[:16]" in py


def test_validated_hash_columns_exist_in_migrations():
    """④ 경고와 승인 흔적은 이 두 컬럼이 있어야 동작한다(0040)."""
    assert "validated_script_hash" in columns_of("report_drafts")
    assert "validated_at_approval" in columns_of("report_published")


def test_recheck_recomputes_selfcheck_instead_of_reusing_it():
    """재검사가 옛 self_check 를 재사용하면 고친 문장에 옛 빨간 깃발이 남는다(P1-2)."""
    src = (ROOT / "engine" / "report_draft.py").read_text(encoding="utf-8")
    block = src.split("def recheck_compliance")[1].split(chr(10) + "def ")[0]
    assert "report_selfcheck.check(" in block, "재검사가 자기검증을 다시 돌리지 않는다"
    assert "script_revision.sync_scenes(" in block, "편집된 대본으로 씬을 맞추지 않는다"
    assert 'draft.get("self_check")' not in block, "옛 self_check 를 재사용한다"


def test_directive_prompt_drops_scenes_that_no_longer_match_the_script():
    """⑤ 입력에 옛 씬이 실리면 운영자가 지운 문장이 되살아난다(P1-1)."""
    src = (ROOT / "engine" / "report_directive.py").read_text(encoding="utf-8")
    assert "scenes_match_script(" in src
    block = src.split("def scene_block")[1].split(chr(10) + "def ")[0]
    assert "없다" in block, "어긋난 씬을 비울 때 이유를 알려 주지 않는다"


def test_ledger_job_kind_is_constrained_in_migrations():
    """0039 가 외래키를 뗀 자리를 CHECK 로 메운다 — 'banana' 가 들어가면 안 된다(P2-1)."""
    sql = "".join(p.read_text(encoding="utf-8") for p in MIGRATIONS)
    assert "render_job_kind in ('paper', 'report')" in sql


def test_report_render_tags_the_ledger_as_report():
    """0039 배선이 실제로 payload 까지 내려가는가(리뷰 Test 4).

    ★ 이게 없으면 리포트 렌더 비용이 원장에서 통째로 빠진다 — 실사형 시험 렌더에서 $1.47 을
      쓰고 원장이 0행이었던 사고가 정확히 그것이다(외래키 위반으로 전부 거부됐다).
    """
    src = (ROOT / "engine" / "report_render.py").read_text(encoding="utf-8")
    assert 'render_job_kind="report"' in src, "리포트 렌더가 원장에 종류를 알리지 않는다"

    cost = (ROOT / "engine" / "cost.py").read_text(encoding="utf-8")
    assert '"render_job_kind": render_job_kind' in cost, "원장 행에 종류가 실리지 않는다"


def test_duplicate_draft_request_contract_is_explicit():
    """진행 중 요청이 있을 때 새 지시를 조용히 버리지 않는다(리뷰 §9).

    예전에는 queued/processing 이 있으면 무시하고 202 를 돌려줘, 운영자가 새로 적은
    "리스크를 더 강조"가 어디에도 닿지 않는데 화면은 성공처럼 보였다.
    """
    route = (ROOT / "web/app/api/report-generate-draft/route.ts").read_text(encoding="utf-8")
    assert "status: 409" in route, "생성 중 요청을 거절하는 경로가 없다"
    assert ".update({ instruction })" in route, "대기 중 요청의 지시를 갱신하지 않는다"


def test_draft_buttons_dispatch_the_worker_not_just_enqueue():
    """버튼이 큐에만 넣고 끝나면 다음 안전망 크론까지 기다린다.

    ★ 2026-08-12 부터 그 크론은 하루 3번(KST 09/15/21)이라 대기가 몇 시간이다
      (docs/deviation-cron-cost.md). 디스패치가 기본 경로라는 이 단언이 그만큼 더 중요해졌다.

    ★ 실제로 그랬다 — 큐 전용으로 바꾸면서 그 큐를 집어가는 것을 만들지 않아 버튼이
      아무 일도 하지 않았다. 렌더·발행 버튼은 이미 workflow_dispatch 를 부른다(trigger-render.ts).
      초안·재검사도 같아야 한다. 크론은 디스패치가 막혔을 때의 폴백이지 기본 경로가 아니다.
    """
    for name in ("report-generate-draft", "report-compliance-check"):
        src = (ROOT / f"web/app/api/{name}/route.ts").read_text(encoding="utf-8")
        assert "triggerReportDraft" in src, f"{name} 이 워커를 디스패치하지 않는다"

    trig = (ROOT / "web/lib/trigger-render.ts").read_text(encoding="utf-8")
    block = trig.split("export function triggerReportDraft")[1].split("\n}")[0]
    assert "report-draft.yml" in block
    # ★ inputs 를 보내면 GitHub 이 422 로 거절한다 — report-draft.yml 은 mode 를 선언하지 않는다.
    assert "null" in block, "report-draft.yml 에는 inputs 를 보내면 안 된다"


def test_every_queue_worker_has_dispatch_and_a_cron_fallback():
    """디스패치(빠른 경로)와 크론(폴백)이 둘 다 있어야 한다.

    ★ 2026-09-06 구조 변경 — 크론이 **개별 워크플로에서 queues.yml 로 옮겨갔다.**
      GitHub 은 잡 단위로 1분씩 올림 청구하는데, 4개가 각자 하루 3회 크론을 돌면 전부
      "큐 비었음"으로 몇 초에 끝나면서도 매번 4분이 나갔다(월 324분).
      그래서 검사도 바뀐다 — "이 파일에 cron 이 있나"가 아니라
      **"폴백이 존재하고, 그 폴백이 이 큐를 실제로 확인하고 처리하나"** 를 본다.
      (파일에 cron 만 있고 큐를 안 보면 폴백이 아니라 빈 폴링일 뿐이다.)
    """
    queues = (ROOT / ".github/workflows/queues.yml").read_text(encoding="utf-8")
    assert "cron:" in queues, "크론 폴백이 통째로 사라졌다"

    for wf_name, queue_table, module in [
        ("publish.yml", "upload_requests", "engine.publish"),
        ("report-draft.yml", "report_draft_requests", "engine.report_draft"),
        ("report-video.yml", "report_render_jobs", "engine.report_render"),
        ("report-publish.yml", "report_upload_requests", "engine.report_publish"),
    ]:
        wf = (ROOT / ".github/workflows" / wf_name).read_text(encoding="utf-8")
        # 대시보드 버튼이 이 워크플로를 이름으로 직접 깨운다(web/lib/trigger-*.ts).
        assert "workflow_dispatch:" in wf, f"{wf_name}: 라우트가 디스패치로 부르므로 필수"
        # 디스패치가 막혔을 때(토큰 없음·API 실패) 크론이 받아야 한다.
        assert queue_table in queues, f"{wf_name}: 폴백이 {queue_table} 를 확인하지 않는다"
        assert module in queues, f"{wf_name}: 폴백이 {module} 로 처리하지 않는다"


def test_report_render_jobs_can_store_qa():
    """리포트 라인은 지금까지 아무 검사도 받지 않고 나갔다 — 0036 이 그 자리를 만든다."""
    assert "qa" in columns_of("report_render_jobs")

    rr = (ROOT / "engine" / "report_render.py").read_text(encoding="utf-8")
    assert "render_qa.run_qa" in rr, "리포트 라인이 mp4 실검을 안 부른다"
    assert 'qa["board"]' in rr and 'qa["cut_map"]' in rr

    db = (ROOT / "engine" / "report_db.py").read_text(encoding="utf-8")
    fn = db.split("def update_report_render_job")[1].split("\ndef ")[0]
    assert 'patch["qa"] = qa' in fn, "받아 놓고 저장하지 않으면 기록이 사라진다"


def test_board_verdicts_reach_the_job_record():
    """core_fill 이 계산되고 버려지면 승격 기준을 정할 데이터가 안 쌓인다."""
    r = (ROOT / "engine" / "render.py").read_text(encoding="utf-8")
    assert "board_qa_out" in r
    assert '"core_fill": round(res.core_fill, 4)' in r
    assert 'qa["board"] = board_qa' in r


# ── 렌더 잡 상태 어휘 — PY/TS 쌍둥이 (v3 §8-3) ──────────────────
def _ts_render_status_list(name: str) -> list[str]:
    """web/lib/renderStatus.ts 에서 배열 리터럴을 읽어 온다(노드 실행 없이)."""
    import re

    src = Path("web/lib/renderStatus.ts").read_text(encoding="utf-8")
    m = re.search(rf"export const {name}[^=]*=\s*\[(.*?)\]", src, re.S)
    assert m, f"{name} 을 renderStatus.ts 에서 못 찾았다"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_the_node_tested_module_copy_matches_the_canonical_list():
    """★ renderQueue.ts 는 두 줄을 **복제**한다 — node 는 import 에 ".ts" 를 요구하는데 tsc 는
    프로젝트 내 파일에서 그 확장자를 거부해(TS5097) 둘을 동시에 만족시킬 수 없다.
    복제를 허용하는 대신 갈리면 여기서 잡는다. 갈리면 degraded 잡이 '진행 중' 탭으로
    돌아가 영원히 안 보인다.
    """
    import re

    from engine import config

    src = Path("web/lib/work/renderQueue.ts").read_text(encoding="utf-8")
    m = re.search(r"const AWAITING_HUMAN\s*=\s*\[(.*?)\]", src, re.S)
    assert m, "renderQueue.ts 에서 AWAITING_HUMAN 을 못 찾았다"
    assert re.findall(r'"([^"]+)"', m.group(1)) == list(config.RENDER_STATUS_AWAITING_HUMAN)


def test_render_status_vocabulary_matches_between_python_and_ts():
    """★ 이 목록이 갈리면 조용히 망가진다 — 웹은 '살아 있는 잡'으로 안 세는데 엔진은 그 상태로
    두는 순간, 같은 지시서에 **두 번째 렌더 잡**이 생긴다(같은 영상 두 번, 비용 두 번).
    """
    from engine import config

    assert _ts_render_status_list("RENDER_STATUS_IN_PROGRESS") == list(
        config.RENDER_STATUS_IN_PROGRESS)
    assert _ts_render_status_list("RENDER_STATUS_AWAITING_HUMAN") == list(
        config.RENDER_STATUS_AWAITING_HUMAN)
    assert _ts_render_status_list("RENDER_STATUS_TERMINAL") == list(
        config.RENDER_STATUS_TERMINAL)


def test_the_watchdog_never_requeues_a_job_that_is_waiting_for_a_human():
    """★ 워치독이 승인 대기 잡을 queued 로 되돌리면 **승인이 지워진다.**

    재큐 대상은 '워커가 죽어서 멈춘 잡'이지 '사람이 아직 안 본 잡'이 아니다. 두 목록이
    겹치는 순간 degraded 승인은 아무 의미가 없어진다.
    """
    import inspect

    from engine import config, db, report_db

    assert not (set(config.RENDER_STATUS_IN_PROGRESS)
                & set(config.RENDER_STATUS_AWAITING_HUMAN))
    for fn in (db._reclaim_stale_render_jobs, report_db._reclaim_stale_report_render_jobs):
        src = inspect.getsource(fn)
        assert "RENDER_STATUS_IN_PROGRESS" in src, f"{fn.__name__}: 정본 상수를 안 쓴다"
        assert "AWAITING_HUMAN" not in src, f"{fn.__name__}: 사람 대기 잡을 재큐하면 안 된다"


def test_duplicate_job_guards_count_human_waiting_jobs_as_active():
    """활성 목록에서 빠뜨리면 승인 대기 중인 지시서에 두 번째 잡이 생긴다."""
    from engine import config

    assert set(config.RENDER_STATUS_AWAITING_HUMAN) <= set(config.RENDER_STATUS_ACTIVE)
    for route in ("web/app/api/directive-approve/route.ts",
                  "web/app/api/report-directive-approve/route.ts",
                  "web/app/api/report-render-retry/route.ts"):
        src = Path(route).read_text(encoding="utf-8")
        assert "RENDER_STATUS_ACTIVE" in src, f"{route}: 정본 목록을 안 쓴다"
        assert '"assembling"' not in src, f"{route}: 상태 목록을 다시 적었다 — 갈린다"


# ── §8-2 degraded 승인 배선 (0037) ──────────────────────────────
def test_degraded_approval_column_exists_in_a_migration():
    """status 를 'done' 으로 덮는 대신 컬럼을 둔다 — 무엇을 승인했는지가 남아야 한다."""
    sql = "\n".join(p.read_text(encoding="utf-8")
                    for p in Path("supabase/migrations").glob("*.sql"))
    for table in ("render_jobs", "report_render_jobs"):
        assert f"alter table {table}\n  add column if not exists degraded_approved_at" in sql, table


def test_upload_is_blocked_until_a_degraded_job_is_approved():
    """★ 승인 없이 올리면 결함이 그대로 발행된다 — 그게 이 상태를 만든 이유다."""
    for route in ("web/app/api/youtube-upload/route.ts",
                  "web/app/api/report-youtube-upload/route.ts"):
        src = Path(route).read_text(encoding="utf-8")
        assert "degraded_approved_at" in src, f"{route}: 승인 표식을 안 본다"
        assert 'job.status === "done"' in src, f"{route}: done 허용이 사라졌다"
        assert 'job.status !== "done" || !job.output_url' not in src, (
            f"{route}: 옛 게이트가 남아 승인된 degraded 도 막는다")


def test_approve_action_only_accepts_degraded_jobs():
    """다른 상태를 승인하면 '승인'이라는 말의 뜻이 사라진다."""
    for route in ("web/app/api/render-manage/route.ts",
                  "web/app/api/report-render-manage/route.ts"):
        src = Path(route).read_text(encoding="utf-8")
        assert '"approve_degraded"' in src, f"{route}: 액션 미등록"
        assert 'job.status !== "degraded"' in src, f"{route}: 상태 확인 없이 승인한다"
        assert 'status: "done"' not in src, f"{route}: 승인이 판정을 덮으면 기록이 사라진다"
