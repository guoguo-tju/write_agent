import React, { useEffect, useMemo, useState } from "react";
import { ExternalLink, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { AppTopNav } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  addGithubTrendItemToMaterials,
  addGithubTrendWeekDigestToMaterials,
  getGithubTrendWeeks,
  getGithubTrends,
  refreshGithubTrends,
  type GithubTrendItem,
  type GithubTrendSnapshot,
  type GithubTrendWeekOption,
} from "../services/api";
import "./GithubTrendsPage.css";

type FeedbackKind = "info" | "success" | "error";

const calcCurrentWeekKey = () => {
  const now = new Date();
  const target = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  const day = target.getUTCDay() || 7;
  target.setUTCDate(target.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((target.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  return `${target.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
};

const formatDateTime = (value: string, locale: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString(locale);
};

const pickDescription = (item: GithubTrendItem, lang: "zh" | "en"): string => {
  const original = item.description?.trim() || "";
  const translated = item.description_zh?.trim() || "";
  const hasChineseInOriginal = /[\u4e00-\u9fff]/.test(original);

  if (lang === "zh") {
    return translated || (hasChineseInOriginal ? original : "暂无简介");
  }
  return original || translated || "No description";
};

const markdownForItem = (
  weekKey: string,
  item: GithubTrendItem,
  displayRank: number,
) => {
  const description = pickDescription(item, "zh");
  return [
    `# GitHub 周榜项目观察（${weekKey} #${displayRank}）`,
    "",
    `- 项目：${item.repo_full_name}`,
    `- 作者：${item.owner}`,
    `- 本周新增 Star：${item.stars_this_week}`,
    `- 项目链接：${item.repo_url}`,
    `- 项目简介：${description}`,
    "",
    "## 本周观察（可补充）",
    "- 这个项目解决了什么问题？",
    "- 为什么这周增长快？",
    "",
    "## 改写方向（可补充）",
    "- 面向小白的解释路径",
    "- 可落地实践建议",
  ].join("\n");
};

const markdownForDigest = (weekKey: string, items: GithubTrendItem[]) => {
  const lines = [
    `# GitHub 周榜 Top10（${weekKey}）`,
    "",
    "| 排名 | 项目 | 作者 | 本周新增Star | 简介 | 链接 |",
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
  const [weeks, setWeeks] = useState<GithubTrendWeekOption[]>([]);
  const [selectedWeekKey, setSelectedWeekKey] = useState(calcCurrentWeekKey());
  const [snapshot, setSnapshot] = useState<GithubTrendSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isBulkAdding, setIsBulkAdding] = useState(false);
  const [rowActionKey, setRowActionKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ kind: FeedbackKind; message: string } | null>(null);

  const effectiveWeekKey = snapshot?.week_key || selectedWeekKey;
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

  const loadWeeks = async () => {
    try {
      const result = await getGithubTrendWeeks();
      setWeeks(result);
    } catch (error) {
      console.error("加载周列表失败:", error);
    }
  };

  const loadSnapshot = async (weekKey?: string) => {
    setIsLoading(true);
    try {
      const data = await getGithubTrends(weekKey);
      setSnapshot(data);
      setFeedback(null);
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
      await Promise.all([loadWeeks(), loadSnapshot(selectedWeekKey)]);
    })();
  }, []);

  const handleSelectWeek = async (weekKey: string) => {
    setSelectedWeekKey(weekKey);
    await loadSnapshot(weekKey);
  };

  const handleRefresh = async () => {
    if (isRefreshing || snapshot?.is_refreshing) {
      setFeedback({ kind: "info", message: trendsText.refreshingLocked });
      return;
    }

    setIsRefreshing(true);
    try {
      const data = await refreshGithubTrends();
      setSnapshot(data);
      setSelectedWeekKey(data.week_key);
      await loadWeeks();
      setFeedback({ kind: "success", message: trendsText.refreshSuccess });
    } catch (error) {
      console.error("手动更新失败:", error);
      setFeedback({ kind: "error", message: trendsText.refreshFailed });
      await loadSnapshot(selectedWeekKey);
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleAddItem = async (item: GithubTrendItem) => {
    setRowActionKey(`add-${item.repo_full_name}`);
    try {
      const result = await addGithubTrendItemToMaterials(
        effectiveWeekKey,
        item.repo_full_name,
      );
      setFeedback({
        kind: "success",
        message: result.created
          ? trendsText.addSuccessCreated
          : trendsText.addSuccessExisting,
      });
    } catch (error) {
      console.error("单项目入素材失败:", error);
      setFeedback({ kind: "error", message: trendsText.addFailed });
    } finally {
      setRowActionKey(null);
    }
  };

  const handleBulkAdd = async () => {
    setIsBulkAdding(true);
    try {
      const result = await addGithubTrendWeekDigestToMaterials(effectiveWeekKey);
      setFeedback({
        kind: "success",
        message: result.created
          ? trendsText.addSuccessCreated
          : trendsText.addSuccessExisting,
      });
    } catch (error) {
      console.error("周报入素材失败:", error);
      setFeedback({ kind: "error", message: trendsText.addFailed });
    } finally {
      setIsBulkAdding(false);
    }
  };

  const handleRewriteItem = (item: GithubTrendItem, displayRank: number) => {
    const prefillSource = markdownForItem(effectiveWeekKey, item, displayRank);
    if (!prefillSource) {
      setFeedback({ kind: "error", message: trendsText.rewritePayloadMissing });
      return;
    }
    navigate("/", {
      state: {
        prefillSource,
        sourceType: "github-trend-item",
        prefillTitle: tf(trendsText.rewriteTitleSingle, { name: item.repo_full_name }),
      },
    });
  };

  const handleRewriteTop10 = () => {
    if (!snapshot?.items?.length) {
      setFeedback({ kind: "error", message: trendsText.rewritePayloadMissing });
      return;
    }
    const prefillSource = markdownForDigest(effectiveWeekKey, sortedItems);
    navigate("/", {
      state: {
        prefillSource,
        sourceType: "github-trend-weekly",
        prefillTitle: tf(trendsText.rewriteTitleWeekly, { week: effectiveWeekKey }),
      },
    });
  };

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
            <label className="github-trends-week-select">
              <span>{trendsText.weekLabel}</span>
              <select
                value={selectedWeekKey}
                onChange={(event) => {
                  void handleSelectWeek(event.target.value);
                }}
              >
                {weekOptions.map((week) => (
                  <option key={week.week_key} value={week.week_key}>
                    {week.week_key}
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
              className="github-trends-secondary-btn"
              onClick={() => {
                void handleBulkAdd();
              }}
              disabled={isBulkAdding || !snapshot?.items?.length}
            >
              {isBulkAdding ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
              {trendsText.bulkAdd}
            </button>

            <button
              type="button"
              className="github-trends-primary-btn"
              onClick={handleRewriteTop10}
              disabled={!snapshot?.items?.length}
            >
              {trendsText.rewriteTop10}
            </button>
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
            {feedback.message}
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
                  <th>{trendsText.weeklyStars}</th>
                  <th>{trendsText.link}</th>
                  <th>{trendsText.actions}</th>
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((item, index) => {
                  const rowBusy = rowActionKey === `add-${item.repo_full_name}`;
                  const descriptionText = pickDescription(item, lang);
                  return (
                    <tr key={`${item.rank}-${item.repo_full_name}`}>
                      <td>{index + 1}</td>
                      <td className="repo-cell">{item.repo_full_name}</td>
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
                            {rowBusy ? (
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
                            onClick={() => handleRewriteItem(item, index + 1)}
                          >
                            {trendsText.goRewrite}
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
