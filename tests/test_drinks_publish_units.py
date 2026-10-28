"""주류 순환 고리 단위 시험 — 인스타 공급자(토큰 경계·오류 갈래)·전략 계산·캡션 검사(네트워크 0).
DB 를 거치는 상태 기계는 web/lib/drinks/publish.db.test.ts, 한 바퀴는 tests/test_drinks_loop_e2e.py 가 본다."""
import httpx
import pytest

from engine import drinks_script_check as sc
from engine import drinks_strategy as ds
from engine.providers import instagram as ig

ACC = {"connection": "instagram_login", "external_account_id": "1784", "credential_ref": "DRINKS_IG_TOKEN_TEST"}
SECRET = "IGQVJ-secret-token-value"


def graph(handler, monkeypatch):
    monkeypatch.setenv("DRINKS_IG_TOKEN_TEST", SECRET)
    return ig.GraphInstagram(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_graph_token_goes_in_header_never_in_url(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "c1"})
        return httpx.Response(200, json={"user_id": "1784", "username": "sooljjerigo"})
    g = graph(handler, monkeypatch)
    assert g.verify(ACC) == {"id": "1784", "username": "sooljjerigo"}
    g.create_container(ACC, kind="image", url="https://x.supabase.co/storage/v1/object/sign/drinks/a.png?token=t")
    for r in seen:
        assert SECRET not in str(r.url), "토큰을 URL 에 넣지 않는다"
        assert r.headers["authorization"] == f"Bearer {SECRET}"
    assert seen[0].url.host == "graph.instagram.com"


def test_graph_error_branches_and_messages_carry_no_secret(monkeypatch):
    def auth(req):
        return httpx.Response(400, json={"error": {"code": 190, "message": f"bad token {SECRET}"}})
    with pytest.raises(ig.AuthError) as e:
        graph(auth, monkeypatch).verify(ACC)
    assert SECRET not in str(e.value), "공급자 오류 문장을 그대로 싣지 않는다(비밀이 섞일 수 있다)"

    def boom(req):
        raise httpx.ReadTimeout("t", request=req)
    with pytest.raises(ig.PublishTimeout):
        graph(boom, monkeypatch).publish(ACC, "c1")

    def rejected(req):
        return httpx.Response(400, json={"error": {"code": 9004, "message": "bad media"}})
    with pytest.raises(ig.PublishError) as e2:
        graph(rejected, monkeypatch).publish(ACC, "c1")
    assert type(e2.value) is ig.PublishError and e2.value.code == "provider_rejected"


def test_graph_refuses_non_https_file_and_missing_secret(monkeypatch):
    g = graph(lambda r: httpx.Response(200, json={}), monkeypatch)
    with pytest.raises(ig.PublishError) as e:
        g.create_container(ACC, kind="image", url="file:///tmp/a.png")
    assert e.value.code == "media_url_invalid"
    monkeypatch.delenv("DRINKS_IG_TOKEN_TEST")
    with pytest.raises(ig.AuthError):
        g.verify(ACC)


def test_real_provider_is_off_until_operator_turns_it_on(monkeypatch, tmp_path):
    monkeypatch.delenv("DRINKS_IG_LIVE", raising=False)
    with pytest.raises(ig.PublishError) as e:
        ig.provider_for(ACC)
    assert e.value.code == "provider_disabled"
    fake = ig.FakeInstagram(str(tmp_path / "s.json"))
    assert ig.provider_for({"connection": "fake"}, fake=fake) is fake
    with pytest.raises(ig.PublishError):
        fake.verify(ACC)   # 가짜 공급자는 실제 계정을 다루지 않는다


def test_fake_carousel_parent_needs_finished_children(tmp_path):
    f = ig.FakeInstagram(str(tmp_path / "s.json"))
    f.add_account("fake_a", "a")
    acc = {"connection": "fake", "external_account_id": "fake_a"}
    with pytest.raises(ig.PublishError) as e:
        f.create_container(acc, kind="carousel", children=["nope"])
    assert e.value.code == "children_not_ready"
    kid = f.create_container(acc, kind="image", url="file:///a.png")
    parent = f.create_container(acc, kind="carousel", children=[kid], caption="c")
    mid = f.publish(acc, parent)
    assert f.publish(acc, parent) == mid, "같은 컨테이너를 두 번 게시해도 게시물은 하나"
    vals, unavailable = f.insights(acc, mid, "carousel")
    assert "views" not in vals and "views" not in unavailable, "카드뉴스는 조회수(영상 지표)를 묻지 않는다"


