import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "설정",
  description: "계정, AI 사용량, 데이터 삭제를 관리해요.",
};

export default function Set01001Page() {
  return <ScreenPlaceholder screenId="SET_01_001" name="설정" feature="F-001" />;
}
