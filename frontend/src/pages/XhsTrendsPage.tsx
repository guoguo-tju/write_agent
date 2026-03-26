import React, { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Loader2, RefreshCw } from "lucide-react";

import { AppTopNav } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  getXhsTrendCategories,
  getXhsTrends,
  refreshXhsTrends,
  streamXhsTrendAnalysis,
  type XhsTrendAnalysisStreamCallbacks,
} from "../services/api";
import type {
  XhsTrendAnalysisDone,
  XhsTrendCategory,
  XhsTrendItem,
  XhsTrendListResponse,
} from "../types";
import "./XhsTrendsPage.css";

type SortMode = "hot" | "latest";
type FeedbackKind = "info" | "success" | "error";
type FeedbackState = {
  kind: FeedbackKind;
  message: string;
};

const LAST_CATEGORY_KEY = "xhs_trends_last_category";
const PREFETCH_POLL_INTERVAL_MS = 5000;
const PREFETCH_MAX_POLLS = 36;

const formatDateTime = (value: string, locale: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString(locale);
};

const extractTraceId = (message: string): string => {
  const matched = message.match(/trace_id=([a-zA-Z0-9\-]+)/);
  return matched?.[1] || "";
};

const normalizeType = (value: string): "video" | "image_text" => {
  if (value === "video") {
    return "video";
  }
  return "image_text";
};

const safeExternalUrl = (value: string): string => {
  const text = (value || "").trim();
  if (!text) {
    return "";
  }
  try {
    const parsed = new URL(text);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.toString();
    }
  } catch {
    return "";
  }
  return "";
};

const CONTENT_PREVIEW_LIMIT = 96;

const toContentPreview = (value: string): string => {
  const text = (value || "").trim();
  if (!text) {
    return "--";
  }
  if (text.length <= CONTENT_PREVIEW_LIMIT) {
    return text;
  }
  return `${text.slice(0, CONTENT_PREVIEW_LIMIT).trimEnd()}…`;
};