LIM = {"strategy_bucket": "72h", "strategy_min_group": 3, "strategy_min_total": 6, "strategy_max_step": 0.2, "strategy_max_lift": 0.5}


def post(cat, saved, reach=1000, shares=0, **kw):
    return {"categories": [cat], "post_type": "carousel", "lane": "evergreen", "slot": "evening",
            "values": {"reach": reach, "saved": saved, "shares": shares, **kw}}


def test_strategy_small_sample_changes_nothing_and_says_so():
    inp = {"limits": LIM, "active": {"id": "v0", "weights": {"category": {"sake": 0.1}}},
           "posts": [post("whisky", 90), post("sake", 1)]}
    out = ds.propose(inp)
    assert out["sufficient"] is False and "표본 부족" in out["summary_ko"]
    assert out["weights"]["category"] == {"sake": 0.1}, "표본이 적으면 가중치를 그대로 둔다"


def test_strategy_moves_one_step_only_for_groups_with_enough_samples():
    posts = [post("whisky", 60), post("whisky", 70), post("whisky", 80), post("sake", 10), post("sake", 10), post("sake", 12),
             post("traditional", 60), post("x_missing", 5, reach=0), {"categories": ["sake"], "post_type": "carousel",
                                                                       "lane": "evergreen", "slot": "evening", "values": {"reach": 100}}]
    out = ds.propose({"limits": LIM, "active": {"id": "v0", "weights": {}}, "posts": posts})
    w = out["weights"]["category"]
    assert out["sufficient"] is True and out["sample_total"] == 7
    assert out["basis"]["excluded"] == 2, "도달 0·저장/공유 미제공은 0 이 아니라 표본에서 뺀다"
    assert w["whisky"] == 0.2 and w["sake"] == -0.2, "한 번에 ±0.2 까지만"
    assert "traditional" not in w, "표본 1편 묶음은 바꾸지 않는다"
    assert out["basis"]["groups"]["category"]["traditional"]["enough"] is False


def test_caption_check_blocks_invented_numbers_amounts_and_advice_but_not_hashtags():
    claims = [{"claim_id": "c1", "claim_type": "process", "source_refs": [{"original_quote": "精米歩合50%以下の白米"}]}]
    assert sc.check_caption("쌀을 50% 이하로 깎아요 #2026 #사케", claims).ok
    codes = {f.code for f in sc.check_caption("물을 세 티스푼 넣어 보세요. 70도에서 마셔요", claims).blocks}
    assert codes == {"number_unsupported", "quantity_unsupported", "advice_unsupported"}


def test_graph_media_owner_app_scoped_id_maps_to_account_id(monkeypatch):
    """실측(2026-10-28): Instagram 로그인 토큰은 게시물 owner 를 앱 전용 ID 로 준다 — 계정 ID 로 이어 줘야 게시가 unknown 이 안 된다."""
    def handler(req):
        if req.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "29421002334173283", "user_id": "1784"})
        return httpx.Response(200, json={"id": "m1", "permalink": "https://www.instagram.com/p/x/", "owner": {"id": "29421002334173283"}})
    m = graph(handler, monkeypatch).media(ACC, "m1")
    assert m.owner_id == "1784"

    def other(req):
        if req.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "29421002334173283", "user_id": "1784"})
        return httpx.Response(200, json={"id": "m1", "owner": {"id": "555"}})
    assert graph(other, monkeypatch).media(ACC, "m1").owner_id == "555", "다른 주인은 그대로 둔다(불일치로 잡히게)"


def test_live_publish_workflow_is_manual_only_and_reads_token_from_secret():
    """실제 게시 스위치(DRINKS_IG_LIVE)를 켠 워크플로는 사람이 눌러야만 돈다 — 예약 실행·푸시 실행이 끼면 무인 게시가 된다."""
    import pathlib
    import re as _re

    import yaml

    p = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "drinks-publish.yml"
    raw = p.read_text(encoding="utf-8")
    wf = yaml.safe_load(raw)
    triggers = wf.get("on") or wf.get(True)
    assert set(triggers) == {"workflow_dispatch"}, "실제 게시 워크플로에 cron·push 를 붙이려면 운영자 승인 후 이 시험을 고친다"
    env = wf["jobs"]["run"]["env"]
    assert env.get("DRINKS_IG_LIVE") == "1"
    tokens = {k: v for k, v in env.items() if k.endswith("_IG_TOKEN")}
    assert tokens and all(v == "${{ secrets.%s }}" % k for k, v in tokens.items()), "토큰은 같은 이름의 GitHub 비밀에서만"
    assert not _re.search(r"echo .*TOKEN|set -x", raw), "토큰을 로그에 찍지 않는다"
