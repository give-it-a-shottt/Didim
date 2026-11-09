import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "경험 카드",
  description: "노트에서 뽑은 경험을 상황 · 과제 · 행동 · 결과 카드로 모아 봐요.",
};

export default function Crd01001Page() {
  return <ScreenPlaceholder screenId="CRD_01_001" name="경험 카드 목록" feature="F-006" />;
}
