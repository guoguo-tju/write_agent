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
import { AppTopNav } from "../components";
import {
  getRewrites,
  getReviewsByRewrite,
  manualEdit,
  startReview,
  type ReviewRecord,
  type RewriteRecord,
} from "../services/api";
import "./ReviewsPage.css";

type RewriteStatus = "completed" | "failed" | "running" | "pending";

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

export const ReviewsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const rewriteIdFromQuery = parseRewriteId(searchParams.get("rewrite_id"));

  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
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

  const selectedRewrite = useMemo(
    () => rewrites.find((item) => item.id === selectedRewriteId) || null,
    [rewrites, selectedRewriteId],
  );

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
      setLatestReview(latest);
    } catch (error) {
      console.error("加载审核详情失败:", error);
      setLatestReview(null);
    } finally {
      setIsReviewLoading(false);
    }
  };

  const loadData = async () => {
    setIsLoading(true);
    try {
      const data = await getRewrites();
      const sorted = [...data].sort((left, right) => {
        const leftTime = Date.parse(left.updated_at || left.created_at);
        const rightTime = Date.parse(right.updated_at || right.created_at);
        return rightTime - leftTime;
      });
      setRewrites(sorted);

      const preferredId =
        rewriteIdFromQuery && sorted.some((item) => item.id === rewriteIdFromQuery)
          ? rewriteIdFromQuery
          : sorted[0]?.id ?? null;

      setSelectedRewriteId(preferredId);
      syncRewriteQuery(preferredId);
    } catch (error) {
      console.error("加载审核记录失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

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
      return;
    }

    setIsEditing(false);
    setEditedContent(selectedRewrite.final_content || "");
    setEditNote("");
    setEditMessage("");
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
      await handleRunReviewThenEdit();
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

  const handleRunReviewThenEdit = async () => {
    if (!selectedRewrite?.id) {
      return;
    }

    setIsRunningReview(true);
    setEditMessage("");
    try {
      const review = await startReview({ rewrite_id: selectedRewrite.id });
      setLatestReview(review);
      setIsEditing(true);
      setEditedContent(selectedRewrite.final_content || "");
      setEditMessage("审核已完成，已进入人工编辑模式。");
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

  return (
    <div className="reviews-v2-page">
      <AppTopNav />

      <main className="reviews-v2-main">
        <aside className="reviews-v2-queue">
          <div className="reviews-v2-panel-head">
            <div>
              <h1>审核队列</h1>
              <p>{rewrites.length} 条改写记录</p>
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

              {!latestReview && !isEditing && (
                <div className="reviews-v2-manual-empty">
                  当前记录暂无审核结果，点击“人工编辑”会先自动执行审核，再进入编辑模式。
                </div>
              )}

              {editMessage && <div className="reviews-v2-manual-message">{editMessage}</div>}
              {latestReview && !isEditing && (
                <div className="reviews-v2-manual-empty">
                  已关联审核记录 #{latestReview.id}，可直接在改写结果区域进行人工编辑。
                </div>
              )}
              {!latestReview && isRunningReview && (
                <div className="reviews-v2-manual-empty">正在执行审核，请稍候...</div>
              )}
            </>
          ) : (
            <div className="reviews-v2-empty reviews-v2-paper-empty">请选择左侧记录查看结果</div>
          )}
        </section>
      </main>
    </div>
  );
};
