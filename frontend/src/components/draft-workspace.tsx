"use client";

// APL_02_003 자소서 탭(Figma 18:202): 왼쪽 문항 · 경험 카드(304) | 가운데 문항 편집(문장 + 근거 칩) | 오른쪽 검사 · 근거(304).
// 데이터: 처음은 서버 컴포넌트가 받은 값(initialDrafts), 그 뒤는 TanStack Query 캐시(D-012). 문장 하나를 적용할 때마다
// 서버가 version을 올리므로, 응답을 바로 캐시에 넣어야 다음 적용이 409가 나지 않는다(router.refresh를 기다리지 않음).
// 고른 문항 · 고른 문장 · 고치는 문장 · 카드 연결 창은 이 화면만 쓰는 상태라 useState.
// 파일 나눔: 왼쪽 draft-questions.tsx, 가운데 draft-editor.tsx, 오른쪽 draft-aside.tsx, [카드 연결] card-link-dialog.tsx.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CardLinkDialog } from "@/components/card-link-dialog";
import { DraftAside } from "@/components/draft-aside";
import { DraftEditor, type EditTarget } from "@/components/draft-editor";
import { DraftQuestions } from "@/components/draft-questions";
import { ApiRequestError } from "@/lib/api-request";
import type { CardSummary } from "@/lib/cards";
import {
  type ApplicationDrafts,
  type Draft,
  type EvidenceLink,
  type QuestionEdit,
  type SentenceEdit,
  draftsQueryKey,
  editsOf,
  fetchDrafts,
  replaceQuestions,
  setDraftCompleted,
  updateDraft,
  withDraft,
  writeDraft,
} from "@/lib/drafts";
import { SECONDARY_BUTTON_S } from "@/lib/ui-classes";

const CONFLICT = 409;
const NOT_FOUND = 404;

/** 다른 곳에서 먼저 바뀌었거나(409) 지워졌으면(404) 서버에서 새로 받아야 한다(1차 리뷰 R3). */
const needsRefetch = (error: Error) => error instanceof ApiRequestError && (error.status === CONFLICT || error.status === NOT_FOUND);

