import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "경험 카드 상세",
  description: "경험 카드의 빈칸을 채우고 근거를 확인해요.",
};

export default function Crd01002Page() {
  return <ScreenPlaceholder screenId="CRD_01_002" name="카드 상세 · 편집" feature="F-006" />;
}
