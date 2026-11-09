import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "평가 리포트",
  description: "근거율, 근거 없는 문장 비율, 매칭 적중률을 봐요.",
};

export default function Set02001Page() {
  return <ScreenPlaceholder screenId="SET_02_001" name="평가 리포트" feature="F-010" />;
}
