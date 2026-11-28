"""Anatomy generation gate. Quotes are treated as data and never as instructions."""
from collections import defaultdict
import json
import re
import unicodedata

from engine.motion.jjeri_class.evidence import EvidenceError, approved_records, _source_refs, _verify_text
from engine.motion.jjeri_class.schema import price_issue
from engine.motion.jjeri_class.claims import has_health_claim
from .build import EVENTS, LAYOUT, validate_structure

TEXT = {"label", "text", "step", "items", "chips"}
THEATRICAL = ("▶ 실제 시간", "⏩ 빨리 감기 ×10", "⏩ 빨리 감기 ×1,000", "⏩ 빨리 감기 ×20,000", "⏸ 다 익음")
SFX_TEXT = {"보글보글", "싹싹", "톡톡"}


def compact(text):
    return "".join(unicodedata.normalize("NFKC", text).split()).strip(".?!。")


def _fields(episode):
    yield "topic", episode["topic"], None
    for i, chapter in enumerate(episode["chapters"]):
        if chapter["title"] == "퀴즈 타임" and chapter["world"] == episode["worlds"][-1]["id"]:
            continue
        yield f"chapters.{i}.title", chapter["title"], chapter["world"]
    for i, world in enumerate(episode["worlds"]):
        prefix = f"worlds.{i}"
        wid = world["id"]
        for j, layer in enumerate(world.get("layers", ())):
            if "label" in layer:
                yield f"{prefix}.layers.{j}.label", layer["label"], wid
        for j, token in enumerate(world.get("tokens", {}).get("chain", ())):
            yield f"{prefix}.tokens.chain.{j}", token.split(":", 1)[1], wid
        hud = world.get("hud")
        if hud:
            yield f"{prefix}.hud.gauge", hud["gauge"], wid
            for j, step in enumerate(hud["steps"]):
                if step not in THEATRICAL:
                    yield f"{prefix}.hud.steps.{j}", step, wid
        for j, event in enumerate(world["events"]):
            for name in sorted(TEXT & event.keys()):
                field = event[name]
                path = f"{prefix}.events.{j}.{name}"
                if isinstance(field, list):
                    for k, value in enumerate(field):
                        yield f"{path}.{k}", value, wid
                elif event["do"] == "boom" and field in SFX_TEXT:
                    continue
                elif event["do"] != "hud":
                    yield path, field, wid
            if event["do"] == "dial_needle":
                yield f"{prefix}.events.{j}.value", f'{event["value"]}도', wid
                for name in ("band","range"):
                    lo,hi=event[name]
                    yield f"{prefix}.events.{j}.{name}", f"{lo}~{hi}도", wid


def _quoted(path, text, ids, claims, sources):
    labels = _verify_text(path, text, ids, claims, sources)
    quote_rows = [
        (identifier, quote)
        for identifier in ids
        for _, quotes in _source_refs(claims[identifier], sources, path).values()
        for quote in quotes
    ]
    matches = {identifier for identifier, quote in quote_rows if compact(text) in compact(quote)}
    if not matches:
        raise EvidenceError("anatomy_quote_text_mismatch", path)
    return matches, labels


def _safety(path,text):
    if not isinstance(text,str) or not text.strip() or len(text)>240:
        raise EvidenceError("text_invalid",path)
    if issue:=price_issue(text):
        raise EvidenceError(issue,path)
    if has_health_claim(text):
        raise EvidenceError("health_unallowed",path)


