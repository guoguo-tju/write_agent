import React, { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Clipboard,
  Clock3,
  Edit3,
  Loader2,
  RefreshCw,
  Save,
  X,
  XCircle
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AppTopNav, Pagination } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  getReview,
  getRewritesPage,
  getReviewsByRewrite,
  manualEdit,
  startReview,
  type ReviewRecord,
  type RewriteRecord,
} from "../services/api";
import "./ReviewsPage.css";

type RewriteStatus = "completed" | "failed" | "running" | "pending";
type WorkflowTrackState = "pending" | "running" | "completed" | "failed";
const QUEUE_PAGE_SIZE = 10;

const parseRewriteId = (value: string | null): number | null => {
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
};

const formatTime = (value: string, locale = "zh-CN") => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const summarize = (value: string, maxLength = 72) => {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}...`;
};

const statusClassName = (status: string) => {
  if (
    status === "completed" ||
    status === "failed" ||
    status === "running" ||
    status === "pending"
  ) {
    return status;
  }
  return "pending";
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case "completed":
      return <CheckCircle2 size={14} />;
    case "failed":
      return <XCircle size={14} />;
    default:
      return <Clock3 size={14} />;
  }
};

const sortReviews = (items: ReviewRecord[]) =>
  [...items].sort((left, right) => {
    const leftTime = Date.parse(left.updated_at || left.created_at || "");
    const rightTime = Date.parse(right.updated_at || right.created_at || "");
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
      return rightTime - leftTime;
    }
    return right.id - left.id;
  });

interface ReviewIssue {
  type?: string;
  severity?: string;
  location?: string;
  description?: string;
  suggestion?: string;
}

interface ReviewFeedback {
  passed?: boolean;
  reason?: string;
  ai_detection?: {
    has_ai_smell?: boolean;
    issues?: string[];
    examples?: string[];
  };
  quality_scores?: {
    total?: number;
    authenticity?: number;
  };
  issues?: ReviewIssue[];
}

export const ReviewsPage: React.FC = () => {
  const navigate = useNavigate();
  const { lang, text } = useLanguage();
  const reviewsText = text.reviews;
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const tx = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const tf = (template: string, vars: Record<string, string | number>) =>
    formatMessage(template, vars);
  const getStatusLabel = (status: RewriteStatus) => {
    if (status === "completed") return reviewsText.completed;
    if (status === "failed") return reviewsText.failed;
    if (status === "running") return reviewsText.running;
    return reviewsText.pending;
  };
  const getWorkflowStateLabel = (state: WorkflowTrackState) => {
    if (state === "completed") return reviewsText.workflowStateCompleted;
    if (state === "failed") return reviewsText.workflowStateFailed;
    if (state === "running") return reviewsText.workflowStateRunning;
    return reviewsText.workflowStatePending;
  };
  const [searchParams, setSearchParams] = useSearchParams();
  const rewriteIdFromQuery = parseRewriteId(searchParams.get("rewrite_id"));

  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [queuePage, setQueuePage] = useState(1);
  const [queueTotal, setQueueTotal] = useState(0);
  const [selectedRewriteId, setSelectedRewriteId] = useState<number | null>(
    rewriteIdFromQuery,
  );
  const [isLoading, setIsLoading] = useState(true);

  const [latestReview, setLatestReview] = useState<ReviewRecord | null>(null);
  const [reviewHistory, setReviewHistory] = useState<ReviewRecord[]>([]);
  const [isReviewLoading, setIsReviewLoading] = useState(false);

  const [isEditing, setIsEditing] = useState(false);
  const [editedContent, setEditedContent] = useState("");
  const [editNote, setEditNote] = useState("");
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [isRunningReview, setIsRunningReview] = useState(false);
  const [editMessage, setEditMessage] = useState("");
  const [showReviewModal, setShowReviewModal] = useState(false);

  const selectedRewrite = useMemo(
    () => rewrites.find((item) => item.id === selectedRewriteId) || null,
    [rewrites, selectedRewriteId],
  );

  const reviewFeedback = useMemo(() => {
    if (!latestReview?.feedback) {
      return null;
    }
    if (typeof latestReview.feedback !== "string") {
      return {
        parsed: latestReview.feedback as unknown as ReviewFeedback,
        raw: JSON.stringify(latestReview.feedback, null, 2),
        parseError: false,
      };
    }

    try {
      const parsed = JSON.parse(latestReview.feedback) as ReviewFeedback;
      return {
        parsed,
        raw: JSON.stringify(parsed, null, 2),
        parseError: false,
      };
    } catch {
      return {
        parsed: null,
        raw: latestReview.feedback,
        parseError: true,
      };
    }
  }, [latestReview?.feedback]);

  const workflowTrack = useMemo(() => {
    const round1 = reviewHistory.find((item) => (item.round || 0) === 1);
    const round2 = reviewHistory.find((item) => (item.round || 0) === 2);

    const resolveReviewState = (item?: ReviewRecord): WorkflowTrackState => {
      if (!item) {
        return "pending";
      }
      if (item.result === "passed") {
        return "completed";
      }
      if (item.result === "failed" || item.status === "failed") {
        return "failed";
      }
      if (item.status === "running" || item.status === "pending") {
        return "running";
      }
      return "pending";
    };

    const rewriteRound1: WorkflowTrackState =
      !selectedRewrite
        ? "pending"
        : selectedRewrite.status === "failed"
          ? "failed"
          : selectedRewrite.status === "running"
            ? "running"
            : "completed";

    const reviewRound1 = resolveReviewState(round1);

    let rewriteRound2: WorkflowTrackState = "pending";
    if (round2) {
      rewriteRound2 = "completed";
    } else if (round1 && (round1.result === "failed" || round1.status === "failed")) {
      rewriteRound2 = selectedRewrite?.status === "running" ? "running" : "pending";
    }

    const reviewRound2 = resolveReviewState(round2);

    return [
      { key: "r1w", label: reviewsText.workflowStepRewriteRound1, state: rewriteRound1 },
      { key: "r1r", label: reviewsText.workflowStepReviewRound1, state: reviewRound1 },
      { key: "r2w", label: reviewsText.workflowStepRewriteRound2, state: rewriteRound2 },
      { key: "r2r", label: reviewsText.workflowStepReviewRound2, state: reviewRound2 },
    ] as const;
  }, [reviewHistory, reviewsText, selectedRewrite]);

  const syncRewriteQuery = (rewriteId: number | null) => {
    const next = new URLSearchParams(searchParams);
    if (rewriteId) {
      next.set("rewrite_id", String(rewriteId));
    } else {
      next.delete("rewrite_id");
    }
    setSearchParams(next, { replace: true });
  };

  const loadLatestReview = async (rewriteId: number) => {
    setIsReviewLoading(true);
    try {
      const result = await getReviewsByRewrite(rewriteId);
      const sorted = sortReviews(result.items);
      setReviewHistory(sorted);
      const latest = sorted[0] || null;
      if (!latest) {
        setLatestReview(null);
        return;
      }
      const detail = await getReview(latest.id);
      setLatestReview(detail);
    } catch (error) {
      console.error("加载审核详情失败:", error);
      setLatestReview(null);
      setReviewHistory([]);
    } finally {
      setIsReviewLoading(false);
    }
  };

  const loadData = async (page = queuePage) => {
    setIsLoading(true);
    try {
      const response = await getRewritesPage({
        page,
        limit: QUEUE_PAGE_SIZE,
      });
      setRewrites(response.items);
      setQueueTotal(response.total);

      const preferredId =
        rewriteIdFromQuery && response.items.some((item) => item.id === rewriteIdFromQuery)
          ? rewriteIdFromQuery
          : selectedRewriteId && response.items.some((item) => item.id === selectedRewriteId)
            ? selectedRewriteId
            : response.items[0]?.id ?? null;

      setSelectedRewriteId(preferredId);
      if (!rewriteIdFromQuery && preferredId) {
        syncRewriteQuery(preferredId);
      }
    } catch (error) {
      console.error("加载审核记录失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadData(queuePage);
  }, [queuePage]);

  useEffect(() => {
    if (
      rewriteIdFromQuery &&
      rewriteIdFromQuery !== selectedRewriteId &&
      rewrites.some((item) => item.id === rewriteIdFromQuery)
    ) {
      setSelectedRewriteId(rewriteIdFromQuery);
    }
  }, [rewriteIdFromQuery, rewrites, selectedRewriteId]);

  useEffect(() => {
    if (!selectedRewriteId) {
      setLatestReview(null);
      setReviewHistory([]);
      return;
    }
    void loadLatestReview(selectedRewriteId);
  }, [selectedRewriteId]);

  useEffect(() => {
    if (!selectedRewrite) {
      setIsEditing(false);
      setEditedContent("");
      setEditNote("");
      setEditMessage("");
      setShowReviewModal(false);
      return;
    }

    setIsEditing(false);
    setEditedContent(selectedRewrite.final_content || "");
    setEditNote("");
    setEditMessage("");
    setShowReviewModal(false);
  }, [selectedRewrite?.id]);

  const copyResult = async () => {
    if (!selectedRewrite?.final_content) {
      return;
    }
    await navigator.clipboard.writeText(selectedRewrite.final_content);
  };

  const handleStartEdit = async () => {
    if (!selectedRewrite?.id) {
      return;
    }
    if (!latestReview) {
      await handleRunReview(true);
      return;
    }
    setEditedContent(selectedRewrite.final_content || "");
    setIsEditing(true);
    setEditMessage("");
  };

  const handleCancelEdit = () => {
    if (!selectedRewrite) {
      return;
    }
    setIsEditing(false);
    setEditedContent(selectedRewrite.final_content || "");
    setEditNote("");
    setEditMessage("");
  };

  const handleSaveEdit = async () => {
    if (!selectedRewrite?.id || !latestReview) {
      return;
    }

    const content = editedContent.trim();
    if (!content) {
      setEditMessage(reviewsText.contentRequired);
      return;
    }

    setIsSavingEdit(true);
    setEditMessage("");
    try {
      await manualEdit(
        latestReview.id,
        content,
        editNote.trim() || undefined,
      );
      setIsEditing(false);
      setEditNote("");
      setEditMessage(reviewsText.manualEditSaved);
      await loadData();
      if (selectedRewriteId) {
        await loadLatestReview(selectedRewriteId);
      }
    } catch (error) {
      console.error("保存人工编辑失败:", error);
      setEditMessage(error instanceof Error ? error.message : reviewsText.saveFailed);
    } finally {
      setIsSavingEdit(false);
    }
  };

  const handleRunReview = async (enterEdit = false) => {
    if (!selectedRewrite?.id) {
      return;
    }

    setIsRunningReview(true);
    setEditMessage("");
    try {
      const review = await startReview({ rewrite_id: selectedRewrite.id });
      setLatestReview(review);
      if (enterEdit) {
        setIsEditing(true);
        setEditedContent(selectedRewrite.final_content || "");
        setEditMessage(reviewsText.reviewDoneEnterEdit);
      } else {
        setEditMessage(reviewsText.reviewDoneView);
      }
    } catch (error) {
      console.error("执行审核失败:", error);
      setEditMessage(error instanceof Error ? error.message : reviewsText.reviewFailed);
    } finally {
      setIsRunningReview(false);
    }
  };

  const handleSelectRewrite = (rewriteId: number) => {
    setSelectedRewriteId(rewriteId);
    syncRewriteQuery(rewriteId);
  };

  const handleOpenReviewModal = async () => {
    if (!selectedRewrite?.id) {
      return;
    }
    setShowReviewModal(true);
    if (!latestReview && !isRunningReview) {
      await handleRunReview(false);
    }
  };

  return (
    <div className="reviews-v2-page">
      <AppTopNav />

      <main className="reviews-v2-main">
        <aside className="reviews-v2-queue">
          <div className="reviews-v2-panel-head">
            <div>
              <h1>{reviewsText.queueTitle}</h1>
              <p>{tf(reviewsText.queueSubtitle, { total: queueTotal, size: QUEUE_PAGE_SIZE })}</p>
            </div>
            <button type="button" onClick={() => void loadData()} disabled={isLoading}>
              {isLoading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              {reviewsText.refresh}
            </button>
          </div>

          <div className="reviews-v2-queue-list">
            {isLoading ? (
              <div className="reviews-v2-empty">{reviewsText.loading}</div>
            ) : rewrites.length === 0 ? (
              <div className="reviews-v2-empty">{reviewsText.empty}</div>
            ) : (
              rewrites.map((rewrite) => {
                const normalizedStatus = statusClassName(rewrite.status) as RewriteStatus;

                return (
                  <button
                    key={rewrite.id}
                    type="button"
                    className={`reviews-v2-queue-item ${selectedRewriteId === rewrite.id ? "active" : ""}`}
                    onClick={() => handleSelectRewrite(rewrite.id)}
                  >
                    <div className="reviews-v2-queue-item-head">
                      <span>#{rewrite.id}</span>
                      <strong className={`status-${normalizedStatus}`}>
                        {getStatusIcon(normalizedStatus)}
                        {getStatusLabel(normalizedStatus)}
                      </strong>
                    </div>
                    <p>{summarize(rewrite.source_article)}</p>
                    <div className="reviews-v2-queue-item-meta">
                      <span>{formatTime(rewrite.created_at, locale)}</span>
                      <span>{rewrite.style_name || reviewsText.unknownStyle}</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
          <div className="reviews-v2-queue-pagination">
            <Pagination
              page={queuePage}
              total={queueTotal}
              limit={QUEUE_PAGE_SIZE}
              onPageChange={(nextPage) => setQueuePage(nextPage)}
            />
          </div>
        </aside>

        <section className="reviews-v2-source">
          <div className="reviews-v2-panel-head">
            <div>
              <h2>{tx("原文", "Source")}</h2>
              <p>{selectedRewrite ? `#${selectedRewrite.id}` : reviewsText.chooseRecord}</p>
            </div>
          </div>

          {selectedRewrite ? (
            <>
              <div className="reviews-v2-meta-row">
                <span>
                  {tx("状态：", "Status:")}
                  <strong className={`status-${statusClassName(selectedRewrite.status)}`}>
                    {getStatusLabel(statusClassName(selectedRewrite.status) as RewriteStatus)}
                  </strong>
                </span>
                <span>{tf(reviewsText.targetWords, { count: selectedRewrite.target_words || 0 })}</span>
                <span>{tf(reviewsText.style, { name: selectedRewrite.style_name || reviewsText.unknown })}</span>
              </div>
              <article className="reviews-v2-paper">{selectedRewrite.source_article}</article>
            </>
          ) : (
            <div className="reviews-v2-empty reviews-v2-paper-empty">{reviewsText.chooseRecord}</div>
          )}
        </section>

        <section className="reviews-v2-result">
          <div className="reviews-v2-panel-head">
            <div>
              <h2>{tx("改写结果", "Rewrite Result")}</h2>
              <p>
                {selectedRewrite
                  ? tf(reviewsText.updatedAt, {
                      time: formatTime(selectedRewrite.updated_at, locale),
                    })
                  : ""}
              </p>
            </div>
            <div className="reviews-v2-result-actions">
              <button
                type="button"
                onClick={() => {
                  if (selectedRewrite?.id) {
                    navigate(`/layout?rewrite_id=${selectedRewrite.id}`);
                  }
                }}
                disabled={!selectedRewrite?.id || isEditing}
              >
                {reviewsText.goToLayout}
              </button>
              <button type="button" onClick={copyResult} disabled={!selectedRewrite?.final_content || isEditing}>
                <Clipboard size={14} />
                {tx("复制", "Copy")}
              </button>
              <button
                type="button"
                onClick={() => void handleOpenReviewModal()}
                disabled={!selectedRewrite?.id || isRunningReview || isSavingEdit || isEditing}
              >
                {isRunningReview ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    {tx("审核中...", "Reviewing...")}
                  </>
                ) : latestReview ? reviewsText.viewEditorReview : reviewsText.startEditorReview}
              </button>
              <button
                type="button"
                onClick={() => void handleStartEdit()}
                disabled={!selectedRewrite?.id || isEditing || isSavingEdit || isRunningReview || isReviewLoading}
              >
                {isRunningReview || isReviewLoading ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    {tx("准备中...", "Preparing...")}
                  </>
                ) : (
                  <>
                    <Edit3 size={14} />
                    {tx("人工编辑", "Manual Edit")}
                  </>
                )}
              </button>
            </div>
          </div>

          {selectedRewrite ? (
            <>
              <section className="reviews-v2-workflow-track">
                <div className="reviews-v2-workflow-head">
                  <h3>{reviewsText.workflowTrackTitle}</h3>
                  <span>{reviewsText.workflowTrackSubtitle}</span>
                </div>
                <div className="reviews-v2-workflow-grid">
                  {workflowTrack.map((item) => (
                    <article key={item.key} className={`workflow-${item.state}`}>
                      <strong>{item.label}</strong>
                      <span>{getWorkflowStateLabel(item.state)}</span>
                    </article>
                  ))}
                </div>
              </section>

              {selectedRewrite.error_message && (
                <div className="reviews-v2-error">
                  {tx("错误信息：", "Error:")} {selectedRewrite.error_message}
                </div>
              )}
              {isEditing ? (
                <div className="reviews-v2-inline-edit">
                  <label>
                    {tx("编辑内容", "Edited Content")}
                    <textarea
                      value={editedContent}
                      onChange={(event) => setEditedContent(event.target.value)}
                      placeholder={reviewsText.editorPlaceholder}
                    />
                  </label>
                  <label>
                    {tx("编辑备注（可选）", "Edit Note (Optional)")}
                    <input
                      value={editNote}
                      onChange={(event) => setEditNote(event.target.value)}
                      placeholder={reviewsText.notePlaceholder}
                    />
                  </label>
                  <div className="reviews-v2-manual-actions">
                    <button
                      type="button"
                      className="ghost"
                      onClick={handleCancelEdit}
                      disabled={isSavingEdit}
                    >
                      <X size={14} />
                      {reviewsText.cancel}
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={handleSaveEdit}
                      disabled={isSavingEdit || !editedContent.trim()}
                    >
                      {isSavingEdit ? (
                        <>
                          <Loader2 size={14} className="spin" />
                          {reviewsText.saving}
                        </>
                      ) : (
                        <>
                          <Save size={14} />
                          {reviewsText.save}
                        </>
                      )}
                    </button>
                  </div>
                </div>
              ) : (
                <article className="reviews-v2-paper">
                  {selectedRewrite.final_content || reviewsText.noRewriteResult}
                </article>
              )}

              {!latestReview && !isReviewLoading && (
                <div className="reviews-v2-manual-empty">
                  {tx(
                    "当前记录暂无审核结果，可点击上方“主编审核”查看。",
                    "No review result yet. Click Editor Review above to generate one.",
                  )}
                </div>
              )}

              {editMessage && <div className="reviews-v2-manual-message">{editMessage}</div>}
            </>
          ) : (
            <div className="reviews-v2-empty reviews-v2-paper-empty">{reviewsText.chooseRecord}</div>
          )}
        </section>
      </main>

      {showReviewModal && (
        <div
          className="reviews-v2-feedback-modal-mask"
          onClick={() => setShowReviewModal(false)}
        >
          <div
            className="reviews-v2-feedback-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="reviews-v2-feedback-modal-head">
              <div>
                <h3>{tx("主编审核意见", "Editor Review Notes")}</h3>
                <p>
                  {latestReview
                    ? tf(reviewsText.roundAndTime, {
                        round: latestReview.round || 1,
                        time: formatTime(latestReview.created_at, locale),
                      })
                    : reviewsText.noReviewRecord}
                </p>
              </div>
              <div className="reviews-v2-feedback-modal-actions">
                <button
                  type="button"
                  onClick={() => void handleRunReview(false)}
                  disabled={!selectedRewrite?.id || isRunningReview || isSavingEdit}
                >
                  {isRunningReview ? (
                    <>
                      <Loader2 size={14} className="spin" />
                      {tx("审核中...", "Reviewing...")}
                    </>
                  ) : reviewsText.runReviewAgain}
                </button>
                <button type="button" onClick={() => setShowReviewModal(false)}>
                  {tx("关闭", "Close")}
                </button>
              </div>
            </div>

            <div className="reviews-v2-feedback-modal-body">
              {isReviewLoading || isRunningReview ? (
                <div className="reviews-v2-manual-empty">
                  {tx("正在加载主编审核意见...", "Loading editor review...")}
                </div>
              ) : latestReview ? (
                <section className="reviews-v2-feedback">
                  {reviewFeedback?.parseError ? (
                    <div className="reviews-v2-feedback-fallback">
                      <p>
                        {tx(
                          "审核意见解析失败，已展示原始内容：",
                          "Failed to parse review details. Raw payload is shown:",
                        )}
                      </p>
                      <pre>{reviewFeedback.raw}</pre>
                    </div>
                  ) : (
                    <>
                      <div className="reviews-v2-feedback-summary">
                        <span>
                          {tx("结论：", "Result:")}
                          <strong
                            className={
                              (reviewFeedback?.parsed?.passed ?? latestReview.result === "passed")
                                ? "passed"
                                : "failed"
                            }
                          >
                            {(reviewFeedback?.parsed?.passed ?? latestReview.result === "passed")
                              ? reviewsText.pass
                              : reviewsText.reject}
                          </strong>
                        </span>
                        <span>{tx("总分：", "Score:")}{reviewFeedback?.parsed?.quality_scores?.total ?? latestReview.total_score ?? "--"}</span>
                        <span>
                          {tx("AI味道：", "AI smell:")}
                          {reviewFeedback?.parsed?.ai_detection?.has_ai_smell === undefined
                            ? "--"
                            : reviewFeedback?.parsed?.ai_detection?.has_ai_smell
                              ? reviewsText.aiSmellHigh
                              : reviewsText.aiSmellLow}
                        </span>
                      </div>

                      {reviewFeedback?.parsed?.reason && (
                        <div className="reviews-v2-feedback-reason">
                          {reviewFeedback.parsed.reason}
                        </div>
                      )}

                      {(reviewFeedback?.parsed?.issues || []).length > 0 ? (
                        <div className="reviews-v2-feedback-issues">
                          {(reviewFeedback?.parsed?.issues || []).map((issue, index) => (
                            <article key={`${issue.type || "issue"}-${index}`}>
                              <div>
                                <strong>{issue.type || reviewsText.uncategorizedIssue}</strong>
                                <span>{issue.severity || reviewsText.pendingConfirm}</span>
                                <span>{issue.location || reviewsText.locationUnknown}</span>
                              </div>
                              <p>{issue.description || reviewsText.noDescription}</p>
                              {issue.suggestion && <p>{tx("建议：", "Suggestion:")}{issue.suggestion}</p>}
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="reviews-v2-manual-empty">
                          {tx(
                            "当前审核未返回问题清单。",
                            "No issue list was returned in this review.",
                          )}
                        </div>
                      )}

                      <details className="reviews-v2-feedback-raw">
                        <summary>{tx("查看原始 JSON", "View Raw JSON")}</summary>
                        <pre>{reviewFeedback?.raw || "{}"}</pre>
                      </details>
                    </>
                  )}
                </section>
              ) : (
                <div className="reviews-v2-manual-empty">
                  {tx(
                    "当前记录暂无审核结果，请先点击“重新主编审核”。",
                    "No review result yet. Please click Run Review Again first.",
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
