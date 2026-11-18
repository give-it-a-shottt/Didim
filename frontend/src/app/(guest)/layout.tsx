// 게스트 화면(로그인 · 샘플 입구 · 평가 리포트) 공통 틀. 랜딩은 위 메뉴 · 바닥글을 직접 그려서 (landing)에 따로 있다.
export default function GuestLayout({ children }: LayoutProps<"/">) {
  return <main className="flex-1">{children}</main>;
}
