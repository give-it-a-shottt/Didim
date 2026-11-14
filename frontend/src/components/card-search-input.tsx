"use client";

// 카드 제목 검색 칸(Figma Input — 검색 아이콘 + 글 칸, 높이 40). 자소서 탭 왼쪽 카드 목록과 [카드 연결] 창이 같이 쓴다(2차 리뷰 R1).

import { useId } from "react";
import { Icon } from "@/components/icon";

export function CardSearchInput({
  value,
  onChange,
  placeholder = "카드 검색",
  autoFocus = false,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex h-10 items-center gap-1.5 rounded-input border border-line-input bg-bg-default px-3 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary-default">
      <Icon name="search" size={20} className="text-icon-sub" />
      <label htmlFor={id} className="sr-only">
        카드 검색
      </label>
      <input
        id={id}
        type="search"
        autoFocus={autoFocus}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="min-w-0 flex-1 bg-transparent text-body-1 text-text-main outline-none placeholder:text-text-sub-weak"
      />
    </div>
  );
}
