from copy import deepcopy
import json
from pathlib import Path

import pytest

from engine.drinks_collect import DbError
from engine.jjeri_anatomy.build import LAYOUT, SAMPLE_WORLD_ORIGIN, load_sample, build, read_manifest, schedule, validate_structure
from engine.jjeri_anatomy.evidence import EvidenceError, _fields, audit, compact, generate
from test_jjeri_generation_e2e import factory, prepared_topic, version


@pytest.mark.parametrize("bad",["world","part","token","event","beat","price","line","quiz","source","wrong_quote"])
def test_anatomy_audit_rejects_unsafe_episode(bad):
    episode,evidence=mock_episode()
    jar=episode["worlds"][0]
    if bad=="world":
        jar["world"]="unknown"
    elif bad=="part":
        jar["parts"][0]="external"
    elif bad=="token":
        jar["tokens"]["chain"][0]="unknown:모의"
    elif bad=="event":
        jar["events"][0]["do"]="eval"
    elif bad=="beat":
        jar["events"][0]["beat"]=55
    elif bad=="price":
        jar["events"][11]["text"]="39,900원"
    elif bad=="line":
        jar["beats"][0]["text"]="긴 문장입니다 긴 문장입니다 긴 문장입니다"
    elif bad=="quiz":
        episode["worlds"][-1]["quiz"]["answer"]=3
    elif bad=="source":
        jar["source_chip"]="모의"
    else:
        for claim in evidence["claims"]:
            claim["source_refs"][0]["original_quote"]="무관한 근거 문장."
    expected = {
        "world":"layout_sequence_invalid", "part":"part_invalid", "token":"token_invalid",
        "event":"event_sequence_invalid", "beat":"beat_reference_invalid", "price":"price",
        "line":"subtitle_length", "quiz":"quiz_answer_not_previously_displayed",
        "source":"source_chip_injected", "wrong_quote":"anatomy_quote_text_mismatch",
    }
    with pytest.raises(ValueError, match=expected[bad]):
        audit(episode,evidence)


def mock_episode(*, saved_voice=False):
    episode=load_sample()
    lines=[
        ["막걸리 해부.","전분 든 곡물.","항아리 속 발효.","맑은 윗술.","청주를 떠냅니다."],
        ["통째로 거르기."],
        ["잔에 담긴 것.","단맛과 신맛.","도수는 7도예요."],
        ["퀴즈! 윗술만 떠내면?"],
    ]
    if saved_voice:
        lines = [[beat["text"].replace("누룩, 그리고", "누룩,그리고").replace("탄산 음료라면", "탄산음료라면")
                  for beat in w["beats"]] for w in episode["worlds"]]
        for world in episode["worlds"]:
            for index in SAMPLE_WORLD_ORIGIN.get(LAYOUT[world["world"]], ()):
                world["events"][index]["origin"] = "world"
    for chapter in episode["chapters"]:
        if chapter["title"] == "한 잔에 담긴 것":
            chapter["title"] = "잔에 담긴 것"
    fields={}
    claim_map={}
    for i,(world,parts) in enumerate(zip(episode["worlds"],lines)):
        cid=f"c{i+1}"
        claim_map[world["id"]]=cid
        fields[cid]=parts.copy()
        for beat,text in zip(world["beats"],parts):
            beat.update(text=text,claim_ids=[cid] if i<3 else [])
    episode["worlds"][-1]["quiz"]["claim_ids"]=["c1"]
    refs={}
    for path,text,wid in _fields(episode):
        cid=claim_map[wid] if wid else "c1"
        refs[path]=[cid]
        fields[cid].append(text)
    episode["text_claim_ids"]=refs
    sources=[{"snapshot_id":"snap","url":"https://example.org/synthetic","publisher":"모의 근거"}]
    claims=[{"claim_id":cid,"claim_type":"process","support_review":"supported",
             "source_refs":[{"snapshot_id":"snap","quote_check":"matched","original_quote":" ".join(texts)}]}
            for cid,texts in fields.items()]
    return episode,{"approved":True,"selected_claim_ids":list(fields),"claims":claims,"sources":sources}


