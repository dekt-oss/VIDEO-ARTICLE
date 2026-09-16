"""저장소 자동 정리 판정 테스트.

★ 이 테스트가 지키는 것은 하나다: **아직 확인 안 한 영상을 지우지 않는다.**
   2026-08-24 에 저장소가 한도를 넘겨 조직 전체가 정지된 사고를 계기로 만든 장치라,
   "많이 지우는 것"보다 "잘못 지우지 않는 것"이 훨씬 중요하다.
"""
from engine.storage_gc import Doomed, JobState, Obj, classify, directive_of, job_id_of, plan

D1 = "11111111-1111-1111-1111-111111111111"
D2 = "22222222-2222-2222-2222-222222222222"
J_KO = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
J_EN = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _paths(doomed: list[Doomed]) -> set[str]:
    return {d.path for d in doomed}


def test_classify_구분():
    assert classify(f"{D1}/{J_KO}_ko.mp4") == "final"
    assert classify(f"{D1}/{J_KO}.mp4") == "final"
    assert classify(f"report/{D1}/{J_KO}_en.mp4") == "final"
    assert classify(f"{D1}/cut_3.mp4") == "clip"
    assert classify(f"{D1}/cut_3.png") == "still"


def test_directive_of_리포트_경로도_읽는다():
    assert directive_of(f"{D1}/x.png") == D1
    assert directive_of(f"report/{D1}/{J_KO}_ko.mp4") == D1


def test_job_id_of():
    assert job_id_of(f"{D1}/{J_KO}_ko.mp4") == J_KO
    assert job_id_of(f"{D1}/{J_KO}.mp4") == J_KO
    assert job_id_of(f"{D1}/cut_3.png") == ""


def test_미업로드_편은_아무것도_지우지_않는다():
    """가장 중요한 보장 — 사람이 아직 확인하지 않은 결과물은 건드리지 않는다."""
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10), Obj(f"{D1}/cut_1.png", 3), Obj(f"{D1}/cut_1.mp4", 2)]
    jobs = [JobState(J_KO, D1, trashed=False, uploaded=False)]
    assert plan(objs, jobs) == []


def test_방금_버린_것은_지우지_않는다():
    """⑥ 의 [버리기]는 복원 가능한 소프트 삭제다. 바로 지우면 [복원]이 껍데기가 된다."""
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10), Obj(f"{D1}/cut_1.png", 3)]
    jobs = [JobState(J_KO, D1, trashed=True, uploaded=False, trashed_days=0.5)]
    assert plan(objs, jobs) == []


def test_보관기간_지난_휴지통은_전부_지운다():
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10), Obj(f"{D1}/cut_1.png", 3)]
    jobs = [JobState(J_KO, D1, trashed=True, uploaded=False, trashed_days=8)]
    assert _paths(plan(objs, jobs)) == {f"{D1}/{J_KO}_ko.mp4", f"{D1}/cut_1.png"}


def test_한_잡이라도_보관기간_안_지났으면_그_편은_남긴다():
    """같은 편의 KO 는 8일 전, EN 은 어제 버렸으면 아직 복원 여지가 있다 → 남긴다."""
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10), Obj(f"{D1}/{J_EN}_en.mp4", 10)]
    jobs = [
        JobState(J_KO, D1, trashed=True, uploaded=False, trashed_days=8),
        JobState(J_EN, D1, trashed=True, uploaded=False, trashed_days=1),
    ]
    assert plan(objs, jobs) == []


def test_업로드된_잡의_최종mp4만_지우고_안올라간_언어는_남긴다():
    """KO 만 유튜브에 올라갔으면 EN mp4 는 남아야 한다 — 잡 단위 판정."""
    objs = [
        Obj(f"{D1}/{J_KO}_ko.mp4", 10),
        Obj(f"{D1}/{J_EN}_en.mp4", 10),
        Obj(f"{D1}/cut_1.png", 3),
    ]
    jobs = [
        JobState(J_KO, D1, trashed=False, uploaded=True),
        JobState(J_EN, D1, trashed=False, uploaded=False),
    ]
    got = _paths(plan(objs, jobs))
    assert got == {f"{D1}/{J_KO}_ko.mp4"}, "EN 영상과 캐시는 남아야 한다"


