import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "홈",
  description: "오늘 복습할 문제, 마감이 다가오는 지원, 빈칸이 남은 경험 카드를 한눈에 봐요.",
};

export default function Hom01001Page() {
  return <ScreenPlaceholder screenId="HOM_01_001" name="홈 (첫 방문이면 HOM_01_900)" feature="F-012" />;
}