def test_anatomy_fake_generation_correction_and_revocation():
    episode,evidence=mock_episode()
    seen=[]
    def response(_,payload):
        seen.append(payload)
        return "invalid JSON" if len(seen)==1 else json.dumps(episode)
    result=generate(evidence,episode["topic"],response,required_claim_ids=("c1","c2","c3"))
    assert result==episode
    assert seen[1]["correction"]["code"]=="anatomy_invalid"
    with pytest.raises(EvidenceError,match="evidence_not_approved"):
        generate({**evidence,"approved":False},episode["topic"],response)
    assert len(seen)==2


def test_anatomy_canonical_time_and_data_mutations_are_separate(tmp_path):
    sample=load_sample()
    b,c,bt,d,ev,ch,total=schedule(sample,read_manifest(),sample=True)
    assert total==46.62
    assert b["quiz"]+ev["quiz"]["quiz"][0]["time"]==pytest.approx(39.32)
    original=tmp_path/"canonical"
    build(sample,original,mode="golden")
    clone=deepcopy(sample)
    jar=clone["worlds"][0]
    jar.update(world="barrel_cutaway",vessel="oak_barrel")
    jar["tokens"]["chain"][0]="grain:변형어"
    jar["events"][6]["focus"]=[520,880]
    clone["chapters"][0]["title"]="변형 제목"
    variant=tmp_path/"structural"
    build(clone,variant,mode="golden")
    html=(variant/"compositions/jar.html").read_text(encoding="utf8")
    assert "변형어" in html and 'x: -604.0' in html and "#9A9A91" in html
    assert "변형 제목" in (variant/"compositions/frame.html").read_text(encoding="utf8")
    clone["worlds"][0]["beats"][0]["text"]="실제 이야기 교체"
    with pytest.raises(ValueError,match="sample_voice_mismatch"):
        build(clone,tmp_path/"rejected",mode="golden")


def test_anatomy_render_rpc_keeps_permissions_and_legacy_worker_out(factory):
    b=factory
    form,_,_,_=prepared_topic(b)
    episode,_=mock_episode()
    rpc=b.rpc
    saved=rpc("drinks_save_plan",{"topic_id":form["topic_id"],"topic_review_id":form["review_id"],
        "format":"video","plan_json":{"jjeri_anatomy":episode,"scenes":[{"narration":"내용","claim_ids":["c1"]}]}})
    pid=saved["revision_id"]
    request={"plan_revision_id":pid}
    with pytest.raises(DbError,match="승인되고"):
        rpc("drinks_request_jjeri_anatomy_render",request)
    for action in ("submit","approve"):
        rpc("drinks_plan_action",{"revision_id":pid,"action":action,
                                  "expected_version":version(b,"drink_plan_revisions",pid)})
    with pytest.raises(DbError,match="무료"):
        rpc("drinks_request_jjeri_anatomy_render",{**request,"paid":True})
    grants=b.sql("select has_function_privilege('anon','drinks_request_jjeri_anatomy_render(jsonb)','EXECUTE') ok")
    assert not grants[0]["ok"]
    assert rpc("drinks_jjeri_render_status", {"include_anatomy":True})["anatomy_ready"]
    first=rpc("drinks_request_jjeri_anatomy_render",request)
    assert first["renderer"]=="jjeri_anatomy"
    assert rpc("drinks_start_render",{"worker_id":"old"})["job"] is None
    assert rpc("drinks_request_jjeri_anatomy_render",request)["job_id"]==first["job_id"]
    rpc("drinks_cancel_render",{"job_id":first["job_id"]})
    with pytest.raises(DbError):
        rpc("drinks_request_render",{**request,"retry_of":first["job_id"]})
    second=rpc("drinks_request_jjeri_anatomy_render",{**request,"retry_of":first["job_id"]})
    assert second["attempt_no"]==2
    job=rpc("drinks_start_render",{"worker_id":"new","allow_jjeri_anatomy":True})["job"]
    assert job["plan"]["jjeri_anatomy"]==episode
    rpc("drinks_review_action",{"review_id":form["review_id"],"action":"revoke",
                                "expected_version":version(b,"drink_topic_reviews",form["review_id"]),"reason":"test"})
    assert rpc("drinks_heartbeat_render",{"job_id":job["job_id"],"lease_token":job["lease_token"]})["renderable"] is False


