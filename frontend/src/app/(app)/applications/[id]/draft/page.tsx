import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "자소서",
  description: "문장마다 근거가 달린 자소서 초안을 고쳐 써요.",
};

export default function Apl02003Page() {
  return <ScreenPlaceholder screenId="APL_02_003" name="자소서" feature="F-008" headingLevel={2} />;
}
