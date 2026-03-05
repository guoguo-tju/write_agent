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
import { useSearchParams } from "react-router-dom";
import { AppTopNav, Pagination } from "../components";
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

const formatTime = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString("zh-CN", {
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

const statusLabel: Record<RewriteStatus, string> = {
  completed: "已完成",
  failed: "失败",
  running: "处理中",
  pending: "待处理",
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
      const latest = sortReviews(result.items)[0] || null;
      if (!latest) {
        setLatestReview(null);
        return;
      }
      const detail = await getReview(latest.id);
      setLatestReview(detail);
    } catch (error) {
      console.error("加载审核详情失败:", error);
      setLatestReview(null);
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
      setEditMessage("编辑内容不能为空。");
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
      setEditMessage("人工编辑已保存并生效。");
      await loadData();
      if (selectedRewriteId) {
        await loadLatestReview(selectedRewriteId);
      }
    } catch (error) {
      console.error("保存人工编辑失败:", error);
      setEditMessage(error instanceof Error ? error.message : "保存失败，请重试。");
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
        setEditMessage("审核已完成，已进入人工编辑模式。");
      } else {
        setEditMessage("主编审核已完成，可在弹框中查看审核意见。");
      }
    } catch (error) {
      console.error("执行审核失败:", error);
      setEditMessage(error instanceof Error ? error.message : "执行审核失败，请稍后重试。");
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
              <h1>审核队列</h1>
              <p>共 {queueTotal} 条，每页 {QUEUE_PAGE_SIZE} 条</p>
            </div>
            <button type="button" onClick={() => void loadData()} disabled={isLoading}>
              {isLoading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              刷新
            </button>
          </div>

          <div className="reviews-v2-queue-list">
            {isLoading ? (
              <div className="reviews-v2-empty">加载中...</div>
            ) : rewrites.length === 0 ? (
              <div className="reviews-v2-empty">暂无改写记录</div>
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
                        {statusLabel[normalizedStatus]}
                      </strong>
                    </div>
                    <p>{summarize(rewrite.source_article)}</p>
                    <div className="reviews-v2-queue-item-meta">
                      <span>{formatTime(rewrite.created_at)}</span>
                      <span>{rewrite.style_name || "未知风格"}</span>
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
              <h2>原文</h2>
              <p>{selectedRewrite ? `#${selectedRewrite.id}` : "请选择记录"}</p>
            </div>
          </div>

          {selectedRewrite ? (
            <>
              <div className="reviews-v2-meta-row">
                <span>
                  状态：
                  <strong className={`status-${statusClassName(selectedRewrite.status)}`}>
                    {statusLabel[statusClassName(selectedRewrite.status) as RewriteStatus]}
                  </strong>
                </span>
                <span>目标字数：{selectedRewrite.target_words || 0}</span>
                <span>风格：{selectedRewrite.style_name || "未知"}</span>
              </div>
              <article className="reviews-v2-paper">{selectedRewrite.source_article}</article>
            </>
          ) : (
            <div className="reviews-v2-empty reviews-v2-paper-empty">请选择左侧记录查看原文</div>
          )}
        </section>

        <section className="reviews-v2-result">
          <div className="reviews-v2-panel-head">
            <div>
              <h2>改写结果</h2>
              <p>{selectedRewrite ? `更新时间 ${formatTime(selectedRewrite.updated_at)}` : ""}</p>
            </div>
            <div className="reviews-v2-result-actions">
              <button type="button" onClick={copyResult} disabled={!selectedRewrite?.final_content || isEditing}>
                <Clipboard size={14} />
                复制
              </button>
              <button
                type="button"
                onClick={() => void handleOpenReviewModal()}
                disabled={!selectedRewrite?.id || isRunningReview || isSavingEdit || isEditing}
              >
                {isRunningReview ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    审核中...
                  </>
                ) : latestReview ? "查看主编审核" : "主编审核"}
              </button>
              <button
                type="button"
                onClick={() => void handleStartEdit()}
                disabled={!selectedRewrite?.id || isEditing || isSavingEdit || isRunningReview || isReviewLoading}
              >
                {isRunningReview || isReviewLoading ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    准备中...
                  </>
                ) : (
                  <>
                    <Edit3 size={14} />
                    人工编辑
                  </>
                )}
              </button>
            </div>
          </div>

          {selectedRewrite ? (
            <>
              {selectedRewrite.error_message && (
                <div className="reviews-v2-error">错误信息：{selectedRewrite.error_message}</div>
              )}
              {isEditing ? (
                <div className="reviews-v2-inline-edit">
                  <label>
                    编辑内容
                    <textarea
                      value={editedContent}
                      onChange={(event) => setEditedContent(event.target.value)}
                      placeholder="请输入人工优化后的正文内容"
                    />
                  </label>
                  <label>
                    编辑备注（可选）
                    <input
                      value={editNote}
                      onChange={(event) => setEditNote(event.target.value)}
                      placeholder="例如：精简开头、调整段落顺序"
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
                      取消
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
                          保存中...
                        </>
                      ) : (
                        <>
                          <Save size={14} />
                          保存并生效
                        </>
                      )}
                    </button>
                  </div>
                </div>
              ) : (
                <article className="reviews-v2-paper">
                  {selectedRewrite.final_content || "暂无改写结果"}
                </article>
              )}

              {!latestReview && !isReviewLoading && (
                <div className="reviews-v2-manual-empty">
                  当前记录暂无审核结果，可点击上方“主编审核”查看。
                </div>
              )}

              {editMessage && <div className="reviews-v2-manual-message">{editMessage}</div>}
            </>
          ) : (
            <div className="reviews-v2-empty reviews-v2-paper-empty">请选择左侧记录查看结果</div>
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
                <h3>主编审核意见</h3>
                <p>
                  {latestReview
                    ? `第 ${latestReview.round || 1} 轮 · ${formatTime(latestReview.created_at)}`
                    : "尚无审核记录"}
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
                      审核中...
                    </>
                  ) : "重新主编审核"}
                </button>
                <button type="button" onClick={() => setShowReviewModal(false)}>
                  关闭
                </button>
              </div>
            </div>

            <div className="reviews-v2-feedback-modal-body">
              {isReviewLoading || isRunningReview ? (
                <div className="reviews-v2-manual-empty">正在加载主编审核意见...</div>
              ) : latestReview ? (
                <section className="reviews-v2-feedback">
                  {reviewFeedback?.parseError ? (
                    <div className="reviews-v2-feedback-fallback">
                      <p>审核意见解析失败，已展示原始内容：</p>
                      <pre>{reviewFeedback.raw}</pre>
                    </div>
                  ) : (
                    <>
                      <div className="reviews-v2-feedback-summary">
                        <span>
                          结论：
                          <strong
                            className={
                              (reviewFeedback?.parsed?.passed ?? latestReview.result === "passed")
                                ? "passed"
                                : "failed"
                            }
                          >
                            {(reviewFeedback?.parsed?.passed ?? latestReview.result === "passed")
                              ? "通过"
                              : "不通过"}
                          </strong>
                        </span>
                        <span>总分：{reviewFeedback?.parsed?.quality_scores?.total ?? latestReview.total_score ?? "--"}</span>
                        <span>
                          AI味道：
                          {reviewFeedback?.parsed?.ai_detection?.has_ai_smell === undefined
                            ? "--"
                            : reviewFeedback?.parsed?.ai_detection?.has_ai_smell
                              ? "明显"
                              : "可接受"}
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
                                <strong>{issue.type || "未分类问题"}</strong>
                                <span>{issue.severity || "待确认"}</span>
                                <span>{issue.location || "位置未标注"}</span>
                              </div>
                              <p>{issue.description || "无描述"}</p>
                              {issue.suggestion && <p>建议：{issue.suggestion}</p>}
                            </article>
                          ))}
                        </div>
                      ) : (
                        <div className="reviews-v2-manual-empty">当前审核未返回问题清单。</div>
                      )}

                      <details className="reviews-v2-feedback-raw">
                        <summary>查看原始 JSON</summary>
                        <pre>{reviewFeedback?.raw || "{}"}</pre>
                      </details>
                    </>
                  )}
                </section>
              ) : (
                <div className="reviews-v2-manual-empty">
                  当前记录暂无审核结果，请先点击“重新主编审核”。
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