@pytest.mark.parametrize("extra", [0,3])
def test_anatomy_accepts_two_and_five_worlds_with_independent_ids(extra):
    from engine.jjeri_anatomy.layout import render_world

    episode=load_sample()
    first,middle,_,last=episode["worlds"]
    middles=[]
    for i in range(extra):
        repeated=deepcopy(middle)
        repeated["id"]=f"middle-{i}"
        middles.append(repeated)
    episode["worlds"]=[first,*middles,last]
    episode["chapters"]=[{"title":w["id"],"world":w["id"],"beat":0} for w in episode["worlds"]]
    voice=read_manifest()
    reordered=[*voice[:5],*([voice[5]]*extra),voice[-1]]
    validate_structure(episode)
    starts,captions,beats,lengths,cues,_,_=schedule(episode,reordered,sample=True)
    assert list(starts)==[w["id"] for w in episode["worlds"]]
    if extra:
        w=middles[-1]
        wid=w["id"]
        material=render_world("sieve",w,cues[wid],beats[wid],lengths[wid],captions[wid],[],
                              (424,1036),False,.35,2,first)
        assert 'data-composition-id="middle-2"' in material and "#middle-2-cam" in material
        assert '#sv-cam' not in material


def test_jjeri_sfx_click_alias_matches_played_peak_and_parameters():
    from engine import config
    from hashlib import sha256
    assets = Path("assets/templates")
    clips = [assets / "jjeri-anatomy/assets/sfx/click.mp3",
             assets / "jjeri-class/assets/sfx/click-soft.mp3"]
    assert len({sha256(p.read_bytes()).digest() for p in clips}) == 1
    peak, duration, gain = config.JJERI_SFX["click"]
    assert config.JJERI_SFX["click-soft"] == (peak, duration, gain)
    assert peak == pytest.approx(.0735)


def test_owned_sfx_config_matches_source_over_the_played_window():
    import shutil
    from engine import config
    from scripts.jjeri_formats_signal import energy_peak, samples
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for the local PCM check")
    for asset in Path("assets/templates").glob("jjeri-*/assets/sfx/*.mp3"):
        peak, duration, _ = config.JJERI_SFX[asset.stem]
        clip = samples(asset, config.JJERI_SFX_FILTER)
        assert energy_peak(clip, duration) == pytest.approx(peak, abs=.001), asset


def test_hud_steps_snap_independently_to_decoded_bed_frames():
    from engine.jjeri_music import hud_frames
    fps = 30
    peaks = (8.2316, 8.7605, 9.2623, 9.7861)
    onsets = (8.2051, 8.7180, 9.2308, 9.7436)
    selected = hud_frames(8.229, peaks, onsets)
    assert selected == pytest.approx((247/fps, 262/fps, 277/fps, 293/fps))
    assert all(max(abs(p-f), abs(o-f)) <= 1/fps for p,o,f in zip(peaks,onsets,selected))


