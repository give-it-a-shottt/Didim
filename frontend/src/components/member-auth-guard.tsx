import type { ReactNode } from "react";
import { requireCurrentUser } from "@/lib/auth";

export async function MemberAuthGuard({ children }: { children: ReactNode }) {
  await requireCurrentUser();
  return <>{children}</>;
}
