"""주류 파일이 기존 저장소 정리(GC)·업로드 후 삭제에 걸리지 않는지 — 드라이런만(실제 삭제 0). 명세 §12.1.

주류 제작 파일은 비공개 버킷 'drinks' 의 drinks/{job}/… 에 있다(engine/drinks_produce.py). 기존 정리 경로는
공개 버킷 'renders' 에서 render_jobs·report_render_jobs 의 지시서 폴더만 걷는다. 여기서 그 경계를 못박는다.
"""
from engine import drinks_produce, storage_gc


class FakeStorage:
    def __init__(self, files):
        self.files = files      # {bucket: {path: size}}
        self.listed = []        # (bucket, path)
        self.removed = []

    def from_(self, bucket):
        st = self

        class B:
            def list(self, path, opts=None):
                st.listed.append((bucket, path))
                pre = path.rstrip("/") + "/" if path else ""
                names = {}
                for p, size in st.files.get(bucket, {}).items():
                    if p.startswith(pre):
                        rest = p[len(pre):]
                        head = rest.split("/", 1)[0]
                        names[head] = None if "/" in rest else size
                return [{"name": n, "metadata": ({"size": s} if s is not None else None),
                         "created_at": "2020-01-01T00:00:00Z"} for n, s in names.items()]

            def remove(self, paths):
                st.removed.extend(paths)

        return B()


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class FakeSupa:
    def __init__(self, files, tables):
        self.storage = FakeStorage(files)
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.get(name, []))


PAPER_DIR = "11111111-1111-1111-1111-111111111111"
PAPER_JOB = "22222222-2222-2222-2222-222222222222"
DRINK_JOB = "33333333-3333-3333-3333-333333333333"


def _supa():
    files = {
        "renders": {f"{PAPER_DIR}/{PAPER_JOB}_ko.mp4": 100, f"{PAPER_DIR}/assets/cut_1.png": 10},
        "drinks": {f"drinks/{DRINK_JOB}/final_video_01.mp4": 999, f"drinks/{DRINK_JOB}/page_01.png": 5},
    }
    tables = {"render_jobs": [{"id": PAPER_JOB, "directive_id": PAPER_DIR, "deleted_at": None}],
              "upload_requests": [{"render_job_id": PAPER_JOB, "status": "done", "youtube_url": "https://youtu.be/x"}]}
    return FakeSupa(files, tables)


def test_sweep_dry_run_never_lists_or_selects_drinks_files():
    supa = _supa()
    storage_gc.sweep(apply=False, supa=supa)
    assert all(b == storage_gc.BUCKET for b, _ in supa.storage.listed), "정리 경로는 renders 버킷만 걷는다"
    assert not any(p.startswith("drinks") for _, p in supa.storage.listed)
    assert supa.storage.removed == [], "드라이런은 아무것도 지우지 않는다"


def test_plan_ignores_drinks_paths_even_when_old_and_named_like_finals():
    objs = [storage_gc.Obj(f"drinks/{DRINK_JOB}/final_video_01.mp4", 999, age_days=999),
            storage_gc.Obj(f"drinks/{DRINK_JOB}/{DRINK_JOB}_ko.mp4", 999, age_days=999)]
    jobs = [storage_gc.JobState(PAPER_JOB, PAPER_DIR, trashed=False, uploaded=True)]
    assert storage_gc.plan(objs, jobs) == []


def test_purge_after_upload_only_touches_the_uploaded_paper_folder():
    supa = _supa()
    storage_gc.purge_after_upload(PAPER_DIR, supa=supa)
    assert supa.storage.removed and all(p.startswith(PAPER_DIR + "/") for p in supa.storage.removed)
    assert not any("drinks" in p for p in supa.storage.removed)


def test_drinks_worker_uses_its_own_private_bucket():
    assert drinks_produce.BUCKET == "drinks" != storage_gc.BUCKET