def test_anatomy_request_reaches_same_mock_provider_and_requires_approval(factory, tmp_path, monkeypatch):
    from test_jjeri_generation_e2e import worker
    import os

    real = os.environ.get("JJERI_LOCAL_REAL_ANATOMY") == "1"
    episode, evidence = mock_episode(saved_voice=real)
    form, _, _, _ = prepared_topic(factory, anatomy=(episode, evidence))
    rpc = factory.rpc
    request = rpc("drinks_request_jjeri_episode", form)
    assert rpc("drinks_request_jjeri_episode", form)["request_id"] == request["request_id"]
    assert rpc("drinks_start_develop", {"worker_id":"previous","allow_jjeri":True})["job"] is None
    def provider(_, body):
        assert json.loads(body)["format"] == "jjeri_anatomy"
        return json.dumps(episode)
    outcome = worker(factory, provider, anatomy=True)
    assert outcome["status"] == "succeeded", json.dumps(outcome, ensure_ascii=False)
    status = rpc("drinks_jjeri_generation_status", {"topic_id":form["topic_id"]})
    assert status["request"]["format"] == "jjeri_anatomy"
    assert status["request"]["result"]["plan"]["jjeri_anatomy"] == episode
    assert status["revision_id"] is None
    with pytest.raises(DbError):
        rpc("drinks_approve_jjeri_episode", {"request_id":request["request_id"]})
    approved = rpc("drinks_approve_jjeri_episode", {"request_id":request["request_id"],"review_confirmed":True})
    production = rpc("drinks_request_jjeri_anatomy_render", {"plan_revision_id":approved["revision_id"]})
    assert production["renderer"] == "jjeri_anatomy"

    if not real:
        return
    from hashlib import sha256
    import shutil
    from engine import drinks_produce, drinks_publish
    from engine.jjeri_anatomy import build as anatomy_build

    # Only the Edge synthesizer is replaced. Production audit, assembly, HF
    # check/render, stream checks, storage and QA registration all run normally.
    manifest = {compact(row["text"]): row for row in read_manifest()}
    spoken = []
    def saved_speech(text, target):
        row = manifest[compact(text)]
        clip = anatomy_build.REFERENCE / "assets/vo" / f"b{row['k']:02}.mp3"
        assert sha256(clip.read_bytes()).hexdigest() == row["sha256"]
        shutil.copyfile(clip, target)
        spoken.append(text)
        return row["sec"], row["head"], row["end"]

    monkeypatch.setattr(anatomy_build, "_synthesize", saved_speech)
    storage = drinks_produce.Storage(mode="local", root=str(tmp_path / "storage"))
    results = drinks_produce.run_queue(rpc, storage, worker_id="real-anatomy", max_jobs=1)
    assert results[0]["status"] == "succeeded", results
    assert spoken == [beat["text"] for w in episode["worlds"] for beat in w["beats"]]
    assert len(list((tmp_path / "storage").rglob("*.mp4"))) == 1
    assert any((tmp_path / "storage").rglob("*.jpg"))
    job_id = production["job_id"]
    cost = factory.sql("select sum(cost_usd)::float8 as total, count(*)::int as count from drink_cost_entries where job_id = $1",
                       [job_id])[0]
    assert cost == {"total":0,"count":2}
    qa = factory.sql("select id, version, qa_summary from drink_output_reviews where manifest_id = $1",
                     [results[0]["manifest_id"]])[0]
    assert qa["qa_summary"]["renderer"] == "jjeri_anatomy"
    assert qa["qa_summary"]["evidence"]["source_labels_by_world"]["jar"]
    assert drinks_publish.format_gate({"content_format":"jjeri_anatomy"}) == (
        "jjeri_owner_review_required", "째리의 술 해부 영상은 소유자 최종 판정 대기 중입니다")
    # Local test account and disposable approval only. No publishing worker.
    from datetime import datetime, timezone
    checklist = {key:True for key in ("scene_types_labeled","no_real_product_implied",
                                       "claims_match_evidence","audio_subtitles_ok","vertical_ok")}
    rpc("drinks_output_review_action", {"review_id":qa["id"],"expected_version":qa["version"],
                                         "action":"approve","checklist":checklist})
    aid = rpc("drinks_register_account", {"external_account_id":"fake_anatomy","display_name":"로컬",
        "account_type":"test","connection":"fake","capabilities":{"post_types":["reel"]}})["account_id"]
    publication = rpc("drinks_create_publication", {"output_review_id":qa["id"],"account_id":aid,
        "caption":"로컬 시험", "publish_at":datetime.now(timezone.utc).isoformat()})
    assert publication["content_format"] == "jjeri_anatomy"
    with pytest.raises(RuntimeError, match="jjeri_owner_review_required"):
        factory.sql("update drink_publication_requests set status = 'scheduled' where id = $1", [publication["request_id"]])
    print(json.dumps({"status":"succeeded","voice_clips":len(spoken),"storage":str(tmp_path/"storage"),
                      "qa":qa["qa_summary"]["audio"],"cost":cost,"publication_gate":"blocked"},ensure_ascii=False))
