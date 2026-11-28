"""Build a deterministic timeline from per-beat measured voice spans."""
from __future__ import annotations

import math
from typing import Any

from engine import config


def build_timeline(episode: dict[str, Any], voice: list[dict[str, Any]]) -> dict[str, Any]:
    scenes = episode.get("scenes") or []
    if not scenes or sum(len(s.get("beats") or []) for s in scenes) != len(voice):
        raise ValueError("voice count does not match beats")
    result = []
    cursor = 0.0
    index = 0
    for scene_index, scene in enumerate(scenes):
        sid = scene["id"]
        if not scene.get("beats"):
            raise ValueError(f"scene {sid} has no beats")
        local = config.JJERI_FIRST_LEAD if scene_index == 0 else config.JJERI_LEAD
        beats = []
        for _ in scene.get("beats") or []:
            item = voice[index]
            head, end = float(item["head"]), float(item["end"])
            if item.get("sid") != sid or not all(map(math.isfinite, (head, end))) or head < 0 or end <= head:
                raise ValueError(f"invalid voice span at beat {index}")
            if "sec" not in item or not math.isfinite(float(item["sec"])) or end > float(item["sec"]) + config.JJERI_AUDIO_SPAN_TOLERANCE:
                raise ValueError(f"voice span exceeds file at beat {index}")
            speech = round(end - head, 3)
            beats.append({"k": index, "start_local": round(local, 3), "speech": speech, "media_start": head})
            local += round(speech + config.JJERI_GAP, 3)
            index += 1
        template = scene.get("template")
        tail = config.JJERI_TAILS.get(template, config.JJERI_TAIL)
        duration = round(max(config.JJERI_MIN_DURATION.get(template, 0), local + tail), 2)
        if template == "house_rule_search":
            search = scene.get("slots", {}).get("search", {})
            query = search.get("query", "")
            beat = search.get("on_beat", 0)
            if not isinstance(query, str) or not isinstance(beat, int) or not 0 <= beat < len(beats):
                raise ValueError("invalid search timing")
            type_end = beats[beat]["start_local"] + config.JJERI_SEARCH_DELAY + len(query) * config.JJERI_TYPE_INTERVAL
            query_end = type_end + read_seconds(query)
            chip = search.get("after_chip")
            chip_end = type_end + config.JJERI_SEARCH_CHIP_DELAY + read_seconds(chip) if chip else 0
            duration = max(duration, ceil_seconds(max(query_end, chip_end)))
        if template == "vote_comment" and (comment := scene.get("slots", {}).get("comment")):
            duration = max(duration, ceil_seconds(
                config.JJERI_VOTE_INPUT_AT + len(comment) * config.JJERI_TYPE_INTERVAL + read_seconds(comment)
            ))
        result.append({"id": sid, "start": round(cursor, 2), "dur": duration, "beats": beats})
        cursor += duration
    return {"total": round(cursor, 2), "scenes": result}


def read_seconds(text: str) -> float:
    return config.JJERI_READ_BASE + config.JJERI_READ_PER_WORD * len(text.split())


def ceil_seconds(value: float) -> float:
    return math.ceil(round(value, 6) * 100) / 100
