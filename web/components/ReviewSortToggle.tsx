// ④ 초안 검수 목록의 정렬 전환 — [낙점일순 | 초안 생성순]. 주소(?sort=)에 남아 새로고침·공유해도 유지된다.
import Link from "next/link";
import type { ReviewSort } from "@/lib/reviewSort";

export default function ReviewSortToggle({ base, sort }: { base: string; sort: ReviewSort }) {
  return (
    <div className="toggle" role="group" aria-label="정렬">
      <Link href={base} data-active={sort === "decided"} scroll={false}>낙점일순</Link>
      <Link href={`${base}?sort=draft`} data-active={sort === "draft"} scroll={false}>초안 생성순</Link>
    </div>
  );
}
