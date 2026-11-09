import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "공고 분석",
  description: "공고의 요구 역량과 내 경험 카드를 맞춰 봐요.",
};

export default function Apl02002Page() {
  return <ScreenPlaceholder screenId="APL_02_002" name="공고 분석" feature="F-007" headingLevel={2} />;
}