export const XhsTrendsPage: React.FC = () => {
  const { lang, text } = useLanguage();
  const xhsText = text.xhsTrends;
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const tf = (template: string, vars: Record<string, string | number>) =>
    formatMessage(template, vars);

  const [categories, setCategories] = useState<XhsTrendCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("hot");
  const [trends, setTrends] = useState<XhsTrendListResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isPrefetching, setIsPrefetching] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);

  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState("");
  const [analysisError, setAnalysisError] = useState("");
  const [analysisTraceId, setAnalysisTraceId] = useState("");
  const [analysisData, setAnalysisData] = useState<XhsTrendAnalysisDone | null>(null);
  const [traceCopied, setTraceCopied] = useState(false);
  const analysisSourceRef = useRef<EventSource | null>(null);
  const prefetchStartedRef = useRef(false);
  const prefetchPollTokenRef = useRef(0);
  const trendsRequestSeqRef = useRef(0);

  const selectedCategoryLabel = useMemo(() => {
    return categories.find((item) => item.key === selectedCategory)?.name || "";
  }, [categories, selectedCategory]);

  const closeAnalysisSource = () => {
    if (analysisSourceRef.current) {
      analysisSourceRef.current.close();
      analysisSourceRef.current = null;
    }
  };

  const clearAnalysis = () => {
    closeAnalysisSource();
    setAnalysisLoading(false);
    setAnalysisProgress("");
    setAnalysisError("");
    setAnalysisTraceId("");
    setAnalysisData(null);
    setTraceCopied(false);
  };

  const nextTrendsRequestSeq = () => {
    trendsRequestSeqRef.current += 1;
    return trendsRequestSeqRef.current;
  };

  const loadTrends = async (
    categoryKey: string,
    sort: SortMode,
    showLoading: boolean,
    requestSeq: number,
  ): Promise<XhsTrendListResponse | null> => {
    if (showLoading) {
      setIsLoading(true);
    }
    try {
      const payload = await getXhsTrends(categoryKey, sort, 10);
      if (requestSeq !== trendsRequestSeqRef.current) {
        return null;
      }
      setTrends(payload);
      setFeedback(null);
      return payload;
    } catch (error) {
      if (requestSeq !== trendsRequestSeqRef.current) {
        return null;
      }
      const message = error instanceof Error ? error.message : String(error);
      setTrends(null);
      setFeedback({ kind: "error", message: xhsText.loadFailed });
      setAnalysisError(message);
      return null;
    } finally {
      if (showLoading && requestSeq === trendsRequestSeqRef.current) {
        setIsLoading(false);
      }
    }
  };

  const startAnalysis = (categoryKey: string) => {
    if (!categoryKey) {
      return;
    }
    closeAnalysisSource();
    setAnalysisLoading(true);
    setAnalysisProgress("");
    setAnalysisError("");
    setAnalysisTraceId("");
    setAnalysisData(null);
    setTraceCopied(false);

    const callbacks: XhsTrendAnalysisStreamCallbacks = {
      onStart: () => {
        setAnalysisProgress(xhsText.analysisLoading);
      },
      onProgress: (event) => {
        setAnalysisProgress(event.message || xhsText.analysisLoading);
      },
      onDone: (payload) => {
        setAnalysisLoading(false);
        setAnalysisProgress("");
        setAnalysisData(payload);
      },
      onError: (message, traceId) => {
        setAnalysisLoading(false);
        setAnalysisProgress("");
        setAnalysisError(message || xhsText.analysisFailed);
        setAnalysisTraceId(traceId || extractTraceId(message));
      },
    };

    analysisSourceRef.current = streamXhsTrendAnalysis(categoryKey, callbacks);
  };

  const ensureCategoryPrefetched = async (
    categoryKey: string,
    sort: SortMode,
    requestSeq: number,
  ) => {
    if (!categoryKey) {
      return;
    }
    if (requestSeq !== trendsRequestSeqRef.current) {
      return;
    }
    if (!prefetchStartedRef.current) {
      setFeedback({ kind: "info", message: xhsText.prefetching });
      setIsPrefetching(true);
      try {
        await refreshXhsTrends(categoryKey, { background: true, timeoutMs: 15000 });
        if (requestSeq !== trendsRequestSeqRef.current) {
          return;
        }
        prefetchStartedRef.current = true;
      } catch (error) {
        if (requestSeq !== trendsRequestSeqRef.current) {
          return;
        }
        setIsPrefetching(false);
        setFeedback({
          kind: "error",
          message: error instanceof Error ? error.message : xhsText.refreshFailed,
        });
        return;
      }
    }

    clearAnalysis();
    const token = prefetchPollTokenRef.current + 1;
    prefetchPollTokenRef.current = token;
    setIsPrefetching(true);

    for (let attempt = 0; attempt < PREFETCH_MAX_POLLS; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, PREFETCH_POLL_INTERVAL_MS));
      if (prefetchPollTokenRef.current !== token || requestSeq !== trendsRequestSeqRef.current) {
        return;
      }

      const payload = await loadTrends(categoryKey, sort, false, requestSeq);
      if (!payload) {
        continue;
      }
      if (payload.items?.length) {
        setIsPrefetching(false);
        setFeedback({ kind: "success", message: xhsText.prefetchReady });
        startAnalysis(categoryKey);
        return;
      }
      if (payload.fetch_error) {
        setIsPrefetching(false);
        setFeedback({ kind: "error", message: `${xhsText.refreshFailed}（${payload.fetch_error}）` });
        return;
      }
    }

    if (prefetchPollTokenRef.current === token) {
      setIsPrefetching(false);
      setFeedback({ kind: "info", message: xhsText.prefetchTimeout });
    }
  };

  useEffect(() => {
    void (async () => {
      try {
        const result = await getXhsTrendCategories();
        setCategories(result);

        const storedCategory = localStorage.getItem(LAST_CATEGORY_KEY) || "";
        const defaultCategory = result.find((item) => item.key === storedCategory)
          ? storedCategory
          : result[0]?.key || "";

        setSelectedCategory(defaultCategory);
        if (defaultCategory) {
          const requestSeq = nextTrendsRequestSeq();
          const payload = await loadTrends(defaultCategory, "hot", true, requestSeq);
          if (payload?.items?.length) {
            startAnalysis(defaultCategory);
          } else {
            await ensureCategoryPrefetched(defaultCategory, "hot", requestSeq);
          }
        } else {
          setIsLoading(false);
        }
      } catch (error) {
        setIsLoading(false);
        setFeedback({
          kind: "error",
          message: error instanceof Error ? error.message : xhsText.loadFailed,
        });
      }
    })();

    return () => {
      prefetchPollTokenRef.current += 1;
      closeAnalysisSource();
    };
  }, []);

  useEffect(() => {
    if (!selectedCategory) {
      return;
    }
    localStorage.setItem(LAST_CATEGORY_KEY, selectedCategory);
  }, [selectedCategory]);

  const handleCategoryChange = async (nextCategory: string) => {
    const requestSeq = nextTrendsRequestSeq();
    prefetchPollTokenRef.current += 1;
    setIsPrefetching(false);
    clearAnalysis();
    setSelectedCategory(nextCategory);
    const payload = await loadTrends(nextCategory, sortMode, true, requestSeq);
    if (payload?.items?.length) {
      startAnalysis(nextCategory);
      return;
    }
    await ensureCategoryPrefetched(nextCategory, sortMode, requestSeq);
  };

  const handleSortChange = async (nextSort: SortMode) => {
    const requestSeq = nextTrendsRequestSeq();
    prefetchPollTokenRef.current += 1;
    setIsPrefetching(false);
    clearAnalysis();
    setSortMode(nextSort);
    if (!selectedCategory) {
      return;
    }
    const payload = await loadTrends(selectedCategory, nextSort, true, requestSeq);
    if (payload?.items?.length) {
      return;
    }
    await ensureCategoryPrefetched(selectedCategory, nextSort, requestSeq);
  };

  const handleRefresh = async () => {
    if (!selectedCategory || isRefreshing || isPrefetching) {
      return;
    }
    setIsRefreshing(true);
    try {
      const requestSeq = nextTrendsRequestSeq();
      prefetchPollTokenRef.current += 1;
      setIsPrefetching(false);
      const result = await refreshXhsTrends(selectedCategory, { timeoutMs: 240000 });
      const payload = await loadTrends(selectedCategory, sortMode, false, requestSeq);
      if (payload?.items?.length) {
        startAnalysis(selectedCategory);
      } else {
        clearAnalysis();
      }
      const refreshError = result.errors?.[selectedCategory];
      if (refreshError) {
        setFeedback({ kind: "error", message: `${xhsText.refreshFailed}（${refreshError}）` });
      } else {
        setFeedback({ kind: "success", message: xhsText.refreshSuccess });
      }
    } catch (error) {
      setFeedback({
        kind: "error",
        message: error instanceof Error ? error.message : xhsText.refreshFailed,
      });
    } finally {
      setIsRefreshing(false);
    }
  };

  const copyTraceId = async () => {
    if (!analysisTraceId) {
      return;
    }
    try {
      await navigator.clipboard.writeText(analysisTraceId);
      setTraceCopied(true);
      setTimeout(() => setTraceCopied(false), 1200);
    } catch {
      setTraceCopied(false);
    }
  };

  return (
    <div className="xhs-trends-page">
      <AppTopNav />

      <main className="xhs-trends-main">
        <section className="xhs-trends-header">
          <div>
            <h1>{xhsText.title}</h1>
            <p>{xhsText.subtitle}</p>
          </div>

          <div className="xhs-trends-controls">
            <label className="xhs-trends-select">
              <span>{xhsText.categoryLabel}</span>
              <select
                value={selectedCategory}
                onChange={(event) => {
                  void handleCategoryChange(event.target.value);
                }}
                disabled={!categories.length}
              >
                {categories.map((category) => (
                  <option key={category.key} value={category.key}>
                    {lang === "zh" ? category.name : category.name_en}
                  </option>
                ))}
              </select>
            </label>

            <label className="xhs-trends-select">
              <span>{xhsText.sortLabel}</span>
              <select
                value={sortMode}
                onChange={(event) => {
                  void handleSortChange(event.target.value as SortMode);
                }}
              >
                <option value="hot">{xhsText.sortHot}</option>
                <option value="latest">{xhsText.sortLatest}</option>
              </select>
            </label>

            <button
              type="button"
              className="xhs-trends-secondary-btn"
              onClick={() => {
                void handleRefresh();
              }}
              disabled={!selectedCategory || isRefreshing || isPrefetching}
            >
              {isRefreshing ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              {isRefreshing ? xhsText.refreshing : xhsText.refresh}
            </button>
          </div>
        </section>

        <section className="xhs-trends-meta">
          {trends?.updated_at && (
            <span>{tf(xhsText.updatedAt, { time: formatDateTime(trends.updated_at, locale) })}</span>
          )}
          {trends?.is_stale && <span className="warn">{xhsText.staleNotice}</span>}
          {trends?.fetch_error && (
            <span className="warn">{tf(xhsText.fetchError, { error: trends.fetch_error })}</span>
          )}
        </section>

        {feedback && <section className={`xhs-trends-feedback ${feedback.kind}`}>{feedback.message}</section>}

        <section className="xhs-trends-table-wrap">
          {isLoading ? (
            <div className="xhs-trends-loading">
              <Loader2 size={16} className="spin" />
              <span>{text.home.loading}</span>
            </div>
          ) : !trends?.items?.length ? (
            <div className="xhs-trends-empty">{isPrefetching ? xhsText.prefetching : xhsText.noData}</div>
          ) : (
            <table className="xhs-trends-table">
              <thead>
                <tr>
                  <th>{xhsText.titleCol}</th>
                  <th>{xhsText.contentCol}</th>
                  <th>{xhsText.contentType}</th>
                  <th>{xhsText.likeCount}</th>
                  <th>{xhsText.favoriteCount}</th>
                  <th>{xhsText.commentCount}</th>
                  <th>{xhsText.publishTime}</th>
                  <th>{xhsText.hotScore}</th>
                  <th>{xhsText.sourceLink}</th>
                </tr>
              </thead>
              <tbody>
                {trends.items.map((item: XhsTrendItem) => {
                  const typeKey = normalizeType(item.content_type);
                  const safeUrl = safeExternalUrl(item.source_url);
                  const fullContent = (item.content || item.title || "").trim();
                  const previewContent = toContentPreview(fullContent);
                  const hasMoreContent = fullContent.length > CONTENT_PREVIEW_LIMIT;
                  return (
                    <tr key={`${item.id || item.title}-${item.publish_time}`}>
                      <td className="title-cell">
                        <div title={item.title}>{item.title}</div>
                      </td>
                      <td className="content-cell">
                        {fullContent ? (
                          <div
                            className={`xhs-content-preview${hasMoreContent ? " has-more" : ""}`}
                            title={hasMoreContent ? undefined : fullContent}
                            tabIndex={hasMoreContent ? 0 : -1}
                          >
                            <span>{previewContent}</span>
                            {hasMoreContent && <div className="xhs-content-popover">{fullContent}</div>}
                          </div>
                        ) : (
                          "--"
                        )}
                      </td>
                      <td>{typeKey === "video" ? xhsText.typeVideo : xhsText.typeImageText}</td>
                      <td>{item.like_count}</td>
                      <td>{item.favorite_count}</td>
                      <td>{item.comment_count}</td>
                      <td>{formatDateTime(item.publish_time, locale)}</td>
                      <td>{item.hot_score.toFixed(1)}</td>
                      <td>
                        {safeUrl ? (
                          <a href={safeUrl} target="_blank" rel="noreferrer">
                            {xhsText.openSource}
                            <ExternalLink size={12} />
                          </a>
                        ) : (
                          "--"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>

        <section className="xhs-analysis">
          <div className="xhs-analysis-header">
            <h2>
              {xhsText.analysisTitle}
              {selectedCategoryLabel ? ` · ${selectedCategoryLabel}` : ""}
            </h2>
          </div>

          {analysisLoading && (
            <div className="xhs-analysis-loading">
              <Loader2 size={16} className="spin" />
              <span>{analysisProgress || xhsText.analysisLoading}</span>
            </div>
          )}

          {analysisError && !analysisLoading && (
            <div className="xhs-analysis-error">
              <div>{analysisError}</div>
              {analysisTraceId && (
                <div className="xhs-trace-row">
                  <span>{tf(xhsText.traceIdLabel, { traceId: analysisTraceId })}</span>
                  <button type="button" onClick={() => void copyTraceId()}>
                    {traceCopied ? text.home.statusCompleted : text.home.copy}
                  </button>
                </div>
              )}
            </div>
          )}

          {analysisData && !analysisLoading && !analysisError && (
            <div className="xhs-analysis-grid">
              <article className="xhs-analysis-card">
                <h3>{xhsText.analysisReason}</h3>
                <ul>
                  {analysisData.reason_points.map((item, index) => (
                    <li key={`${item}-${index}`}>{item}</li>
                  ))}
                </ul>
              </article>

              <article className="xhs-analysis-card">
                <h3>{xhsText.analysisComments}</h3>
                <ul>
                  {analysisData.comment_topics.map((topic, index) => (
                    <li key={`${topic.topic}-${index}`}>
                      <strong>{topic.topic}</strong>
                      <span>{xhsText.ratioLabel}: {topic.ratio}</span>
                      <p>{xhsText.sampleCommentLabel}: {topic.sample_comment}</p>
                    </li>
                  ))}
                </ul>
              </article>

              <article className="xhs-analysis-card">
                <h3>{xhsText.analysisInspiration}</h3>
                <ul>
                  {analysisData.inspiration_cards.map((card, index) => (
                    <li key={`${card.topic}-${index}`}>
                      <strong>{card.topic}</strong>
                      <span>{xhsText.contentType}: {card.content_type === "video" ? xhsText.typeVideo : xhsText.typeImageText}</span>
                      <p>{xhsText.hookLabel}: {card.title_hook}</p>
                      <p>{xhsText.rationaleLabel}: {card.rationale}</p>
                    </li>
                  ))}
                </ul>
              </article>
            </div>
          )}
        </section>
      </main>
    </div>
  );
};
