// 아이콘(Phosphor Regular, MIT — Figma 디딤 파일에서 받은 SVG, public/icons/).
// Figma 설명대로 "색은 icon/* 토큰"이라, SVG는 모양(마스크)으로만 쓰고 색은 글자색(currentColor)을 따른다.
// → 부모나 className에 text-icon-sub · text-text-main 같은 토큰을 주면 그 색이 된다. 선택 상태마다 파일을 따로 두지 않는다.
// 장식용이라 화면 읽기 프로그램에는 숨긴다. 뜻이 필요한 곳은 버튼 · 링크에 글자나 aria-label을 둔다.

// 파일 이름 = public/icons/<이름>.svg
export type IconName =
  | "home"
  | "notebook"
  | "cards"
  | "briefcase"
  | "settings"
  | "plus"
  | "search"
  | "caret-left"
  | "error"
  | "success"
  | "upload"
  | "check"
  | "chat";

// Figma 크기: 메뉴 24, 버튼 M 20, 버튼 S 16, 파일 칸 32
const SIZE_CLASS = { 16: "size-4", 20: "size-5", 24: "size-6", 32: "size-8" } as const;

export function Icon({
  name,
  size = 24,
  className = "",
}: {
  name: IconName;
  size?: keyof typeof SIZE_CLASS;
  className?: string;
}) {
  const url = `url(/icons/${name}.svg)`;
  return (
    <span
      aria-hidden="true"
      className={`inline-block shrink-0 bg-current ${SIZE_CLASS[size]} ${className}`}
      style={{
        maskImage: url,
        WebkitMaskImage: url,
        maskSize: "100% 100%",
        WebkitMaskSize: "100% 100%",
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
      }}
    />
  );
}
