// 뼈대 단계(D-011)의 빈 화면. 각 기능(F-00X)을 만들 때 이 컴포넌트를 실제 화면으로 바꾼다.
type ScreenPlaceholderProps = {
  screenId: string; // didim-design.md IA v2의 화면 ID
  name: string;
  feature: string; // 이 화면을 완성할 기능 번호
  // 한 화면에 h1은 하나만 둔다. 위 레이아웃이 이미 h1을 가진 탭 화면은 2를 넘긴다.
  headingLevel?: 1 | 2;
};

export function ScreenPlaceholder({
  screenId,
  name,
  feature,
  headingLevel = 1,
}: ScreenPlaceholderProps) {
  const Heading = headingLevel === 1 ? "h1" : "h2";
  return (
    <section data-screen-id={screenId} className="p-8" aria-labelledby={`${screenId}-title`}>
      <p className="text-sm">{screenId}</p>
      <Heading id={`${screenId}-title`} className="text-2xl font-semibold">
        {name}
      </Heading>
      <p className="mt-2 text-sm">뼈대 화면이에요. {feature}에서 완성해요.</p>
    </section>
  );
}
