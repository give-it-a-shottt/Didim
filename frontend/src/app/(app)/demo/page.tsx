import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "샘플 체험",
  description: "가상 지원자 데이터로 디딤을 미리 써 봐요.",
};

export default function Dem01001Page() {
  return <ScreenPlaceholder screenId="DEM_01_001" name="샘플 체험 공간" feature="F-010" />;
}
