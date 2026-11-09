import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "퀴즈 결과",
  description: "점수 변화와 틀린 문제를 봐요.",
};

export default function Rev02002Page() {
  return <ScreenPlaceholder screenId="REV_02_002" name="퀴즈 결과" feature="F-004" />;
}
