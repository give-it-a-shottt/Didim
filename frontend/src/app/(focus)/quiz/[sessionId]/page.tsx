import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "퀴즈",
  description: "노트에서 만든 객관식 · OX 문제를 풀어요.",
};

export default function Rev02001Page() {
  return <ScreenPlaceholder screenId="REV_02_001" name="퀴즈" feature="F-004" />;
}
