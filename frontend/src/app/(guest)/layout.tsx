// 게스트 화면(랜딩 · 로그인) 공통 틀. 검색 엔진에 노출되는 공개 페이지다.
export default function GuestLayout({ children }: LayoutProps<"/">) {
  return <main className="flex-1">{children}</main>;
}
