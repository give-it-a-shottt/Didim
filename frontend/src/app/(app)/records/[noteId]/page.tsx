import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "노트 상세",
  description: "노트의 개념과 문제, 원문을 봐요.",
};

export default function Rev01002Page() {
  return <ScreenPlaceholder screenId="REV_01_002" name="노트 상세" feature="F-002" />;
}
