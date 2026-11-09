import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "기록 · 복습",
  description: "올린 노트와 오늘 복습할 문제를 봐요.",
};

export default function Rev01001Page() {
  return <ScreenPlaceholder screenId="REV_01_001" name="기록 · 복습 홈" feature="F-002" />;
}