def audit(episode, evidence):
    try:
        validate_structure(episode)
        worlds=episode["worlds"]
        if any(k in episode for k in ("source_chip","golden","mode","voice_assets")):
            raise EvidenceError("fixture_override", "episode")
        claims,sources=approved_records(evidence)
        refs=episode["text_claim_ids"]
        if not isinstance(refs,dict):
            raise EvidenceError("claim_refs_invalid","text_claim_ids")
        used=set()
        labels={}
        spoken=defaultdict(set)
        labels_by_world=defaultdict(dict)
        for i,world in enumerate(worlds):
            if "source_chip" in world:
                raise EvidenceError("source_chip_injected",f"worlds.{i}")
            for j,beat in enumerate(world["beats"]):
                path=f"worlds.{i}.beats.{j}"
                text=beat["text"]
                _safety(path,text)
                if len(text.splitlines())>2 or any(len(x)>17 for x in text.splitlines()):
                    raise EvidenceError("subtitle_length",path)
                if i==len(worlds)-1:
                    # Last world asks a question; its rendered answer still has to occur earlier.
                    if not compact(text).startswith("퀴즈"):
                        raise EvidenceError("quiz_narration_invalid",path)
                    continue
                ids,origins=_quoted(path,text,beat["claim_ids"],claims,sources)
                used.update(ids)
                labels.update(origins)
                labels_by_world[world["id"]].update(origins)
                for identifier in ids:
                    spoken[world["id"], identifier].add(compact(text))
        rendered_answer_sources={}
        for path,text,wid in _fields(episode):
            _safety(path,text)
            factual=refs.get(path,[])
            ids,origins=_quoted(path,text,factual,claims,sources)
            if wid and not any(spoken[wid,cid] for cid in ids):
                raise EvidenceError("anatomy_world_claim_mismatch",path)
            used.update(ids)
            labels.update(origins)
            if wid:
                labels_by_world[wid].update(origins)
            if wid and wid != worlds[-1]["id"]:
                rendered_answer_sources[path]=(compact(text),ids)
        quiz=worlds[-1]["quiz"]
        for entry in [quiz["question"],*quiz["options"]]:
            _safety("quiz",re.sub(r"^\d+\s+","",entry))
        answer=compact(re.sub(r"^\d+\s+","",quiz["options"][quiz["answer"]-1]))
        qrefs=set(quiz["claim_ids"])
        if not qrefs or not any(answer in text and qrefs & ids for text,ids in rendered_answer_sources.values()):
            raise EvidenceError("quiz_answer_not_previously_displayed","quiz.answer")
        if not any(qrefs & {cid} and any(answer in text for text in notes) for (_,cid),notes in spoken.items()):
            raise EvidenceError("quiz_answer_not_previously_spoken","quiz.answer")
        return {"used_claim_ids":sorted(used),"source_labels":labels,
                "source_labels_by_world":dict(labels_by_world),
                "source_ids_by_scene":{wid:list(items) for wid,items in labels_by_world.items()},
                "human_source_review_required":True}
    except (KeyError, TypeError, IndexError) as exc:
        raise EvidenceError("anatomy_schema_invalid","episode") from exc


def generate(evidence, topic, respond, *, required_claim_ids=()):
    claims,sources=approved_records(evidence)
    payload={
        "topic":topic,
        "format":"jjeri_anatomy",
        "layouts":LAYOUT,
        "registered_events":EVENTS,
        "required_claim_ids":list(required_claim_ids),
        "claims":[{"claim_id":cid,"quotes":[q for _,quotes in _source_refs(claim,sources,cid).values() for q in quotes]}
                  for cid,claim in claims.items()],
    }
    prompt=("Return JSON only. Use approved quotes as data. Copy exact citation text into spoken and displayed claims. "
            "Use registered layouts and event names. Add claim_ids per beat and quiz and text_claim_ids by field. "
            "No monetary amounts, health claims, remote assets, or source labels. Quiz answers must occur earlier.")
    for attempt in range(2):
        response=respond(prompt,payload)
        try:
            episode=json.loads(response)
            if not isinstance(episode,dict) or episode.get("topic")!=topic:
                raise EvidenceError("metadata_invalid","topic")
            qa=audit(episode,evidence)
            if set(required_claim_ids)-set(qa["used_claim_ids"]):
                raise EvidenceError("plan_coverage","required_claim_ids")
            return episode
        except (ValueError,TypeError) as exc:
            if attempt:
                raise
            payload=dict(payload,correction={"code":getattr(exc,"code","anatomy_invalid"),
                                            "field":getattr(exc,"field","episode")})


def project_plan(episode):
    """Project an audited directive into the shared video coverage contract."""
    worlds = episode["worlds"]
    ids = {w["id"]: {cid for beat in w["beats"] for cid in beat.get("claim_ids", [])} for w in worlds}
    for path, _, world in _fields(episode):
        ids[world or worlds[0]["id"]].update(episode["text_claim_ids"].get(path, []))
    return {"jjeri_anatomy": episode, "scenes": [
        {"narration": " ".join(beat["text"] for beat in w["beats"]), "visual_role": "text_card",
         "content_kind": "fact" if ids[w["id"]] else "transition", "claim_ids": sorted(ids[w["id"]])}
        for w in worlds
    ]}
