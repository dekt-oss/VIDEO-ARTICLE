// 통합 작업 화면(WorkspaceClient)이 두 칸(대본 | 지시서)을 다루는 **손잡이** 계약.
//
// 결정 바가 저장·승인을 하나로 소유하므로, 칸은 "무엇이 안 저장됐나 / 저장해라 / 지금 대본이
// 뭐냐 / 요약 숫자" 만 내준다. 네 컴포넌트(논문·리포트 × 대본·지시서)가 같은 모양을 쓴다 —
// 한 공장만 다르게 만들면 결정 바가 갈라진다(이 저장소에서 반복된 드리프트).
import type { MutableRefObject } from "react";

export interface ScriptPaneHandle {
  dirty: boolean;
  /** 대본·씬 편집을 저장한다. 실패하면 false(토스트는 칸이 띄운다). */
  save: () => Promise<boolean>;
  getScript: () => string;
  flaggedScenes: number;
  sceneCount: number;
}

export interface CutsPaneHandle {
  dirty: boolean;
  /** 컷 편집을 저장한다. 지시서가 없으면 true(저장할 것이 없다). */
  save: () => Promise<boolean>;
  directiveId: string | null;
  cutCount: number;
  ungrounded: number;
}

export type ScriptPaneRef = MutableRefObject<ScriptPaneHandle | null>;
export type CutsPaneRef = MutableRefObject<CutsPaneHandle | null>;
