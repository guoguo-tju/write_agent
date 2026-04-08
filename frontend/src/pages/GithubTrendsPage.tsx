import React, { useEffect, useMemo, useState } from "react";
import { ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { AppTopNav } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  addGithubTrendItemToMaterials,
  buildGithubTrendItemRewrite,
  getGithubTrendPeriods,
  getGithubTrendWeeks,
  getGithubTrends,
  refreshGithubTrends,
  type GithubTrendEnrichMeta,
  type GithubTrendItem,
  type GithubTrendPeriodOption,
  type GithubTrendSnapshot,
  type GithubTrendWeekOption,
} from "../services/api";
import "./GithubTrendsPage.css";

type FeedbackKind = "info" | "success" | "error";
type FeedbackState = {
  kind: FeedbackKind;
  message: string;
  materialId?: number;
};

type TrendScope = "daily" | "weekly";

const calcCurrentWeekKey = () => {
  const now = new Date();
  const target = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  const day = target.getUTCDay() || 7;
  target.setUTCDate(target.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((target.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  return `${target.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
};

const calcCurrentDayKey = () => {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};

const formatDateTime = (value: string, locale: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString(locale);
};

const TRANSLATION_PENDING_FALLBACK = "该项目英文简介暂未完成中文翻译，请稍后重试。";

const hasChineseChars = (value: string): boolean => /[\u4e00-\u9fff]/.test(value);

const pickDescription = (item: GithubTrendItem, lang: "zh" | "en"): string => {
  const original = item.description?.trim() || "";
  const translated = item.description_zh?.trim() || "";
  const hasChinese = hasChineseChars(original);

  if (lang === "zh") {
    if (translated) {
      return translated;
    }
    if (!original) {
      return "暂无简介";
    }
    return hasChinese ? original : TRANSLATION_PENDING_FALLBACK;
  }
  return original || translated || "No description";
};

const needsTranslationRetry = (item: GithubTrendItem): boolean => {
  const original = item.description?.trim() || "";
  const translated = item.description_zh?.trim() || "";
  if (!original) {
    return false;
  }
  if (translated === TRANSLATION_PENDING_FALLBACK) {
    return true;
  }
  if (hasChineseChars(translated)) {
    return false;
  }
  if (hasChineseChars(original)) {
    return translated !== original;
  }
  return true;
};

const markdownForDigest = (scope: TrendScope, periodKey: string, items: GithubTrendItem[]) => {
  const titlePrefix = scope === "daily" ? "GitHub 日榜 Top10" : "GitHub 周榜 Top10";
  const starLabel = scope === "daily" ? "本日新增Star" : "本周新增Star";
  const lines = [
    `# ${titlePrefix}（${periodKey}）`,
    "",
    `| 排名 | 项目 | 作者 | ${starLabel} | 简介 | 链接 |`,
    "| --- | --- | --- | ---: | --- | --- |",
  ];

  items.forEach((item, index) => {
    const desc = pickDescription(item, "zh")
      .replace(/\|/g, "\\|")
      .replace(/\n/g, " ");
    lines.push(
      `| ${index + 1} | ${item.repo_full_name.replace(/\|/g, "\\|")} | ${item.owner.replace(/\|/g, "\\|")} | ${item.stars_this_week} | ${desc} | ${item.repo_url} |`,
    );
  });

  lines.push(
    "",
    "## 本周观察（可补充）",
    "- 哪些方向最值得跟进？",
    "- 适合做成什么类型的内容？",
    "",
    "## 改写提示（可补充）",
    "- 面向小白解释核心价值",
    "- 给出具体上手路径和注意事项",
  );

  return lines.join("\n");
};

export const GithubTrendsPage: React.FC = () => {
  const navigate = useNavigate();
  const { lang, text } = useLanguage();
  const trendsText = text.githubTrends;
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const tf = (template: string, vars: Record<string, string | number>) =>
    formatMessage(template, vars);

  const [trendScope, setTrendScope] = useState<TrendScope>("weekly");
  const [weeks, setWeeks] = useState<GithubTrendWeekOption[]>([]);
  const [days, setDays] = useState<GithubTrendPeriodOption[]>([]);
  const [selectedWeekKey, setSelectedWeekKey] = useState(calcCurrentWeekKey());
  const [selectedDayKey, setSelectedDayKey] = useState(calcCurrentDayKey());
  const [snapshot, setSnapshot] = useState<GithubTrendSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [rowActionKey, setRowActionKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [enhanceEnabled, setEnhanceEnabled] = useState(true);

  const effectivePeriodKey =
    trendScope === "daily"
      ? snapshot?.period_key || selectedDayKey
      : snapshot?.period_key || snapshot?.week_key || selectedWeekKey;

  const sortedItems = useMemo(() => {
    if (!snapshot?.items?.length) {
      return [];
    }
    return [...snapshot.items].sort((a, b) => {
      if (b.stars_this_week !== a.stars_this_week) {
        return b.stars_this_week - a.stars_this_week;
      }
      return a.rank - b.rank;
    });
  }, [snapshot?.items]);

  const weekOptions = useMemo(() => {
    const set = new Set<string>(weeks.map((item) => item.week_key));
    if (!set.has(selectedWeekKey)) {
      return [
        {
          week_key: selectedWeekKey,
          latest_snapshot_date: "",
          latest_captured_at: "",
          has_archive: false,
        },
        ...weeks,
      ];
    }
    return weeks;
  }, [selectedWeekKey, weeks]);

  const dayOptions = useMemo(() => {
    const set = new Set<string>(days.map((item) => item.period_key));
    if (!set.has(selectedDayKey)) {
      return [
        {
          period_type: "daily" as const,
          period_key: selectedDayKey,
          latest_snapshot_date: selectedDayKey,
          latest_captured_at: "",
          has_archive: false,
        },
        ...days,
      ];
    }
    return days;
  }, [days, selectedDayKey]);

  const loadWeeks = async () => {
    try {
      const result = await getGithubTrendWeeks();
      setWeeks(result);
      return result;
    } catch (error) {
      console.error("加载周列表失败:", error);
      return [] as GithubTrendWeekOption[];
    }
  };

  const loadDays = async () => {
    try {
      const result = await getGithubTrendPeriods("daily");
      setDays(result);
      return result;
    } catch (error) {
      console.error("加载日榜周期失败:", error);
      return [] as GithubTrendPeriodOption[];
    }
  };

  const loadSnapshot = async (scope: TrendScope, periodKey?: string) => {
    setIsLoading(true);
    try {
      const data = await getGithubTrends({
        periodType: scope,
        periodKey,
        weekKey: scope === "weekly" ? periodKey : undefined,
      });
      setSnapshot(data);
      setFeedback(null);
      if (scope === "weekly") {
        const requestedWeekKey =
          data.requested_period_key || data.requested_week_key || periodKey || data.week_key;
        if (requestedWeekKey) {
          setSelectedWeekKey(requestedWeekKey);
        }
      }
      if (scope === "daily") {
        const requestedDayKey = data.requested_period_key || periodKey || data.period_key;
        if (requestedDayKey) {
          setSelectedDayKey(requestedDayKey);
        }
      }
    } catch (error) {
      console.error("加载趋势数据失败:", error);
      setSnapshot(null);
      setFeedback({ kind: "error", message: trendsText.loadFailed });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void (async () => {
      await Promise.all([loadWeeks(), loadSnapshot("weekly", selectedWeekKey)]);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("github_trends_enhance_enabled");
      if (raw === "0") {
        setEnhanceEnabled(false);
      }
    } catch {
      // ignore localStorage read error
    }
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem("github_trends_enhance_enabled", enhanceEnabled ? "1" : "0");
    } catch {
      // ignore localStorage write error
    }
  }, [enhanceEnabled]);

  const enrichSuffix = (meta?: GithubTrendEnrichMeta): string => {
    if (!enhanceEnabled || !meta?.attempted) {
      return "";
    }
    if (meta.degraded) {
      if (meta.degrade_reason === "missing_github_token") {
        return `（${trendsText.enrichTokenMissing}）`;
      }
      return `（${trendsText.enrichDegradedContinue}）`;
    }
    if (meta.cache_hit) {
      return `（${trendsText.enrichCacheHit}）`;
    }
    return `（${trendsText.enrichFetched}）`;
  };

  const handleSelectWeek = async (weekKey: string) => {
    setSelectedWeekKey(weekKey);
    setTrendScope("weekly");
    await loadSnapshot("weekly", weekKey);
  };

  const handleSelectDay = async (dayKey: string) => {
    setSelectedDayKey(dayKey);
    setTrendScope("daily");
    await loadSnapshot("daily", dayKey);
  };

  const handleSelectScope = async (nextScope: TrendScope) => {
    if (nextScope === trendScope) {
      return;
    }
    setTrendScope(nextScope);
    setFeedback(null);

    if (nextScope === "daily") {
      const dailyPeriods = await loadDays();
      const resolvedDayKey =
        dailyPeriods.some((item) => item.period_key === selectedDayKey)
          ? selectedDayKey
          : dailyPeriods[0]?.period_key || selectedDayKey;
      setSelectedDayKey(resolvedDayKey);
      await loadSnapshot("daily", resolvedDayKey);
      return;
    }

    const weeklyPeriods = await loadWeeks();
    const resolvedWeekKey =
      weeklyPeriods.some((item) => item.week_key === selectedWeekKey)
        ? selectedWeekKey
        : weeklyPeriods[0]?.week_key || selectedWeekKey;
    setSelectedWeekKey(resolvedWeekKey);
    await loadSnapshot("weekly", resolvedWeekKey);
  };

  const handleRefresh = async () => {
    if (isRefreshing || snapshot?.is_refreshing) {
      setFeedback({ kind: "info", message: trendsText.refreshingLocked });
      return;
    }

    setIsRefreshing(true);
    try {
      const selectedPeriodKey = trendScope === "daily" ? selectedDayKey : selectedWeekKey;
      const data = await refreshGithubTrends({
        periodType: trendScope,
        periodKey: selectedPeriodKey,
        retryUntranslatedOnly: true,
      });
      setSnapshot(data);
      if (trendScope === "daily") {
        setSelectedDayKey(data.period_key || selectedDayKey);
        await loadDays();
      } else {
        setSelectedWeekKey(data.week_key);
        await loadWeeks();
      }
      const pendingCount = (data.items || []).filter((item) => needsTranslationRetry(item)).length;
      setFeedback({
        kind: pendingCount > 0 ? "info" : "success",
        message: pendingCount > 0
          ? tf(trendsText.refreshRetryPending, { count: pendingCount })
          : trendScope === "daily"
            ? trendsText.refreshSuccessDaily
            : trendsText.refreshSuccessWeekly,
      });
    } catch (error) {
      console.error("手动更新失败:", error);
      setFeedback({ kind: "error", message: trendsText.refreshFailed });
      await loadSnapshot(trendScope, trendScope === "daily" ? selectedDayKey : selectedWeekKey);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleAddItem = async (item: GithubTrendItem) => {
    setRowActionKey(`add-${item.repo_full_name}`);
    try {
      const result = await addGithubTrendItemToMaterials(
        {
          periodType: trendScope,
          periodKey: effectivePeriodKey,
          weekKey: trendScope === "weekly" ? effectivePeriodKey : undefined,
        },
        item.repo_full_name,
        enhanceEnabled,
      );
      const tokenMissing = result.enrich?.degrade_reason === "missing_github_token";
      setFeedback({
        kind: tokenMissing ? "info" : "success",
        message:
          (result.created
            ? trendsText.addSuccessCreated
            : result.updated
              ? trendsText.addSuccessUpdated
              : trendsText.addSuccessExisting) + enrichSuffix(result.enrich),
        materialId: result.material_id,
      });
    } catch (error) {
      console.error("单项目入素材失败:", error);
      setFeedback({ kind: "error", message: trendsText.addFailed });
    } finally {
      setRowActionKey(null);
    }
  };

  const handleRewriteItem = async (item: GithubTrendItem) => {
    setRowActionKey(`rewrite-${item.repo_full_name}`);
    try {
      const payload = await buildGithubTrendItemRewrite(
        {
          periodType: trendScope,
          periodKey: effectivePeriodKey,
          weekKey: trendScope === "weekly" ? effectivePeriodKey : undefined,
        },
        item.repo_full_name,
        enhanceEnabled,
      );
      const prefillSource = payload.content?.trim();
      if (!prefillSource) {
        setFeedback({ kind: "error", message: trendsText.rewritePayloadMissing });
        return;
      }

      if (payload.enrich?.degraded) {
        setFeedback({
          kind: "info",
          message: `${trendsText.rewriteDegraded}${enrichSuffix(payload.enrich)}`,
        });
      }

      navigate("/", {
        state: {
          prefillSource,
          sourceType: trendScope === "daily" ? "github-trend-daily" : "github-trend-weekly",
          prefillTitle: tf(trendsText.rewriteTitleSingle, { name: item.repo_full_name }),
        },
      });
    } catch (error) {
      console.error("构建改写输入失败:", error);
      setFeedback({ kind: "error", message: trendsText.rewriteBuildFailed });
    } finally {
      setRowActionKey(null);
    }
  };

  const handleRewriteTop10 = () => {
    if (!snapshot?.items?.length) {
      setFeedback({ kind: "error", message: trendsText.rewritePayloadMissing });
      return;
    }
    const prefillSource = markdownForDigest(trendScope, effectivePeriodKey, sortedItems);
    navigate("/", {
      state: {
        prefillSource,
        sourceType: trendScope === "daily" ? "github-trend-daily" : "github-trend-weekly",
        prefillTitle:
          trendScope === "daily"
            ? tf(trendsText.rewriteTop10Daily, {})
            : tf(trendsText.rewriteTop10Weekly, {}),
      },
    });
  };

  const rewriteTop10Label =
    trendScope === "daily" ? trendsText.rewriteTop10Daily : trendsText.rewriteTop10Weekly;

  const periodLabel = trendScope === "daily" ? trendsText.dayLabel : trendsText.weekLabel;
  const trendPeriods = trendScope === "daily" ? dayOptions : weekOptions;
  const starsLabel = trendScope === "daily" ? trendsText.dailyStars : trendsText.weeklyStars;
  const getPeriodKey = (period: GithubTrendPeriodOption | GithubTrendWeekOption) =>
    "period_key" in period ? period.period_key : period.week_key;
  const getPeriodLabel = (period: GithubTrendPeriodOption | GithubTrendWeekOption) =>
    "period_key" in period
      ? period.latest_snapshot_date || period.period_key
      : period.week_key;

  return (
    <div className="github-trends-page">
      <AppTopNav />

      <main className="github-trends-main">
        <section className="github-trends-header">
          <div>
            <h1>{trendsText.title}</h1>
            <p>{trendsText.subtitle}</p>
          </div>

          <div className="github-trends-controls">
            <div className="github-trends-scope-toggle" role="tablist" aria-label={trendsText.scopeLabel}>
              <button
                type="button"
                className={trendScope === "daily" ? "is-active" : ""}
                onClick={() => {
                  void handleSelectScope("daily");
                }}
              >
                {trendsText.scopeDaily}
              </button>
              <button
                type="button"
                className={trendScope === "weekly" ? "is-active" : ""}
                onClick={() => {
                  void handleSelectScope("weekly");
                }}
              >
                {trendsText.scopeWeekly}
              </button>
            </div>

            <label className="github-trends-period-select">
              <span>{periodLabel}</span>
              <select
                value={trendScope === "daily" ? selectedDayKey : selectedWeekKey}
                onChange={(event) => {
                  if (trendScope === "daily") {
                    void handleSelectDay(event.target.value);
                  } else {
                    void handleSelectWeek(event.target.value);
                  }
                }}
              >
                {trendPeriods.map((period) => (
                  <option key={getPeriodKey(period)} value={getPeriodKey(period)}>
                    {getPeriodLabel(period)}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className="github-trends-secondary-btn"
              onClick={() => {
                void handleRefresh();
              }}
              disabled={isRefreshing || snapshot?.is_refreshing}
            >
              {isRefreshing ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              {isRefreshing ? trendsText.refreshing : trendsText.refresh}
            </button>

            <button
              type="button"
              className="github-trends-primary-btn"
              onClick={handleRewriteTop10}
              disabled={!snapshot?.items?.length}
            >
              {rewriteTop10Label}
            </button>

            <label className="github-trends-enhance-toggle">
              <input
                type="checkbox"
                checked={enhanceEnabled}
                onChange={(event) => setEnhanceEnabled(event.target.checked)}
              />
              <span>{trendsText.enrichToggle}</span>
            </label>
          </div>
        </section>

        <section className="github-trends-meta">
          {snapshot?.captured_at && (
            <span>{tf(trendsText.updatedAt, { time: formatDateTime(snapshot.captured_at, locale) })}</span>
          )}
          {snapshot?.is_stale && <span className="warn">{trendsText.staleNotice}</span>}
          {snapshot?.fetch_error && (
            <span className="warn">{tf(trendsText.fetchError, { error: snapshot.fetch_error })}</span>
          )}
        </section>

        {feedback && (
          <section className={`github-trends-feedback ${feedback.kind}`}>
            <span>{feedback.message}</span>
            {feedback.materialId ? (
              <button
                type="button"
                className="github-trends-feedback-link"
                onClick={() => navigate(`/materials?material_id=${feedback.materialId}`)}
              >
                {trendsText.viewMaterialDetail}
              </button>
            ) : null}
          </section>
        )}

        <section className="github-trends-table-wrap">
          {isLoading ? (
            <div className="github-trends-loading">
              <Loader2 size={16} className="spin" />
              <span>{text.home.loading}</span>
            </div>
          ) : !snapshot?.items?.length ? (
            <div className="github-trends-empty">{trendsText.noData}</div>
          ) : (
            <table className="github-trends-table">
              <thead>
                <tr>
                  <th>{trendsText.rank}</th>
                  <th>{trendsText.project}</th>
                  <th>{trendsText.owner}</th>
                  <th>{trendsText.description}</th>
                  <th>{starsLabel}</th>
                  <th>{trendsText.link}</th>
                  <th>{trendsText.actions}</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((item, index) => {
                  const rowBusy =
                    rowActionKey === `add-${item.repo_full_name}` ||
                    rowActionKey === `rewrite-${item.repo_full_name}`;
                  const addBusy = rowActionKey === `add-${item.repo_full_name}`;
                  const rewriteBusy = rowActionKey === `rewrite-${item.repo_full_name}`;
                  const descriptionText = pickDescription(item, lang);
                  return (
                    <tr key={`${item.rank}-${item.repo_full_name}`}>
                      <td>{index + 1}</td>
                      <td className="repo-cell" title={item.repo_full_name}>
                        {item.repo_full_name}
                      </td>
                      <td>{item.owner}</td>
                      <td className="description-cell">
                        <div className="description-text" title={descriptionText}>
                          {descriptionText}
                        </div>
                      </td>
                      <td>{item.stars_this_week}</td>
                      <td className="link-cell">
                        <a href={item.repo_url} target="_blank" rel="noreferrer">
                          {trendsText.openRepo}
                          <ExternalLink size={12} />
                        </a>
                      </td>
                      <td>
                        <div className="github-trends-row-actions">
                          <button
                            type="button"
                            className="github-trends-secondary-btn"
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
                              trendsText.addMaterial
                            )}
                          </button>
                          <button
                            type="button"
                            className="github-trends-primary-btn"
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
                              trendsText.goRewrite
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
