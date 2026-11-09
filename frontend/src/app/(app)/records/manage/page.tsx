import type { Metadata } from "next";
import { ScreenPlaceholder } from "@/components/screen-placeholder";

export const metadata: Metadata = {
  title: "노트 관리",
  description: "노트를 지우거나 다시 올려요.",
};

export default function Rev01003Page() {
  return <ScreenPlaceholder screenId="REV_01_003" name="노트 관리" feature="F-002" />;
}
