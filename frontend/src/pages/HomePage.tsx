import React, { useEffect, useRef, useState } from "react";
import {
  Clipboard,
  Copy,
  Download,
  FolderOpen,
  Loader2,
  Plus,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { AppTopNav, Button, Input, Pagination, Textarea } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  extractStyle,
  getMaterialsPage,
  getRewrite,
  getLatestWorkflowJobByRewrite,
  getRewritesPage,
  getStyles,
  runWorkflowWithStream,
  streamWorkflowJobEvents,
  type Material,
  type RagRetrievedItem,
  type RewriteRecord,
  type WorkflowStreamCallbacks,
  type WorkflowStreamEvent,
  type WritingStyle,
} from "../services/api";
import "./HomePage.css";

const TARGET_WORD_OPTIONS = [100, 300, 500, 800, 1000, 1500, 2000, 5000, 8000];
const RAG_TOP_K_OPTIONS = [1, 3, 5];
const IMAGE_PLACEHOLDER_REGEX = /\[配图建议\|名称:[^\]]+\]/g;
const HISTORY_PAGE_SIZE = 10;
const MATERIAL_PICKER_PAGE_SIZE = 10;

type AutoReviewStatus = "idle" | "running" | "success" | "error";

const formatTime = (value: string, locale?: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "--" : date.toLocaleString(locale);
};

