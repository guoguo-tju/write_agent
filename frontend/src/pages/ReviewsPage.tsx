import React, { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Clipboard,
  Clock3,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { AppTopNav } from "../components";
import { getRewrites, type RewriteRecord } from "../services/api";
import "./ReviewsPage.css";

type RewriteStatus = "completed" | "failed" | "running" | "pending";

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
  if (status === "completed" || status === "failed" || status === "running" || status === "pending") {
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

export const ReviewsPage: React.FC = () => {
  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [selectedRewriteId, setSelectedRewriteId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    void loadData();
  }, []);

  const selectedRewrite = useMemo(
    () => rewrites.find((item) => item.id === selectedRewriteId) || null,
    [rewrites, selectedRewriteId],
  );

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
      setSelectedRewriteId((prev) => {
        if (prev && sorted.some((item) => item.id === prev)) {
          return prev;
        }
        return sorted[0]?.id ?? null;
      });
    } catch (error) {
      console.error("加载审核记录失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const copyResult = async () => {
    if (!selectedRewrite?.final_content) {
      return;
    }
    await navigator.clipboard.writeText(selectedRewrite.final_content);
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
                    onClick={() => setSelectedRewriteId(rewrite.id)}
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
            <button type="button" onClick={copyResult} disabled={!selectedRewrite?.final_content}>
              <Clipboard size={14} />
              复制
            </button>
          </div>

          {selectedRewrite ? (
            <>
              {selectedRewrite.error_message && (
                <div className="reviews-v2-error">错误信息：{selectedRewrite.error_message}</div>
              )}
              <article className="reviews-v2-paper">
                {selectedRewrite.final_content || "暂无改写结果"}
              </article>
            </>
          ) : (
            <div className="reviews-v2-empty reviews-v2-paper-empty">请选择左侧记录查看结果</div>
          )}
        </section>
      </main>
    </div>
  );
};