def test_전부_업로드된_편은_캐시까지_지운다():
    objs = [
        Obj(f"{D1}/{J_KO}_ko.mp4", 10),
        Obj(f"{D1}/{J_EN}_en.mp4", 10),
        Obj(f"{D1}/cut_1.png", 3),
        Obj(f"{D1}/cut_1.mp4", 2),
    ]
    jobs = [
        JobState(J_KO, D1, trashed=False, uploaded=True),
        JobState(J_EN, D1, trashed=False, uploaded=True),
    ]
    assert len(plan(objs, jobs)) == 4


def test_판정근거가_없으면_지우지_않는다():
    """연결된 렌더 잡을 못 찾은 경로(고아)는 남긴다 — 모르면 건드리지 않는다."""
    objs = [Obj(f"{D2}/{J_KO}_ko.mp4", 10)]
    jobs = [JobState(J_KO, D1, trashed=True, uploaded=False)]
    assert plan(objs, jobs) == []


def test_리포트_라인도_같은_규칙으로_판정된다():
    objs = [Obj(f"report/{D1}/{J_KO}_ko.mp4", 10)]
    jobs = [JobState(J_KO, D1, trashed=False, uploaded=True)]
    assert _paths(plan(objs, jobs)) == {f"report/{D1}/{J_KO}_ko.mp4"}


def test_한_편이_여러_잡을_가져도_살아있는_잡만_센다():
    """휴지통 잡이 섞여 있어도, 살아있는 잡이 전부 업로드됐으면 캐시를 지운다."""
    objs = [Obj(f"{D1}/cut_1.png", 3)]
    jobs = [
        JobState(J_KO, D1, trashed=True, uploaded=False),   # 버린 잡 — 세지 않는다
        JobState(J_EN, D1, trashed=False, uploaded=True),
    ]
    assert _paths(plan(objs, jobs)) == {f"{D1}/cut_1.png"}


# ─────────────────────────────────────────────────────────────
# 하위 폴더 재귀 (2026-08-28 실사고)
# ─────────────────────────────────────────────────────────────
class _FakeStorage:
    """Supabase storage.list() 흉내 — 폴더 항목은 metadata 가 없다(실제 동작)."""

    def __init__(self, tree):
        self.tree = tree

    def from_(self, _bucket):
        return self

    def list(self, path, _opts=None):
        return self.tree.get(path, [])


class _FakeSupa:
    def __init__(self, tree):
        self.storage = _FakeStorage(tree)


def test_하위폴더의_컷_캐시까지_찾아낸다():
    """★ 실사고: 컷 캐시는 `{지시서}/assets/cut_N.png` 에 있는데 최상위만 훑어서 못 찾았다.

    폴더 항목은 metadata 가 없어 크기 0 으로 잡히므로, 재귀하지 않으면 **지울 것을 놓치고
    집계도 거짓말을 한다**(실측: 캐시 191개·260MB 를 21개·0MB 로 보고).
    """
    from engine.storage_gc import _walk

    tree = {
        D1: [
            {"name": f"{J_KO}_ko.mp4", "metadata": {"size": 100}},
            {"name": "assets", "metadata": None},          # ← 폴더
        ],
        f"{D1}/assets": [
            {"name": "cut_1.png", "metadata": {"size": 7}},
            {"name": "cut_2.png", "metadata": {"size": 8}},
        ],
    }
    out = []
    _walk(_FakeSupa(tree), D1, out)
    paths = {o.path for o in out}
    assert paths == {f"{D1}/{J_KO}_ko.mp4", f"{D1}/assets/cut_1.png", f"{D1}/assets/cut_2.png"}
    assert sum(o.size for o in out) == 115, "폴더를 파일로 세면 크기가 0 으로 잡힌다"