const summarize = (value: string, maxLength = 34) => {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}...`;
};

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

const isAbortErrorLike = (error: unknown): boolean => {
  if (error instanceof DOMException && error.name === "AbortError") {
    return true;
  }
  if (!(error instanceof Error)) {
    return false;
  }

  const typedError = error as Error & { code?: string };
  return (
    typedError.name === "CanceledError" ||
    typedError.code === "ERR_CANCELED" ||
    typedError.message === "canceled"
  );
};

const parseRagRetrieved = (
  raw?: string,
  unnamedMaterialLabel = "Untitled Material",
): RagRetrievedItem[] => {
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter((item) => item && typeof item === "object")
      .map((item) => {
        const record = item as Record<string, unknown>;
        return {
          material_id: Number(record.material_id || 0),
          title: String(record.title || unnamedMaterialLabel),
          source_url: record.source_url ? String(record.source_url) : undefined,
          tags: record.tags ? String(record.tags) : undefined,
          content: String(record.content || ""),
          score: Number(record.score || 0),
        } satisfies RagRetrievedItem;
      })
      .filter((item) => item.content.trim().length > 0);
  } catch {
    return [];
  }
};

export const HomePage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { lang, text } = useLanguage();
  const homeText = text.home;
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const t = (template: string, vars: Record<string, string | number> = {}) =>
    formatMessage(template, vars);
  const [searchParams, setSearchParams] = useSearchParams();
  const rewriteIdFromQuery = parseRewriteId(searchParams.get("rewrite_id"));
  const [sourceContent, setSourceContent] = useState("");
  const [selectedStyleId, setSelectedStyleId] = useState<number | undefined>();
  const [targetLength, setTargetLength] = useState<number>(500);
  const [enableRag, setEnableRag] = useState(true);
  const [ragTopK, setRagTopK] = useState(3);
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);

  const [isLoading, setIsLoading] = useState(false);
  const [rewrittenContent, setRewrittenContent] = useState("");
  const [resultWordCount, setResultWordCount] = useState(0);
  const [ragReferences, setRagReferences] = useState<RagRetrievedItem[]>([]);
  const [autoReviewStatus, setAutoReviewStatus] = useState<AutoReviewStatus>("idle");
  const [autoReviewMessage, setAutoReviewMessage] = useState("");
  const [autoReviewRewriteId, setAutoReviewRewriteId] = useState<number | null>(null);

  const [selectedHistory, setSelectedHistory] = useState<RewriteRecord | null>(
    null,
  );

  const [showNewStyle, setShowNewStyle] = useState(false);
  const [newStyleName, setNewStyleName] = useState("");
  const [newStyleContent, setNewStyleContent] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);
  const [showMaterialPicker, setShowMaterialPicker] = useState(false);
  const [materialPickerItems, setMaterialPickerItems] = useState<Material[]>([]);
  const [materialPickerPage, setMaterialPickerPage] = useState(1);
  const [materialPickerTotal, setMaterialPickerTotal] = useState(0);
  const [materialPickerKeyword, setMaterialPickerKeyword] = useState("");
  const [isMaterialPickerLoading, setIsMaterialPickerLoading] = useState(false);

  const workflowAbortRef = useRef<AbortController | null>(null);
  const workflowSessionRef = useRef<number | null>(null);
  const workflowSessionSeqRef = useRef(0);

  const countWords = (content: string) => {
    const cleaned = content
      .replace(IMAGE_PLACEHOLDER_REGEX, "")
      .replace(/\s+/g, "");
    return cleaned.length;
  };

  useEffect(() => {
    void loadStyles();
  }, []);

  useEffect(() => {
    void loadHistoryPage(historyPage);
  }, [historyPage]);

  useEffect(() => {
    return () => {
      workflowAbortRef.current?.abort();
      workflowAbortRef.current = null;
      workflowSessionRef.current = null;
    };
  }, []);

  useEffect(() => {
    const state = location.state as
      | {
          prefillSource?: string;
        }
      | undefined;
    const prefillSource = state?.prefillSource?.trim();
    if (!prefillSource) {
      return;
    }

    setSourceContent(prefillSource);
    navigate(
      {
        pathname: location.pathname,
        search: location.search,
      },
      {
        replace: true,
        state: {},
      },
    );
  }, [location.pathname, location.search, location.state, navigate]);

  useEffect(() => {
    if (!showMaterialPicker) {
      return;
    }
    void loadMaterialPicker(materialPickerPage, materialPickerKeyword);
  }, [showMaterialPicker, materialPickerPage, materialPickerKeyword]);

  const loadStyles = async () => {
    try {
      const stylesData = await getStyles();
      setStyles(stylesData);
      if (!selectedStyleId && stylesData.length > 0) {
        setSelectedStyleId(stylesData[0].id);
      }
    } catch (error) {
      console.error("加载风格失败:", error);
    }
  };

  const loadHistoryPage = async (page: number) => {
    setIsHistoryLoading(true);
    try {
      const response = await getRewritesPage({
        page,
        limit: HISTORY_PAGE_SIZE,
      });
      setRewrites(response.items);
      setHistoryTotal(response.total);

      if (!rewriteIdFromQuery && response.items.length > 0 && page === 1) {
        const next = new URLSearchParams(searchParams);
        next.set("rewrite_id", String(response.items[0].id));
        setSearchParams(next, { replace: true });
      }
    } catch (error) {
      console.error("加载改写历史失败:", error);
    } finally {
      setIsHistoryLoading(false);
    }
  };

  const loadMaterialPicker = async (page: number, keyword: string) => {
    setIsMaterialPickerLoading(true);
    try {
      const response = await getMaterialsPage({
        page,
        limit: MATERIAL_PICKER_PAGE_SIZE,
        keyword: keyword.trim() || undefined,
      });
      setMaterialPickerItems(response.items);
      setMaterialPickerTotal(response.total);
    } catch (error) {
      console.error("加载素材库失败:", error);
      setMaterialPickerItems([]);
      setMaterialPickerTotal(0);
    } finally {
      setIsMaterialPickerLoading(false);
    }
  };

  const openMaterialPicker = () => {
    setShowMaterialPicker(true);
    setMaterialPickerPage(1);
    setMaterialPickerKeyword("");
  };

  const closeMaterialPicker = () => {
    setShowMaterialPicker(false);
  };

  const handleSelectMaterialAsSource = (material: Material) => {
    setSourceContent(material.content || "");
    closeMaterialPicker();
  };

  const handleExtractStyle = async () => {
    if (!newStyleName.trim() || !newStyleContent.trim()) {
      return;
    }

    setIsExtracting(true);
    try {
      await extractStyle(newStyleContent.trim(), newStyleName.trim());
      await loadStyles();
      setShowNewStyle(false);
      setNewStyleName("");
      setNewStyleContent("");
    } catch (error) {
      console.error("提取风格失败:", error);
    } finally {
      setIsExtracting(false);
    }
  };

  const syncRewriteQuery = (rewriteId: number | null) => {
    const next = new URLSearchParams(searchParams);
    if (rewriteId) {
      next.set("rewrite_id", String(rewriteId));
    } else {
      next.delete("rewrite_id");
    }
    setSearchParams(next, { replace: true });
  };

  const loadRagReferences = async (rewriteId: number) => {
    try {
      const rewrite = await getRewrite(rewriteId);
      setRagReferences(
        parseRagRetrieved(rewrite.rag_retrieved, homeText.unnamedMaterial),
      );
    } catch (error) {
      console.error("加载引用素材失败:", error);
      setRagReferences([]);
    }
  };

  const executeWorkflowStream = async (
    runner: (
      callbacks: WorkflowStreamCallbacks,
      signal: AbortSignal,
    ) => Promise<WorkflowStreamEvent[]>,
    initialRewriteId: number | null = null,
  ) => {
    workflowAbortRef.current?.abort();

    setIsLoading(true);
    setRewrittenContent("");
    setResultWordCount(0);
    setRagReferences([]);
    setAutoReviewStatus("idle");
    setAutoReviewMessage("");
    setAutoReviewRewriteId(initialRewriteId);
    if (initialRewriteId) {
      syncRewriteQuery(initialRewriteId);
    }

    const controller = new AbortController();
    workflowAbortRef.current = controller;
    const sessionId = workflowSessionSeqRef.current + 1;
    workflowSessionSeqRef.current = sessionId;
    workflowSessionRef.current = sessionId;

    let currentRewriteId: number | null = initialRewriteId;
    let lastReviewScore: number | null = null;

    try {
      await runner(
        {
          onStage: (event) => {
            const rewriteId = Number(event.rewrite_id || 0) || null;
            if (rewriteId) {
              currentRewriteId = rewriteId;
              setAutoReviewRewriteId(rewriteId);
              syncRewriteQuery(rewriteId);
            }

            const stage = event.stage;
            const round = Number(event.round || 1);
            if (stage === "rewrite") {
              if (round === 2) {
                setRewrittenContent("");
                setResultWordCount(0);
                setAutoReviewMessage(homeText.loopStageRewriteRound2);
              } else {
                setAutoReviewMessage(homeText.loopStageRewriteRound1);
              }
            } else if (stage === "review") {
              setAutoReviewMessage(
                round === 2
                  ? homeText.loopStageReviewRound2
                  : homeText.loopStageReviewRound1,
              );
            }
            setAutoReviewStatus("running");
          },
          onProgress: (event) => {
            const message = String(event.message || "");
            if (message) {
              setAutoReviewMessage(message);
            }
          },
          onContent: (event) => {
            const delta = String(event.delta || "");
            if (!delta) {
              return;
            }
            setRewrittenContent((prev) => {
              const next = prev + delta;
              setResultWordCount(countWords(next));
              return next;
            });
          },
          onReviewDone: (event) => {
            lastReviewScore = Number(event.score || 0) || null;
          },
          onDone: (event) => {
            setIsLoading(false);

            const rewriteId = Number(event.rewrite_id || 0) || currentRewriteId;
            if (rewriteId) {
              currentRewriteId = rewriteId;
              setAutoReviewRewriteId(rewriteId);
              syncRewriteQuery(rewriteId);
              void loadRagReferences(rewriteId);
            }

            if (event.status === "passed") {
              const scoreSuffix = lastReviewScore
                ? t(homeText.scoreSuffix, { score: lastReviewScore })
                : "";
              setAutoReviewStatus("success");
              setAutoReviewMessage(t(homeText.loopDonePassed, { scoreSuffix }));
            } else {
              setAutoReviewStatus("error");
              setAutoReviewMessage(homeText.loopDoneMaxRetries);
            }

            if (historyPage !== 1) {
              setHistoryPage(1);
            } else {
              void loadHistoryPage(1);
            }
          },
          onError: (event) => {
            setIsLoading(false);
            const message = String(event.message || "").trim();
            setAutoReviewStatus("error");
            setAutoReviewMessage(
              message ? `${homeText.loopFailed} ${message}` : homeText.loopFailed,
            );
          },
        },
        controller.signal,
      );
    } catch (error) {
      if (isAbortErrorLike(error)) {
        return;
      }
      console.error("改写-审核闭环执行失败:", error);
      setIsLoading(false);
      setAutoReviewStatus("error");
      setAutoReviewMessage(
        error instanceof Error
          ? `${homeText.loopFailed} ${error.message}`
          : homeText.loopFailed,
      );
    } finally {
      if (workflowAbortRef.current === controller) {
        workflowAbortRef.current = null;
      }
      if (workflowSessionRef.current === sessionId) {
        workflowSessionRef.current = null;
      }
    }
  };

  useEffect(() => {
    if (!rewriteIdFromQuery) {
      return;
    }

    let cancelled = false;

    const attemptResume = async () => {
      try {
        const rewrite = await getRewrite(rewriteIdFromQuery);
        if (
          cancelled ||
          rewrite.status !== "running" ||
          workflowSessionRef.current !== null
        ) {
          return;
        }

        const job = await getLatestWorkflowJobByRewrite(rewriteIdFromQuery);
        if (
          cancelled ||
          workflowSessionRef.current !== null ||
          !job.job_id ||
          ["completed", "failed", "cancelled"].includes(job.status)
        ) {
          return;
        }

        await executeWorkflowStream(
          (callbacks, signal) =>
            streamWorkflowJobEvents(job.job_id, callbacks, signal, 0),
          rewriteIdFromQuery,
        );
      } catch (error) {
        if (!cancelled) {
          console.error("恢复工作流任务失败:", error);
        }
      }
    };

    void attemptResume();

    return () => {
      cancelled = true;
    };
  }, [rewriteIdFromQuery]);

  const handleRewrite = () => {
    if (!sourceContent.trim() || !selectedStyleId) {
      return;
    }

    void executeWorkflowStream((callbacks, signal) =>
      runWorkflowWithStream(
        {
          source_article: sourceContent,
          style_id: selectedStyleId,
          target_words: targetLength,
          enable_rag: enableRag,
          rag_top_k: ragTopK,
        },
        callbacks,
        signal,
      ),
    );
  };

  const cancelRewrite = () => {
    workflowAbortRef.current?.abort();
    workflowAbortRef.current = null;
    workflowSessionRef.current = null;
    setIsLoading(false);
    setAutoReviewStatus("idle");
    setAutoReviewMessage("");
  };

  const handleCopy = async () => {
    if (!rewrittenContent) {
      return;
    }
    await navigator.clipboard.writeText(rewrittenContent);
  };

  const handleExport = () => {
    if (!rewrittenContent) {
      return;
    }
    const blob = new Blob([rewrittenContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `rewrite-${Date.now()}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const styleValue = selectedStyleId ? String(selectedStyleId) : "";
  const layoutRewriteId = rewriteIdFromQuery;

  return (
    <div className="home-v2-page">
      <AppTopNav />

      <main className="home-v2-main">
        <section className="home-v2-source">
          <div className="home-v2-panel-header">
            <div>
              <h2>{homeText.sourceTitle}</h2>
              <span>{homeText.sourceSubtitle}</span>
            </div>
            <div className="home-v2-source-actions">
              <button
                type="button"
                title={homeText.pickMaterial}
                onClick={openMaterialPicker}
              >
                <FolderOpen size={15} />
              </button>
              <button
                type="button"
                title={homeText.clear}
                onClick={() => setSourceContent("")}
              >
                <X size={15} />
              </button>
              <button
                type="button"
                title={homeText.paste}
                onClick={async () => {
                  try {
                    const text = await navigator.clipboard.readText();
                    if (text) {
                      setSourceContent(text);
                    }
                  } catch {
                    // ignore clipboard permission errors
                  }
                }}
              >
                <Clipboard size={15} />
              </button>
            </div>
          </div>

          <textarea
            className="home-v2-source-textarea"
            placeholder={homeText.sourcePlaceholder}
            value={sourceContent}
            onChange={(event) => setSourceContent(event.target.value)}
          />

          <div className="home-v2-compose-bar">
            <div className="home-v2-compose-group">
              <label>{homeText.styleLabel}</label>
              <div className="home-v2-inline-row">
                <select
                  value={styleValue}
                  onChange={(event) =>
                    setSelectedStyleId(
                      event.target.value ? Number(event.target.value) : undefined,
                    )
                  }
                >
                  <option value="">{homeText.chooseStyle}</option>
                  {styles.map((style) => (
                    <option key={style.id} value={style.id}>
                      {style.name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="home-v2-mini-btn"
                  onClick={() => setShowNewStyle(true)}
                >
                  <Plus size={13} />
                  {homeText.newStyle}
                </button>
              </div>
            </div>

            <div className="home-v2-compose-group">
              <label>{homeText.targetLength}</label>
              <div className="home-v2-inline-row">
                <input
                  type="range"
                  min={0}
                  max={TARGET_WORD_OPTIONS.length - 1}
                  value={Math.max(0, TARGET_WORD_OPTIONS.indexOf(targetLength))}
                  onChange={(event) => {
                    const index = Number(event.target.value);
                    setTargetLength(TARGET_WORD_OPTIONS[index]);
                  }}
                />
                <strong>{t(homeText.targetWords, { count: targetLength })}</strong>
              </div>
            </div>

            <div className="home-v2-compose-group">
              <label>{homeText.ragBoost}</label>
              <div className="home-v2-rag-config">
                <label className="home-v2-rag-toggle">
                  <input
                    type="checkbox"
                    checked={enableRag}
                    onChange={(event) => setEnableRag(event.target.checked)}
                  />
                  <span>{enableRag ? homeText.ragEnabled : homeText.ragDisabled}</span>
                </label>
                <select
                  value={String(ragTopK)}
                  disabled={!enableRag}
                  onChange={(event) => setRagTopK(Number(event.target.value))}
                >
                  {RAG_TOP_K_OPTIONS.map((count) => (
                    <option key={count} value={count}>
                      {t(homeText.ragReferenceCount, { count })}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="home-v2-compose-actions">
              <Button
                onClick={handleRewrite}
                disabled={!sourceContent.trim() || !selectedStyleId || isLoading}
                loading={isLoading}
                icon={<Send size={14} />}
              >
                {isLoading ? homeText.rewriteLoading : homeText.startRewrite}
              </Button>
              {isLoading && (
                <Button
                  variant="secondary"
                  onClick={cancelRewrite}
                  icon={<X size={14} />}
                >
                  {homeText.cancel}
                </Button>
              )}
            </div>
          </div>

          <div className="home-v2-footnote">
            <span>{t(homeText.sourceWords, { count: countWords(sourceContent) })}</span>
            <span>{t(homeText.targetWords, { count: targetLength })}</span>
          </div>
        </section>

        <section className="home-v2-output">
          <div className="home-v2-panel-header">
            <div>
              <h2>{homeText.outputTitle} {isLoading ? homeText.outputLoading : ""}</h2>
              {resultWordCount > 0 && (
                <span>{t(homeText.wordCount, { count: resultWordCount })}</span>
              )}
            </div>
            <div className="home-v2-output-actions">
              <button
                type="button"
                onClick={() => {
                  if (layoutRewriteId) {
                    navigate(`/layout?rewrite_id=${layoutRewriteId}`);
                  }
                }}
                disabled={!layoutRewriteId}
              >
                {homeText.goToLayout}
              </button>
              <button type="button" onClick={handleCopy} disabled={!rewrittenContent}>
                <Copy size={14} />
                {homeText.copy}
              </button>
              <button type="button" onClick={handleExport} disabled={!rewrittenContent}>
                <Download size={14} />
                {homeText.export}
              </button>
            </div>
          </div>

          <div className="home-v2-paper">
            {isLoading && !rewrittenContent ? (
              <div className="home-v2-placeholder">
                <Loader2 size={22} className="spin" />
                <span>{homeText.generatingPlaceholder}</span>
              </div>
            ) : rewrittenContent ? (
              <div className="home-v2-result-text">
                {rewrittenContent}
                {isLoading && (
                  <span className="home-v2-streaming">
                    <Loader2 size={14} className="spin" />
                    {homeText.receiving}
                  </span>
                )}
              </div>
            ) : (
              <div className="home-v2-placeholder">
                <Sparkles size={36} />
                <span>{homeText.resultPlaceholder}</span>
              </div>
            )}
          </div>

          {autoReviewStatus !== "idle" && (
            <div className={`home-v2-review-status ${autoReviewStatus}`}>
              <span>{autoReviewMessage}</span>
              {autoReviewRewriteId && (
                <a href={`/reviews?rewrite_id=${autoReviewRewriteId}`}>
                  {homeText.goToReviewPage}
                </a>
              )}
            </div>
          )}

          <section className="home-v2-rag-panel">
            <div className="home-v2-rag-panel-head">
              <h3>{homeText.ragMaterialsTitle}</h3>
              <span>
                {enableRag
                  ? t(homeText.ragTop, { count: ragTopK })
                  : homeText.ragClosed}
              </span>
            </div>

            {isLoading ? (
              <div className="home-v2-rag-empty">{homeText.ragAfterRewrite}</div>
            ) : !enableRag ? (
              <div className="home-v2-rag-empty">{homeText.ragNotEnabled}</div>
            ) : ragReferences.length === 0 ? (
              <div className="home-v2-rag-empty">{homeText.ragNoHit}</div>
            ) : (
              <div className="home-v2-rag-list">
                {ragReferences.map((item) => (
                  <article
                    key={`${item.material_id}-${item.title}-${item.score}`}
                    className="home-v2-rag-item"
                  >
                    <div className="home-v2-rag-item-head">
                      <strong>
                        {item.title ||
                          t(homeText.materialFallback, { id: item.material_id })}
                      </strong>
                      <span>{homeText.similarity} {(item.score * 100).toFixed(1)}%</span>
                    </div>
                    <p>{summarize(item.content, 160)}</p>
                    <div className="home-v2-rag-item-meta">
                      {item.tags && <span>{item.tags}</span>}
                      {item.source_url && (
                        <a href={item.source_url} target="_blank" rel="noreferrer">
                          {homeText.viewSource}
                        </a>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </section>

        <aside className="home-v2-history">
          <div className="home-v2-panel-header">
            <div>
              <h2>{homeText.historyTitle}</h2>
              <span>{t(homeText.historyPerPage, { count: HISTORY_PAGE_SIZE })}</span>
            </div>
          </div>
          <div className="home-v2-history-list">
            {isHistoryLoading ? (
              <div className="home-v2-empty">{homeText.loading}</div>
            ) : rewrites.length === 0 ? (
              <div className="home-v2-empty">{homeText.noHistory}</div>
            ) : (
              rewrites.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`home-v2-history-item ${rewriteIdFromQuery === item.id ? "active" : ""}`}
                  onClick={() => {
                    const next = new URLSearchParams(searchParams);
                    next.set("rewrite_id", String(item.id));
                    setSearchParams(next, { replace: true });
                    setSelectedHistory(item);
                  }}
                >
                  <div className="home-v2-history-title">
                    #{item.id} {summarize(item.source_article)}
                  </div>
                  <div className="home-v2-history-meta">
                    <span>{formatTime(item.created_at, locale)}</span>
                    <span className={`status-${item.status}`}>
                      {item.status === "completed"
                        ? homeText.statusCompleted
                        : item.status === "running"
                          ? homeText.statusRunning
                          : item.status === "failed"
                            ? homeText.statusFailed
                            : homeText.statusPending}
                    </span>
                  </div>
                </button>
              ))
            )}
          </div>
          <div className="home-v2-history-pagination">
            <Pagination
              page={historyPage}
              total={historyTotal}
              limit={HISTORY_PAGE_SIZE}
              onPageChange={(nextPage) => setHistoryPage(nextPage)}
            />
          </div>
        </aside>
      </main>

      {showNewStyle && (
        <div className="modal-overlay" onClick={() => setShowNewStyle(false)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>{homeText.extractStyleStart}</h3>
            <Input
              label={homeText.styleName}
              placeholder={homeText.styleNamePlaceholder}
              value={newStyleName}
              onChange={(event) => setNewStyleName(event.target.value)}
              style={{ marginBottom: "12px" }}
            />
            <Textarea
              label={homeText.referenceArticle}
              placeholder={homeText.referenceArticlePlaceholder}
              value={newStyleContent}
              onChange={(event) => setNewStyleContent(event.target.value)}
              style={{ minHeight: "150px" }}
            />
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setShowNewStyle(false)}>
                {homeText.cancel}
              </Button>
              <Button
                onClick={handleExtractStyle}
                loading={isExtracting}
                disabled={!newStyleName.trim() || !newStyleContent.trim()}
              >
                {isExtracting ? homeText.extractStyleLoading : homeText.extractStyleStart}
              </Button>
            </div>
          </div>
        </div>
      )}

      {showMaterialPicker && (
        <div className="modal-overlay" onClick={closeMaterialPicker}>
          <div
            className="modal modal-lg material-picker-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <h3>{homeText.pickSourceFromMaterials}</h3>
            <div className="material-picker-toolbar">
              <input
                value={materialPickerKeyword}
                onChange={(event) => {
                  setMaterialPickerKeyword(event.target.value);
                  setMaterialPickerPage(1);
                }}
                placeholder={homeText.materialSearchPlaceholder}
              />
              {materialPickerKeyword && (
                <button
                  type="button"
                  className="material-picker-clear"
                  onClick={() => {
                    setMaterialPickerKeyword("");
                    setMaterialPickerPage(1);
                  }}
                >
                  {homeText.clear}
                </button>
              )}
            </div>

            <div className="material-picker-list">
              {isMaterialPickerLoading ? (
                <div className="material-picker-empty">{homeText.loading}</div>
              ) : materialPickerItems.length === 0 ? (
                <div className="material-picker-empty">{homeText.noAvailableMaterials}</div>
              ) : (
                materialPickerItems.map((material) => (
                  <button
                    key={material.id}
                    type="button"
                    className="material-picker-item"
                    onClick={() => handleSelectMaterialAsSource(material)}
                  >
                    <div className="material-picker-item-head">
                      <strong>
                        {material.title || t(homeText.materialFallback, { id: material.id })}
                      </strong>
                      <span>{formatTime(material.created_at, locale)}</span>
                    </div>
                    <p>{summarize(material.content || "", 160)}</p>
                    {material.source_url && (
                      <div className="material-picker-item-meta">
                        {t(homeText.sourcePrefix, { url: material.source_url })}
                      </div>
                    )}
                  </button>
                ))
              )}
            </div>

            <div className="material-picker-footer">
              <Pagination
                page={materialPickerPage}
                total={materialPickerTotal}
                limit={MATERIAL_PICKER_PAGE_SIZE}
                onPageChange={(nextPage) => setMaterialPickerPage(nextPage)}
              />
              <Button variant="secondary" onClick={closeMaterialPicker}>
                {homeText.close}
              </Button>
            </div>
          </div>
        </div>
      )}

      {selectedHistory && (
        <div className="modal-overlay" onClick={() => setSelectedHistory(null)}>
          <div
            className="modal modal-lg history-detail-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <h3>{t(homeText.rewriteDetail, { id: selectedHistory.id })}</h3>
            <div className="history-detail-meta">
              <span>{t(homeText.statusLabel, { status: selectedHistory.status })}</span>
              <span>{t(homeText.targetWordsLabel, { count: selectedHistory.target_words })}</span>
              <span>
                {t(homeText.actualWordsLabel, {
                  count:
                    selectedHistory.actual_words ||
                    countWords(selectedHistory.final_content || ""),
                })}
              </span>
              <span>{t(homeText.timeLabel, { time: formatTime(selectedHistory.created_at, locale) })}</span>
            </div>
            <div className="history-detail-block">
              <label>{homeText.sourceArticle}</label>
              <pre>{selectedHistory.source_article}</pre>
            </div>
            <div className="history-detail-block">
              <label>{homeText.rewrittenResult}</label>
              <pre>{selectedHistory.final_content || homeText.noResult}</pre>
            </div>
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setSelectedHistory(null)}>
                {homeText.close}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
