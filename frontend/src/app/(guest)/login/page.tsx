import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "로그인",
  description: "구글 계정으로 디딤을 시작해요. 올린 노트는 나만 볼 수 있어요.",
};

export default function Aut01001Page() {
  return <ScreenPlaceholder screenId="AUT_01_001" name="로그인" feature="F-001" />;
}
