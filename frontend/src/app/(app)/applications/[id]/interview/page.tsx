import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "면접 연습",
  description: "매칭된 경험 카드에서 나온 면접 질문을 모아 봐요.",
};

export default function Apl02004Page() {
  return <ScreenPlaceholder screenId="APL_02_004" name="면접 연습" feature="F-009" headingLevel={2} />;
}
