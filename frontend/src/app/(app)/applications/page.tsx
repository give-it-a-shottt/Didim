import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "지원",
  description: "지원한 공고를 마감일 순으로 봐요.",
};

export default function Apl01001Page() {
  return <ScreenPlaceholder screenId="APL_01_001" name="지원 목록" feature="F-007" />;
}