export function DraftWorkspace({ initialDrafts, cards }: { initialDrafts: ApplicationDrafts; cards: CardSummary[] | null }) {
  const applicationId = initialDrafts.applicationId;
  const queryKey = draftsQueryKey(applicationId);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey,
    queryFn: () => fetchDrafts(applicationId),
    initialData: initialDrafts,
    staleTime: 30_000, // 서버가 막 그린 값은 바로 다시 받지 않는다
    retry: 1, // 기본 3번(약 7초)이면 '최신 자소서를 불러오지 못했어요' 알림이 너무 늦다 — 한 번만 다시 시도
  });
  const data = query.data;

  const [selectedQuestionId, setSelectedQuestionId] = useState<number | null>(data.questions[0]?.id ?? null);
  const [selectedSentenceId, setSelectedSentenceId] = useState<number | null>(null);
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
  const [linkSentenceId, setLinkSentenceId] = useState<number | null>(null);

  const question = data.questions.find((item) => item.id === selectedQuestionId) ?? data.questions[0] ?? null;
  const draft = question?.draft ?? null;

  const refetch = () => queryClient.invalidateQueries({ queryKey });
  const refetchIfStale = (error: Error) => {
    if (needsRefetch(error)) void refetch();
  };
  // 저장 응답을 캐시에 넣는다. 서버가 저장하면서 근거를 다시 검사했으므로 '마지막 검사'는 저장 시각(서버 값)
  const putDraft = (saved: Draft) =>
    queryClient.setQueryData<ApplicationDrafts>(queryKey, (old) => (old ? { ...withDraft(old, saved), checkedAt: saved.updatedAt } : old));

  const write = useMutation({
    mutationFn: ({ questionId, overwrite }: { questionId: number; overwrite: boolean }) =>
      writeDraft(applicationId, questionId, overwrite),
    onSuccess: () => {
      setSelectedSentenceId(null);
      setEditTarget(null);
      return refetch();
    },
    onError: refetchIfStale,
  });

  const save = useMutation({
    mutationFn: ({ target, edits }: { target: Draft; edits: SentenceEdit[] }) => updateDraft(target, edits),
    onSuccess: (saved, { edits }) => {
      putDraft(saved);
      setEditTarget(null);
      setLinkSentenceId(null);
      // 저장하면 문장 번호가 새로 매겨진다 — 고른 문장을 같은 자리(편집 목록 순서)의 새 번호로 다시 고른다(3차 리뷰 R1)
      setSelectedSentenceId((current) => {
        const index = current === null ? -1 : edits.findIndex((item) => item.id === current);
        return index >= 0 ? (saved.sentences[index]?.id ?? null) : null;
      });
    },
    // 다른 탭이 먼저 저장했거나 다시 쓰기로 바뀜(409) · 지워짐(404) — 새로 받아 지금 초안을 보여 준다(고치던 글은 문구로 알림)
    onError: refetchIfStale,
  });

  const complete = useMutation({
    mutationFn: ({ draftId, completed }: { draftId: number; completed: boolean }) => setDraftCompleted(draftId, completed),
    onSuccess: putDraft,
    onError: refetchIfStale,
  });

  const questions = useMutation({
    mutationFn: ({ edits, removedIds }: { edits: QuestionEdit[]; removedIds: number[] }) =>
      replaceQuestions(applicationId, edits, removedIds),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKey, next);
      if (!next.questions.some((item) => item.id === selectedQuestionId)) setSelectedQuestionId(next.questions[0]?.id ?? null);
    },
    onError: refetchIfStale, // 다른 탭이 문항을 먼저 바꿈(409) — 새 목록을 받아 다시 고치게
  });

  const selectQuestion = (questionId: number) => {
    setSelectedQuestionId(questionId);
    setSelectedSentenceId(null);
    setEditTarget(null);
    save.reset();
  };

  const saveEdits = (edits: SentenceEdit[]) => {
    if (draft !== null) save.mutate({ target: draft, edits });
  };
  /** 지금 초안의 편집 목록에서 한 문장만 바꿔 저장한다. */
  const saveOne = (sentenceId: number, change: Partial<SentenceEdit>) => {
    if (draft !== null) saveEdits(editsOf(draft).map((item) => (item.id === sentenceId ? { ...item, ...change } : item)));
  };

  const removeSentence = (sentenceId: number) => {
    if (draft === null) return;
    if (draft.sentences.length === 1) {
      window.alert("문장이 하나만 남아 지울 수 없어요. 고쳐 쓰거나 [다시 쓰기]를 눌러 주세요.");
      return;
    }
    if (!window.confirm("이 문장을 지울까요?")) return;
    saveEdits(editsOf(draft).filter((item) => item.id !== sentenceId));
    setSelectedSentenceId(null);
  };

  const usedCardIds = new Set(
    (draft?.sentences ?? []).flatMap((item) =>
      item.evidenceStatus === "ok" && item.evidence?.cardId != null ? [item.evidence.cardId] : [],
    ),
  );
  const linkSentence = draft?.sentences.find((item) => item.id === linkSentenceId) ?? null;
  const writeVars = write.variables;

  return (
    <div className="flex flex-col gap-4 px-5 py-6 lg:px-12">
      {query.isError ? (
        // 다시 받기가 실패하면 지금 보이는 초안이 옛 것일 수 있다 — 저장해도 409가 이어지므로 알리고 다시 받게 한다
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-button border border-warning-text bg-bg-default p-3">
          <p className="text-body-2 text-text-main">최신 자소서를 불러오지 못했어요. 보이는 내용이 예전 것일 수 있어요.</p>
          <button type="button" onClick={() => void query.refetch()} className={SECONDARY_BUTTON_S}>
            다시 불러오기
          </button>
        </div>
      ) : null}
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <DraftQuestions
          questions={data.questions}
          selectedQuestionId={question?.id ?? null}
          onSelect={selectQuestion}
          saveQuestions={{
            pending: questions.isPending,
            error: questions.error,
            run: (edits, removedIds, onDone) => questions.mutate({ edits, removedIds }, { onSuccess: onDone }),
            reset: questions.reset,
          }}
          cards={cards}
          matchedCardIds={data.matchedCardIds}
          usedCardIds={usedCardIds}
        />
        <DraftEditor
          applicationId={applicationId}
          data={data}
          question={question}
          cards={cards}
          selection={{
            sentenceId: selectedSentenceId,
            onSelect: setSelectedSentenceId,
            editTarget,
            onEdit: setEditTarget,
          }}
          write={{
            pending: write.isPending,
            error: write.error,
            pendingQuestionId: write.isPending ? (writeVars?.questionId ?? null) : null,
            failedQuestionId: write.error && writeVars ? writeVars.questionId : null,
            emptyQuestionId: write.data && !write.data.written && writeVars ? writeVars.questionId : null,
            run: (questionId, overwrite) => write.mutate({ questionId, overwrite }),
          }}
          save={{ pending: save.isPending, error: save.error, run: saveEdits }}
          complete={{
            pending: complete.isPending,
            error: complete.error,
            run: (draftId, completed) => complete.mutate({ draftId, completed }),
          }}
        />
        <DraftAside
          draft={draft}
          selectedSentenceId={selectedSentenceId}
          onSelectSentence={setSelectedSentenceId}
          busy={save.isPending}
          onEdit={(sentenceId) => {
            setSelectedSentenceId(sentenceId);
            setEditTarget({ kind: "edit", sentenceId });
          }}
          onInsertAfter={(sentenceId) => setEditTarget({ kind: "insert", afterSentenceId: sentenceId })}
          onRemove={removeSentence}
          onLink={setLinkSentenceId}
          onUnlink={(sentenceId) => saveOne(sentenceId, { unlink: true })}
        />
        <CardLinkDialog
          sentence={linkSentence}
          cards={cards}
          matchedCardIds={data.matchedCardIds}
          busy={save.isPending}
          error={linkSentence !== null ? save.error : null}
          onClose={() => {
            setLinkSentenceId(null);
            save.reset();
          }}
          onLink={(link: EvidenceLink) => {
            if (linkSentence !== null) saveOne(linkSentence.id, { link });
          }}
        />
      </div>
    </div>
  );
}
