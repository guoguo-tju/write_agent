import React, { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { AppTopNav } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  addLinuxDoTrendItemToMaterials,
  buildLinuxDoTrendItemRewrite,
  getLinuxDoTrendPeriods,
  getLinuxDoTrends,
  refreshLinuxDoTrends,
  type LinuxDoTrendItem,
  type LinuxDoTrendPeriodOption,
  type LinuxDoTrendSnapshot,
} from "../services/api";
import "./LinuxDoTrendsPage.css";

type PeriodType = "weekly" | "monthly";
type FeedbackKind = "info" | "success" | "error";
type FeedbackState = {
  kind: FeedbackKind;
  message: string;
  materialId?: number;
};

const ALL_TAG = "__all__";
const PAGE_LIMIT = 20;
const CONTENT_PREVIEW_LIMIT = 140;

const formatDateTime = (value: string, locale: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString(locale);
};

const safeExternalUrl = (value?: string): string => {
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

const splitTags = (tags?: string[] | string): string[] => {
  if (!tags) {
    return [];
  }
  if (Array.isArray(tags)) {
    return tags.map((tag) => tag.trim()).filter(Boolean);
  }
  return tags
    .split(/[,，\s]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
};

const trimContent = (value: string, maxLength: number) => {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trimEnd()}…`;
};

const extractApiErrorDetail = (error: unknown): string => {
  const maybeAxios = error as {
    response?: {
      data?: {
        detail?: unknown;
      };
    };
  };
  const detail = maybeAxios?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (error instanceof Error && error.message.trim()) {
    if (!/status code \d+/i.test(error.message)) {
      return error.message.trim();
    }
  }
  return "";
};

const getPreviewText = (item: LinuxDoTrendItem): string => {
  const raw =
    item.summary?.trim() ||
    item.content_excerpt?.trim() ||
    item.excerpt?.trim() ||
    item.content?.trim() ||
    "";
  return raw ? trimContent(raw, CONTENT_PREVIEW_LIMIT) : "--";
};

const resolvePeriodKey = (
  periods: LinuxDoTrendPeriodOption[],
  preferredPeriodKey?: string,
): string => {
  if (preferredPeriodKey) {
    const matched = periods.find((item) => item.period_key === preferredPeriodKey);
    if (matched) {
      return matched.period_key;
    }
  }
  return periods[0]?.period_key || preferredPeriodKey || "";
};

const isTouchMode = () =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(hover: none)").matches;

export const LinuxDoTrendsPage: React.FC = () => {
  const navigate = useNavigate();
  const { lang, text } = useLanguage();
  const linuxdoText = text.linuxdoTrends;
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const tf = (template: string, vars: Record<string, string | number>) =>
    formatMessage(template, vars);

  const [periodType, setPeriodType] = useState<PeriodType>("weekly");
  const [periods, setPeriods] = useState<LinuxDoTrendPeriodOption[]>([]);
  const [selectedPeriodKey, setSelectedPeriodKey] = useState("");
  const [selectedTag, setSelectedTag] = useState(ALL_TAG);
  const [snapshot, setSnapshot] = useState<LinuxDoTrendSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [rowActionKey, setRowActionKey] = useState<string | null>(null);
  const [activeSummaryTopicId, setActiveSummaryTopicId] = useState<number | null>(null);
  const dataRequestSeqRef = useRef(0);

  const availableTags = useMemo(() => {
    const tagSet = new Set<string>();
    snapshot?.available_tags?.forEach((tag) => tagSet.add(tag.trim()));
    snapshot?.items?.forEach((item) => {
      splitTags(item.tags).forEach((tag) => tagSet.add(tag));
    });
    return [ALL_TAG, ...Array.from(tagSet).filter(Boolean).sort((left, right) => left.localeCompare(right, locale))];
  }, [locale, snapshot?.available_tags, snapshot?.items]);

  const visibleTag = availableTags.includes(selectedTag) ? selectedTag : ALL_TAG;
  const effectivePeriodKey = snapshot?.period_key || selectedPeriodKey;

  const nextDataRequestSeq = () => {
    dataRequestSeqRef.current += 1;
    return dataRequestSeqRef.current;
  };

  const loadOverview = async (
    nextPeriodType: PeriodType,
    preferredPeriodKey?: string,
    requestedTag = selectedTag,
  ) => {
    const requestSeq = nextDataRequestSeq();
    setIsLoading(true);
    setFeedback(null);
    setActiveSummaryTopicId(null);
    try {
      const periodList = await getLinuxDoTrendPeriods(nextPeriodType);

      if (requestSeq !== dataRequestSeqRef.current) {
        return;
      }

      setPeriods(periodList);
      const resolvedPeriodKey = resolvePeriodKey(periodList, preferredPeriodKey);
      setSelectedPeriodKey(resolvedPeriodKey);
      const snapshotData = await getLinuxDoTrends({
        periodType: nextPeriodType,
        periodKey: resolvedPeriodKey || undefined,
        tag: requestedTag === ALL_TAG ? undefined : requestedTag,
        limit: PAGE_LIMIT,
      });
      if (requestSeq !== dataRequestSeqRef.current) {
        return;
      }
      setSnapshot(snapshotData);
      setFeedback(null);
    } catch (error) {
      if (requestSeq !== dataRequestSeqRef.current) {
        return;
      }
      console.error("加载 Linux.do 趋势失败:", error);
      setSnapshot(null);
      const detail = extractApiErrorDetail(error);
      setFeedback({
        kind: "error",
        message: detail ? `${linuxdoText.loadFailed}（${detail}）` : linuxdoText.loadFailed,
      });
    } finally {
      if (requestSeq === dataRequestSeqRef.current) {
        setIsLoading(false);
      }
    }
  };

  const loadSnapshot = async (
    nextPeriodType: PeriodType,
    nextPeriodKey: string,
    nextTag = selectedTag,
    options: { keepLoading?: boolean } = {},
  ) => {
    const requestSeq = nextDataRequestSeq();
    if (options.keepLoading ?? true) {
      setIsLoading(true);
    }
    setActiveSummaryTopicId(null);
    try {
      const snapshotData = await getLinuxDoTrends({
        periodType: nextPeriodType,
        periodKey: nextPeriodKey || undefined,
        tag: nextTag === ALL_TAG ? undefined : nextTag,
        limit: PAGE_LIMIT,
      });
      if (requestSeq !== dataRequestSeqRef.current) {
        return;
      }
      setSnapshot(snapshotData);
      setFeedback(null);
    } catch (error) {
      if (requestSeq !== dataRequestSeqRef.current) {
        return;
      }
      console.error("加载 Linux.do 趋势快照失败:", error);
      setSnapshot(null);
      const detail = extractApiErrorDetail(error);
      setFeedback({
        kind: "error",
        message: detail ? `${linuxdoText.loadFailed}（${detail}）` : linuxdoText.loadFailed,
      });
    } finally {
      if ((options.keepLoading ?? true) && requestSeq === dataRequestSeqRef.current) {
        setIsLoading(false);
      }
    }
  };

  useEffect(() => {
    void loadOverview(periodType, selectedPeriodKey, selectedTag);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodType]);

  useEffect(() => {
    if (activeSummaryTopicId == null) {
      return;
    }
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target?.closest(".linuxdo-summary-preview")) {
        setActiveSummaryTopicId(null);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [activeSummaryTopicId]);

  const handlePeriodKeyChange = async (nextPeriodKey: string) => {
    setSelectedPeriodKey(nextPeriodKey);
    await loadSnapshot(periodType, nextPeriodKey, selectedTag);
  };

  const handleTagChange = async (nextTag: string) => {
    setSelectedTag(nextTag);
    await loadSnapshot(periodType, selectedPeriodKey, nextTag);
  };

  const handleRefresh = async () => {
    if (isRefreshing) {
      setFeedback({ kind: "info", message: linuxdoText.refreshingLocked });
      return;
    }
    setIsRefreshing(true);
    try {
      const refreshed = await refreshLinuxDoTrends(periodType);
      const resolvedKey = refreshed.period_key || selectedPeriodKey;
      if (resolvedKey) {
        setSelectedPeriodKey(resolvedKey);
      }
      await loadOverview(periodType, resolvedKey || selectedPeriodKey, selectedTag);
      setFeedback({ kind: "success", message: linuxdoText.refreshSuccess });
    } catch (error) {
      console.error("刷新 Linux.do 趋势失败:", error);
      const detail = extractApiErrorDetail(error);
      setFeedback({
        kind: "error",
        message: detail ? `${linuxdoText.refreshFailed}（${detail}）` : linuxdoText.refreshFailed,
      });
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleAddItem = async (item: LinuxDoTrendItem) => {
    const topicId = Number(item.topic_id);
    setRowActionKey(`add-${topicId}`);
    try {
      const result = await addLinuxDoTrendItemToMaterials(periodType, effectivePeriodKey, topicId);
      setFeedback({
        kind: result.created ? "success" : "info",
        message: result.created
          ? linuxdoText.addSuccess
          : result.updated
            ? linuxdoText.addSuccessUpdated
            : linuxdoText.addSuccessExisting,
        materialId: result.material_id,
      });
    } catch (error) {
      console.error("Linux.do 条目入素材失败:", error);
      setFeedback({ kind: "error", message: linuxdoText.addFailed });
    } finally {
      setRowActionKey(null);
    }
  };

  const handleRewriteItem = async (item: LinuxDoTrendItem) => {
    const topicId = Number(item.topic_id);
    setRowActionKey(`rewrite-${topicId}`);
    try {
      const result = await buildLinuxDoTrendItemRewrite(periodType, effectivePeriodKey, topicId);
      const prefillSource = result.content?.trim();
      if (!prefillSource) {
        setFeedback({ kind: "error", message: linuxdoText.rewriteBuildFailed });
        return;
      }
      setFeedback({ kind: "success", message: linuxdoText.rewriteSuccess });
      navigate("/", {
        state: {
          prefillSource,
          sourceType: "linuxdo-trend-item",
          prefillTitle: result.title || item.title,
        },
      });
    } catch (error) {
      console.error("Linux.do 改写输入构建失败:", error);
      setFeedback({ kind: "error", message: linuxdoText.rewriteBuildFailed });
    } finally {
      setRowActionKey(null);
    }
  };

  const selectedPeriodOption = periods.find((item) => item.period_key === selectedPeriodKey) || null;
  const currentItems = snapshot?.items || [];

  return (
    <div className="linuxdo-trends-page">
      <AppTopNav />

      <main className="linuxdo-trends-main">
        <section className="linuxdo-trends-header">
          <div>
            <h1>{linuxdoText.title}</h1>
            <p>{linuxdoText.subtitle}</p>
          </div>

          <div className="linuxdo-trends-controls">
            <div className="linuxdo-trends-segment" role="group" aria-label={linuxdoText.periodLabel}>
              <button
                type="button"
                className={periodType === "weekly" ? "active" : ""}
                onClick={() => {
                  setSelectedTag(ALL_TAG);
                  setPeriodType("weekly");
                }}
              >
                {linuxdoText.periodWeekly}
              </button>
              <button
                type="button"
                className={periodType === "monthly" ? "active" : ""}
                onClick={() => {
                  setSelectedTag(ALL_TAG);
                  setPeriodType("monthly");
                }}
              >
                {linuxdoText.periodMonthly}
              </button>
            </div>

            <label className="linuxdo-trends-select">
              <span>{linuxdoText.periodKeyLabel}</span>
              <select
                value={selectedPeriodKey}
                onChange={(event) => {
                  void handlePeriodKeyChange(event.target.value);
                }}
                disabled={!periods.length}
              >
                {periods.map((item) => (
                  <option key={item.period_key} value={item.period_key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="linuxdo-trends-select">
              <span>{linuxdoText.tagLabel}</span>
              <select
                value={visibleTag}
                onChange={(event) => {
                  void handleTagChange(event.target.value);
                }}
              >
                {availableTags.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag === ALL_TAG ? linuxdoText.allTags : tag}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className="linuxdo-trends-secondary-btn"
              onClick={() => {
                void handleRefresh();
              }}
              disabled={isRefreshing || isLoading || snapshot?.is_refreshing}
            >
              {isRefreshing ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              {isRefreshing ? linuxdoText.refreshing : linuxdoText.refresh}
            </button>
          </div>
        </section>

        <section className="linuxdo-trends-meta">
          {snapshot?.updated_at && (
            <span>{tf(linuxdoText.updatedAt, { time: formatDateTime(snapshot.updated_at, locale) })}</span>
          )}
          {selectedPeriodOption?.label && <span>{selectedPeriodOption.label}</span>}
          {snapshot?.is_stale && <span className="warn">{linuxdoText.staleNotice}</span>}
          {snapshot?.fetch_error && (
            <span className="warn">{tf(linuxdoText.fetchError, { error: snapshot.fetch_error })}</span>
          )}
        </section>

        {feedback && (
          <section className={`linuxdo-trends-feedback ${feedback.kind}`}>
            <span>{feedback.message}</span>
            {feedback.materialId ? (
              <button
                type="button"
                className="linuxdo-trends-feedback-link"
                onClick={() => navigate(`/materials?material_id=${feedback.materialId}`)}
              >
                {linuxdoText.viewMaterialDetail}
              </button>
            ) : null}
          </section>
        )}

        <section className="linuxdo-trends-table-wrap">
          {isLoading ? (
            <div className="linuxdo-trends-loading">
              <Loader2 size={16} className="spin" />
              <span>{text.home.loading}</span>
            </div>
          ) : !currentItems.length ? (
            <div className="linuxdo-trends-empty">{linuxdoText.noData}</div>
          ) : (
            <table className="linuxdo-trends-table">
              <thead>
                <tr>
                  <th>{linuxdoText.titleCol}</th>
                  <th>{linuxdoText.summaryCol}</th>
                  <th>{linuxdoText.authorCol}</th>
                  <th>{linuxdoText.tagsCol}</th>
                  <th>{linuxdoText.repliesCol}</th>
                  <th>{linuxdoText.publishTime}</th>
                  <th>{linuxdoText.sourceLink}</th>
                  <th>{linuxdoText.actions}</th>
                </tr>
              </thead>
              <tbody>
                {currentItems.map((item) => {
                  const topicId = Number(item.topic_id);
                  const rowBusy =
                    rowActionKey === `add-${topicId}` || rowActionKey === `rewrite-${topicId}`;
                  const addBusy = rowActionKey === `add-${topicId}`;
                  const rewriteBusy = rowActionKey === `rewrite-${topicId}`;
                  const safeUrl = safeExternalUrl(item.source_url);
                  const summaryRaw =
                    item.summary?.trim() ||
                    item.content_excerpt?.trim() ||
                    item.excerpt?.trim() ||
                    item.content?.trim() ||
                    "";
                  const contentPreview = summaryRaw ? getPreviewText(item) : "--";
                  const summaryExpanded = activeSummaryTopicId === topicId;
                  const tagText = splitTags(item.tags).join(" · ") || "--";
                  return (
                    <tr key={`${topicId}-${item.title}`}>
                      <td className="title-cell">
                        <div title={item.title}>{item.title}</div>
                      </td>
                      <td className="summary-cell">
                        {summaryRaw ? (
                          <div
                            className={`linuxdo-summary-preview${summaryExpanded ? " mobile-open" : ""}`}
                            tabIndex={0}
                            role="button"
                            aria-expanded={summaryExpanded}
                            aria-label={linuxdoText.summaryCol}
                            onClick={(event) => {
                              if (!isTouchMode()) {
                                return;
                              }
                              event.stopPropagation();
                              setActiveSummaryTopicId((prev) => (prev === topicId ? null : topicId));
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                setActiveSummaryTopicId((prev) => (prev === topicId ? null : topicId));
                              }
                              if (event.key === "Escape") {
                                setActiveSummaryTopicId(null);
                              }
                            }}
                          >
                            <span>{contentPreview}</span>
                            <div className="linuxdo-summary-popover" onClick={(event) => event.stopPropagation()}>
                              <div className="linuxdo-summary-popover-text">{summaryRaw}</div>
                            </div>
                          </div>
                        ) : (
                          "--"
                        )}
                      </td>
                      <td>{item.author || "--"}</td>
                      <td>{tagText}</td>
                      <td>{item.replies_count ?? 0}</td>
                      <td>{formatDateTime(item.publish_time || item.created_at || "", locale)}</td>
                      <td>
                        {safeUrl ? (
                          <a href={safeUrl} target="_blank" rel="noreferrer">
                            {linuxdoText.openSource}
                            <ExternalLink size={12} />
                          </a>
                        ) : (
                          "--"
                        )}
                      </td>
                      <td>
                        <div className="linuxdo-trends-row-actions">
                          <button
                            type="button"
                            className="linuxdo-trends-secondary-btn"
                            disabled={rowBusy}
                            onClick={() => {
                              void handleAddItem(item);
                            }}
                          >
                            {addBusy ? (
                              <>
                                <Loader2 size={14} className="spin" />
                                {text.home.loading}
                              </>
                            ) : (
                              linuxdoText.addMaterial
                            )}
                          </button>
                          <button
                            type="button"
                            className="linuxdo-trends-primary-btn"
                            disabled={rowBusy}
                            onClick={() => {
                              void handleRewriteItem(item);
                            }}
                          >
                            {rewriteBusy ? (
                              <>
                                <Loader2 size={14} className="spin" />
                                {text.home.loading}
                              </>
                            ) : (
                              <>
                                <Sparkles size={14} />
                                {linuxdoText.goRewrite}
                              </>
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
      </main>
    </div>
  );
};
