/** 디딤 로고 마크(장식): 모서리가 왼쪽 위 · 오른쪽 아래 8, 나머지 6. primary/accent는 큰 장식 면에만 쓴다. 사이드바 · 랜딩이 같이 쓴다. */
export function LogoMark() {
  return (
    <span aria-hidden="true" className="size-6 rounded-tl-button rounded-tr-tag rounded-br-button rounded-bl-tag bg-primary-accent" />
  );
}
