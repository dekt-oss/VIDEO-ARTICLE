"use client";

import { useState } from "react";
import { RenderRequest } from "./ProductionControls";

import { JJERI_AVAILABILITY_WARNING, type JjeriAvailability, type JjeriFormat } from "@/lib/drinks/jjeri";

export function JjeriRenderOptions({ planId, availability, anatomy, anatomyRetry, jjeriRetry, localRetry, allowLocal, blocked, hasOutput }: {
  planId: string;
  availability: JjeriAvailability;
  anatomy?: JjeriAvailability;
  anatomyRetry?: string;
  jjeriRetry?: string;
  localRetry?: string;
  allowLocal: boolean;
  blocked: boolean;
  hasOutput: boolean;
}) {
  const [choice, setChoice] = useState<"local" | JjeriFormat>("local");
  const options = { jjeri_class: availability, jjeri_anatomy: anatomy ?? { state: "hidden" } } as const;
  const ready = (Object.keys(options) as JjeriFormat[]).filter((key) => options[key].state === "ready");
  const warnings = (Object.keys(options) as JjeriFormat[]).map((format) => {
    const state = options[format].state;
    return state !== "hidden" && state !== "ready" ?
      <p key={format} className="banner-warn">{format === "jjeri_anatomy" ?
        JJERI_AVAILABILITY_WARNING[state].replace("술 수업", "술 해부") : JJERI_AVAILABILITY_WARNING[state]}</p> : null;
  });
  if (!ready.length) {
    return <>
      {warnings}
      {allowLocal && !blocked && <div className="actions">
        <RenderRequest planId={planId} label={hasOutput ? "다시 렌더" : "렌더 요청"} />
        {localRetry && <RenderRequest planId={planId} retryOf={localRetry} label="실패한 작업 재시도" />}
      </div>}
    </>;
  }
  const selected = choice === "local" ? undefined : options[choice];
  const episode = selected?.state === "ready" ? selected.episode : null;
  const renderer = episode && choice !== "local" ? choice : undefined;
  const retryOf = renderer === "jjeri_class" ? jjeriRetry : renderer === "jjeri_anatomy" ? anatomyRetry : localRetry;
  const label = renderer === "jjeri_anatomy" ? "째리의 술 해부" : "째리의 술 수업";
  return (
    <div className="dk-sub">
      {warnings}
      <label className="dk-row">
        렌더 형식
        <select value={choice} onChange={(event) => setChoice(event.target.value as "local" | JjeriFormat)}>
          <option value="local">{allowLocal ? "기존 영상" : "현재 제작 흐름"}</option>
          {ready.includes("jjeri_class") && <option value="jjeri_class">째리의 술 수업</option>}
          {ready.includes("jjeri_anatomy") && <option value="jjeri_anatomy">째리의 술 해부</option>}
        </select>
      </label>
      {episode && (
        <>
          <p>세로 모션그래픽 · 무료 Edge 음성 · 화면 가격 표시 없음</p>
          <details>
            <summary>{episode.topic} · 장면 {episode.scenes.length}개 · 지시서 미리보기</summary>
            <ol>
              {episode.scenes.map((scene) => (
                <li key={scene.id}>
                  <b>{episode.chapters.find((chapter) => chapter.from_scene === scene.id)?.title ?? scene.template}</b>
                  {scene.beats.map((beat, i) => <div key={i} style={{ whiteSpace: "pre-line" }}>{beat.text}</div>)}
                </li>
              ))}
            </ol>
          </details>
          <p className="muted">렌더 뒤 파일과 출처를 검수합니다. 게시에는 소유자 최종 판정이 필요합니다.</p>
        </>
      )}
      {!blocked && (renderer || allowLocal) && (
        <div className="actions">
          <RenderRequest key={choice} planId={planId} renderer={renderer}
            label={renderer ? label + " 렌더 (0원)" : hasOutput ? "다시 렌더" : "렌더 요청"} />
          {retryOf && <RenderRequest key={choice + "-retry"} planId={planId}
            renderer={renderer} retryOf={retryOf} label="실패한 작업 재시도" />}
        </div>
      )}
    </div>
  );
}
