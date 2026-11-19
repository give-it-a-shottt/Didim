// 랜딩(LND_01_001, F-011) — 화면에 보이는 샘플 글과 첫 화면 평가 수치 규칙. 배치 · 문구는 Figma 디딤 랜딩(29:1373).
//
// Figma의 예시 문장(Accio · Redis)은 디자인용 가상 예시라서 그대로 쓰지 않는다. 화면의 초안 · 인용은 모두
// 샘플 계정의 실제 AI 결과를 글자 그대로 옮겼다(설계 원칙 1, 사용자 확인 2026-11-18):
// [가상] 바구니마켓 · Java 백엔드 개발자 (신입)의 2번 문항 초안(backend/scripts/seed_sample.py로 넣은 평가 회차 결과).
// 샘플을 다시 시드해 글이 바뀌면 여기를 같이 고친다.
import type { CardSlot } from "@/lib/card-slots";
import { dataSizeText, type ReportRun } from "@/lib/report";

type Evidence = { card: string; slot: CardSlot; quote: string };

/** ok = 근거 있음, check = 근거는 있지만 카드에 없는 낱말이 섞임('확인 필요', D-028), none = 근거 없음. */
export type DraftSentence =
  | ({ kind: "ok"; text: string } & Evidence)
  | ({ kind: "check"; text: string; unknownWords: string } & Evidence)
  | { kind: "none"; text: string };

export const DRAFT_POSTING = "[가상] 바구니마켓 · Java 백엔드 개발자 (신입)";
export const DRAFT_QUESTION_LABEL = "2번 문항";
export const DRAFT_QUESTION = "MSA 환경에서 서비스 간 장애 전파를 막은 경험을 써 주세요.";
export const DRAFT_PROGRESS = "348 / 500자 · AI 초안에서 내가 고친 부분 0%"; // 샘플 자소서 화면의 글자 수 줄 그대로

const MSA_SENTENCE: DraftSentence = {
  kind: "check",
  text: "MSA 환경에서 서비스 간 장애 전파를 막기 위해 비동기 메시지 큐를 도입해 서비스 결합도를 낮췄습니다.",
  unknownWords: "msa",
  card: "메일 발송을 메시지 큐로 분리",
  slot: "action",
  quote:
    "신청 저장까지만 요청 안에서 처리하고, 메일 발송은 RabbitMQ 큐에 메시지로 넣은 뒤 따로 도는 소비자가 보내게 바꿨다.",
};

const QUEUE_RESULT_SENTENCE: DraftSentence = {
  kind: "ok",
  text: "동아리 행사 신청 서비스에서 신청 버튼을 누르면 확인 메일을 보낸 뒤에야 응답이 돌아와 평균 3.2초가 걸렸으나, 큐 분리 후 응답 시간이 0.3초로 단축되었습니다.",
  card: "메일 발송을 메시지 큐로 분리",
  slot: "result",
  quote: "신청 응답 시간이 평균 3.2초에서 0.3초로 줄었다.",
};

export const COUPON_ACTION_SENTENCE = {
  kind: "ok",
  text: "고정된 쿠폰 수량을 동시 요청 상황에서 안전하게 차감하기 위해 Redisson 분산 락과 유니크 제약을 적용했습니다.",
  card: "쿠폰이 중복 발급되던 문제",
  slot: "action",
  quote:
    'Spring 서비스에서 쿠폰 수량을 줄이는 부분을 Redisson 분산 락으로 감싸고, 락을 얻지 못한 요청은 0.5초까지만 기다린 뒤 "잠시 후 다시 시도해 주세요" 응답을 주게 했다.',
} as const satisfies DraftSentence;

const COUPON_RESULT_SENTENCE = {
  kind: "ok",
  text: "부하 테스트에서 500개 동시 요청 시 117장이 발급되던 문제가 락 적용 후 정확히 100장만 발급되고 중복 발급 0건으로 해결되었습니다.",
  card: "쿠폰이 중복 발급되던 문제",
  slot: "result",
  quote: "같은 부하 테스트를 다시 돌리자 정확히 100장만 발급됐고, 한 사용자에게 두 번 발급된 경우는 0건이었다.",
} as const satisfies DraftSentence;

const CLOSING_SENTENCE = {
  kind: "none",
  text: "이러한 경험을 바탕으로 장애가 연쇄적으로 퍼지는 것을 차단하는 설계를 실무에 적용하겠습니다.",
} as const satisfies DraftSentence;

/** 첫 화면 자소서 카드 — 초안 5문장 전부(문항의 'MSA'를 AI가 가져다 써 '확인 필요', 마지막 다짐 문장은 '근거 없음'). */
export const DRAFT_SENTENCES: readonly DraftSentence[] = [
  MSA_SENTENCE,
  QUEUE_RESULT_SENTENCE,
  COUPON_ACTION_SENTENCE,
  COUPON_RESULT_SENTENCE,
  CLOSING_SENTENCE,
];

/** 스토리 세 장면 — 같은 초안의 마지막 두 문장(근거 있는 문장 1 + 근거 없는 문장 1). */
export const STORY_SCENE = { kept: COUPON_RESULT_SENTENCE, dropped: CLOSING_SENTENCE } as const;

/** '기록 하나가 세 번 쓰여요'의 복습 칸 — 샘플 퀴즈의 해설 근거 인용(노트 '프로세스와 스레드'). */
export const REVIEW_QUOTE = { quote: "뮤텍스 같은 잠금으로 한 번에 한 스레드만 고치게 해서 막는다.", note: "프로세스와 스레드" };

// 첫 화면 평가 수치 — '잡아내기' 3개(사용자 확인 2026-11-18). 좋은 수치만 고르지 않는다.
// 키는 서버의 대표 수치 정의(backend/app/services/eval_report.py STEPS)와 같다.
const HERO_METRICS = [
  { evalKey: "drafts_ai", metricKey: "warn_rate" }, // 자소서 · AI 초안 — 지어낸 문장 경고율
  { evalKey: "interview_planted", metricKey: "catch_rate" }, // 면접 · 심은 질문 — 잡은 비율
  { evalKey: "postings", metricKey: "false_matches" }, // 공고 매칭 — 없는 근거로 만든 매칭 수
] as const;

export type HeroMetric = { key: string; label: string; value: string };

/** 회차에서 첫 화면 수치를 고른다. 그 회차에 없거나 돌리지 못한 평가는 빼고 보인다(리포트 링크로 전체를 본다). */
export function heroMetrics(run: ReportRun): HeroMetric[] {
  return HERO_METRICS.flatMap(({ evalKey, metricKey }) => {
    const evaluation = run.evals.find((item) => item.key === evalKey);
    const metric = evaluation?.metrics.find((item) => item.key === metricKey);
    if (!evaluation || !metric || evaluation.status === "failed") return [];
    return [{ key: `${evalKey}.${metricKey}`, label: metric.label, value: metric.display }];
  });
}

const HERO_DATA_KEYS = new Set(["experiences", "postings"]);

/** 수치 아래 각주의 데이터 규모 — Figma처럼 카드 · 공고 두 가지만(전체는 리포트에). */
export function heroDataSize(run: ReportRun): string {
  return dataSizeText(run.data_items.filter((item) => HERO_DATA_KEYS.has(item.key)));
}
