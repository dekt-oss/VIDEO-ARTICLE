"""이미지 프롬프트의 식별자 라벨 요구를 코드가 지운다(2026-10-08 조화 음파 컷 16). 순수 함수."""

from __future__ import annotations

import pytest

from engine import photo_contract as p


@pytest.mark.parametrize("before, after", [
    ("Close-up of a frosted plastic cell culture vial labeled L-929 sitting in a rack.",
     "Close-up of a frosted plastic cell culture vial sitting in a rack."),
    ('A sample box marked "XR-7" on the bench.', "A sample box on the bench."),
    ("A beaker labeled DNA next to a pipette.", "A beaker next to a pipette."),
])
def test_identifier_labels_are_removed_and_the_gate_clears(before, after):
    cuts = [{"cut_no": 16, "visual_prompt": before}]
    assert p.normalize_prompt_labels(cuts) == ["컷16"]
    assert cuts[0]["visual_prompt"] == after
    assert not p._FORBIDDEN_SCREEN.search(after)


@pytest.mark.parametrize("text", ["Rows of test tubes with labels on a rack.",
                                  "A neuron labeled with fluorescent dye glows."])
def test_generic_wording_is_left_for_the_gate(text):
    cuts = [{"cut_no": 1, "visual_prompt": text}]
    assert p.normalize_prompt_labels(cuts) == [] and cuts[0]["visual_prompt"] == text