def test_재귀는_깊이_상한에서_멈춘다():
    """경로가 예상 밖으로 깊어도 무한히 파고들지 않는다."""
    from engine.storage_gc import _MAX_DEPTH, _walk

    # 자기 자신을 계속 하위 폴더로 돌려주는 트리
    tree = {}
    p = D1
    for _ in range(_MAX_DEPTH + 5):
        tree[p] = [{"name": "sub", "metadata": None}]
        p = f"{p}/sub"
    out = []
    _walk(_FakeSupa(tree), D1, out)   # 예외 없이 끝나야 한다
    assert out == []


# ─────────────────────────────────────────────────────────────
# 보관 기한 (2026-08-28 추가)
#
# 왜 생겼나: "미업로드 최종 영상은 절대 안 지운다"에 기한이 없어서, 영원히 올릴 일 없는
# 7월 실험 렌더 532MB 가 6주 뒤에도 남아 무료 한도의 절반을 먹었다. 안전은 유지하되
# 기한을 뒀다. 아래 테스트가 **기한 안에서는 여전히 안 지운다**를 고정한다.
# ─────────────────────────────────────────────────────────────

def _live_job(uploaded: bool = False) -> list[JobState]:
    return [JobState(J_KO, D1, trashed=False, uploaded=uploaded)]


def test_최근_미업로드는_캐시도_영상도_안_지운다():
    """기한 안에서는 종전 그대로 — 이것이 깨지면 사람이 확인할 결과물이 사라진다."""
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10, 5.0), Obj(f"{D1}/assets/cut_1.png", 3, 5.0)]
    assert plan(objs, _live_job()) == []


def test_묵은_컷_캐시는_미업로드여도_지운다():
    """캐시는 재생성할 수 있다. 2주 지나면 캐시로서 값을 잃는다."""
    objs = [Obj(f"{D1}/assets/cut_1.png", 3, 20.0), Obj(f"{D1}/cut_1.mp4", 2, 20.0)]
    assert _paths(plan(objs, _live_job())) == {f"{D1}/assets/cut_1.png", f"{D1}/cut_1.mp4"}


def test_묵은_캐시를_지워도_같은_편의_최근_영상은_남는다():
    """핵심 — 캐시 기한(14일)과 영상 기한(30일)은 별개다. 20일 된 편은 영상이 살아야 한다."""
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10, 20.0), Obj(f"{D1}/assets/cut_1.png", 3, 20.0)]
    assert _paths(plan(objs, _live_job())) == {f"{D1}/assets/cut_1.png"}


def test_한달_지난_미발행_영상은_지운다():
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10, 45.0)]
    doomed = plan(objs, _live_job())
    assert _paths(doomed) == {f"{D1}/{J_KO}_ko.mp4"}
    assert "미발행" in doomed[0].reason


def test_기한은_경계에서_정확하다():
    """29일은 남고 30일은 간다 — 오프바이원이 곧 남의 영상 삭제다."""
    assert plan([Obj(f"{D1}/{J_KO}_ko.mp4", 10, 29.9)], _live_job()) == []
    assert len(plan([Obj(f"{D1}/{J_KO}_ko.mp4", 10, 30.0)], _live_job())) == 1
    assert plan([Obj(f"{D1}/cut_1.png", 3, 13.9)], _live_job()) == []
    assert len(plan([Obj(f"{D1}/cut_1.png", 3, 14.0)], _live_job())) == 1


def test_나이를_모르면_아무것도_안_지운다():
    """`age_days` 기본 0 = '방금 만든 것'. 생성시각을 못 읽어도 삭제로 번지면 안 된다."""
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10), Obj(f"{D1}/assets/cut_1.png", 3)]
    assert plan(objs, _live_job()) == []


def test_기한을_늘리면_아무것도_안_지운다():
    """운영자가 보수적으로 돌리고 싶을 때 config 로 되돌릴 수 있어야 한다."""
    objs = [Obj(f"{D1}/{J_KO}_ko.mp4", 10, 999.0), Obj(f"{D1}/cut_1.png", 3, 999.0)]
    assert plan(objs, _live_job(),
                cache_retention_days=10**6, unpublished_retention_days=10**6) == []
