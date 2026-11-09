import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "오답노트",
  description: "틀린 문제를 다시 풀어요. 2번 연속 맞히면 빠져요.",
};

export default function Rev03001Page() {
  return <ScreenPlaceholder screenId="REV_03_001" name="오답노트" feature="F-004" />;
}
