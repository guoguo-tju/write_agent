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
import { useSearchParams } from "react-router-dom";
import { AppTopNav, Button, Input, Pagination, Textarea } from "../components";
import {
  extractStyle,
  getMaterialsPage,
  getRewrite,
  getRewritesPage,
  getStyles,
  rewriteWithStream,
  startReview,
  type Material,
  type RagRetrievedItem,
  type RewriteRecord,
  type WritingStyle,
} from "../services/api";
import "./HomePage.css";

const TARGET_WORD_OPTIONS = [500, 800, 1000, 1500, 2000];
const RAG_TOP_K_OPTIONS = [1, 3, 5];
const IMAGE_PLACEHOLDER_REGEX = /\[配图建议\|名称:[^\]]+\]/g;
const HISTORY_PAGE_SIZE = 10;
const MATERIAL_PICKER_PAGE_SIZE = 10;

type AutoReviewStatus = "idle" | "running" | "success" | "error";

const formatTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "--" : date.toLocaleString();
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

const parseRagRetrieved = (raw?: string): RagRetrievedItem[] => {
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
          title: String(record.title || "未命名素材"),
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
  const [searchParams, setSearchParams] = useSearchParams();
  const rewriteIdFromQuery = parseRewriteId(searchParams.get("rewrite_id"));
  const [sourceContent, setSourceContent] = useState("");
  const [selectedStyleId, setSelectedStyleId] = useState<number | undefined>();
  const [targetLength, setTargetLength] = useState<number>(1000);
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

  const eventSourceRef = useRef<EventSource | null>(null);

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
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, []);

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

  const runAutoReview = async (rewriteId: number) => {
    setAutoReviewStatus("running");
    setAutoReviewRewriteId(rewriteId);
    setAutoReviewMessage("主编审核中...");
    try {
      const review = await startReview({ rewrite_id: rewriteId });
      const reviewPassed = review.result === "passed";
      const score = review.total_score ? `，总分 ${review.total_score}` : "";
      setAutoReviewStatus("success");
      setAutoReviewMessage(
        `主编审核已完成：${reviewPassed ? "通过" : "未通过"}${score}。`,
      );
    } catch (error) {
      console.error("自动主编审核失败:", error);
      setAutoReviewStatus("error");
      setAutoReviewMessage(
        error instanceof Error ? `主编审核失败：${error.message}` : "主编审核失败。",
      );
    }
  };

  const loadRagReferences = async (rewriteId: number) => {
    try {
      const rewrite = await getRewrite(rewriteId);
      setRagReferences(parseRagRetrieved(rewrite.rag_retrieved));
    } catch (error) {
      console.error("加载引用素材失败:", error);
      setRagReferences([]);
    }
  };

  const handleRewrite = () => {
    if (!sourceContent.trim() || !selectedStyleId) {
      return;
    }

    eventSourceRef.current?.close();

    setIsLoading(true);
    setRewrittenContent("");
    setResultWordCount(0);
    setRagReferences([]);
    setAutoReviewStatus("idle");
    setAutoReviewMessage("");
    setAutoReviewRewriteId(null);
    let currentRewriteId: number | null = null;

    eventSourceRef.current = rewriteWithStream(
      {
        source_article: sourceContent,
        style_id: selectedStyleId,
        target_words: targetLength,
        enable_rag: enableRag,
        rag_top_k: ragTopK,
      },
      (chunk) => {
        setRewrittenContent((prev) => {
          const next = prev + chunk;
          setResultWordCount(countWords(next));
          return next;
        });
      },
      (error) => {
        console.error("改写失败:", error);
        setIsLoading(false);
      },
      (data) => {
        const finalContent = String(data?.final_content || "");
        if (finalContent) {
          setRewrittenContent(finalContent);
          setResultWordCount(
            Number(data?.actual_words || 0) || countWords(finalContent),
          );
        }
        setIsLoading(false);
        if (currentRewriteId) {
          const next = new URLSearchParams(searchParams);
          next.set("rewrite_id", String(currentRewriteId));
          setSearchParams(next, { replace: true });
          void loadRagReferences(currentRewriteId);
          void runAutoReview(currentRewriteId);
        }
        if (historyPage !== 1) {
          setHistoryPage(1);
        } else {
          void loadHistoryPage(1);
        }
      },
      (taskId) => {
        currentRewriteId = taskId;
        const next = new URLSearchParams(searchParams);
        next.set("rewrite_id", String(taskId));
        setSearchParams(next, { replace: true });
      },
    );
  };

  const cancelRewrite = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setIsLoading(false);
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

  return (
    <div className="home-v2-page">
      <AppTopNav />

      <main className="home-v2-main">
        <section className="home-v2-source">
          <div className="home-v2-panel-header">
            <div>
              <h2>源文本</h2>
              <span>支持手动粘贴或从素材库选择</span>
            </div>
            <div className="home-v2-source-actions">
              <button
                type="button"
                title="从素材库选择"
                onClick={openMaterialPicker}
              >
                <FolderOpen size={15} />
              </button>
              <button
                type="button"
                title="清空"
                onClick={() => setSourceContent("")}
              >
                <X size={15} />
              </button>
              <button
                type="button"
                title="粘贴"
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
            placeholder="在此粘贴您的文本以开始改写..."
            value={sourceContent}
            onChange={(event) => setSourceContent(event.target.value)}
          />

          <div className="home-v2-compose-bar">
            <div className="home-v2-compose-group">
              <label>写作风格</label>
              <div className="home-v2-inline-row">
                <select
                  value={styleValue}
                  onChange={(event) =>
                    setSelectedStyleId(
                      event.target.value ? Number(event.target.value) : undefined,
                    )
                  }
                >
                  <option value="">请选择风格</option>
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
                  新建
                </button>
              </div>
            </div>

            <div className="home-v2-compose-group">
              <label>目标长度</label>
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
                <strong>约 {targetLength} 字</strong>
              </div>
            </div>

            <div className="home-v2-compose-group">
              <label>RAG 检索增强</label>
              <div className="home-v2-rag-config">
                <label className="home-v2-rag-toggle">
                  <input
                    type="checkbox"
                    checked={enableRag}
                    onChange={(event) => setEnableRag(event.target.checked)}
                  />
                  <span>{enableRag ? "已启用" : "已关闭"}</span>
                </label>
                <select
                  value={String(ragTopK)}
                  disabled={!enableRag}
                  onChange={(event) => setRagTopK(Number(event.target.value))}
                >
                  {RAG_TOP_K_OPTIONS.map((count) => (
                    <option key={count} value={count}>
                      引用 {count} 条
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
                {isLoading ? "改写中..." : "开始改写"}
              </Button>
              {isLoading && (
                <Button
                  variant="secondary"
                  onClick={cancelRewrite}
                  icon={<X size={14} />}
                >
                  取消
                </Button>
              )}
            </div>
          </div>

          <div className="home-v2-footnote">
            <span>{countWords(sourceContent)} 字</span>
            <span>目标：{targetLength} 字</span>
          </div>
        </section>

        <section className="home-v2-output">
          <div className="home-v2-panel-header">
            <div>
              <h2>砚雀输出 {isLoading ? "(研墨中...)" : ""}</h2>
              {resultWordCount > 0 && <span>字数：{resultWordCount}</span>}
            </div>
            <div className="home-v2-output-actions">
              <button type="button" onClick={handleCopy} disabled={!rewrittenContent}>
                <Copy size={14} />
                复制
              </button>
              <button type="button" onClick={handleExport} disabled={!rewrittenContent}>
                <Download size={14} />
                导出
              </button>
            </div>
          </div>

          <div className="home-v2-paper">
            {isLoading && !rewrittenContent ? (
              <div className="home-v2-placeholder">
                <Loader2 size={22} className="spin" />
                <span>正在生成改写内容...</span>
              </div>
            ) : rewrittenContent ? (
              <div className="home-v2-result-text">
                {rewrittenContent}
                {isLoading && (
                  <span className="home-v2-streaming">
                    <Loader2 size={14} className="spin" />
                    接收中...
                  </span>
                )}
              </div>
            ) : (
              <div className="home-v2-placeholder">
                <Sparkles size={36} />
                <span>改写结果将显示在这里</span>
              </div>
            )}
          </div>

          {autoReviewStatus !== "idle" && (
            <div className={`home-v2-review-status ${autoReviewStatus}`}>
              <span>{autoReviewMessage}</span>
              {autoReviewRewriteId && (
                <a href={`/reviews?rewrite_id=${autoReviewRewriteId}`}>去审核页查看</a>
              )}
            </div>
          )}

          <section className="home-v2-rag-panel">
            <div className="home-v2-rag-panel-head">
              <h3>本次引用素材</h3>
              <span>{enableRag ? `Top ${ragTopK}` : "RAG 已关闭"}</span>
            </div>

            {isLoading ? (
              <div className="home-v2-rag-empty">改写完成后展示本次引用素材。</div>
            ) : !enableRag ? (
              <div className="home-v2-rag-empty">本次未启用 RAG 检索。</div>
            ) : ragReferences.length === 0 ? (
              <div className="home-v2-rag-empty">本次未命中素材。</div>
            ) : (
              <div className="home-v2-rag-list">
                {ragReferences.map((item) => (
                  <article
                    key={`${item.material_id}-${item.title}-${item.score}`}
                    className="home-v2-rag-item"
                  >
                    <div className="home-v2-rag-item-head">
                      <strong>{item.title || `素材 #${item.material_id}`}</strong>
                      <span>相似度 {(item.score * 100).toFixed(1)}%</span>
                    </div>
                    <p>{summarize(item.content, 160)}</p>
                    <div className="home-v2-rag-item-meta">
                      {item.tags && <span>标签：{item.tags}</span>}
                      {item.source_url && (
                        <a href={item.source_url} target="_blank" rel="noreferrer">
                          查看来源
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
              <h2>历史记录</h2>
              <span>每页 {HISTORY_PAGE_SIZE} 条</span>
            </div>
          </div>
          <div className="home-v2-history-list">
            {isHistoryLoading ? (
              <div className="home-v2-empty">加载中...</div>
            ) : rewrites.length === 0 ? (
              <div className="home-v2-empty">暂无历史记录</div>
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
                    <span>{formatTime(item.created_at)}</span>
                    <span className={`status-${item.status}`}>
                      {item.status === "completed"
                        ? "完成"
                        : item.status === "running"
                          ? "处理中"
                          : item.status === "failed"
                            ? "失败"
                            : "待处理"}
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
            <h3>提取写作风格</h3>
            <Input
              label="风格名称"
              placeholder="输入风格名称"
              value={newStyleName}
              onChange={(event) => setNewStyleName(event.target.value)}
              style={{ marginBottom: "12px" }}
            />
            <Textarea
              label="参考文章"
              placeholder="粘贴一篇代表文章用于提取风格..."
              value={newStyleContent}
              onChange={(event) => setNewStyleContent(event.target.value)}
              style={{ minHeight: "150px" }}
            />
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setShowNewStyle(false)}>
                取消
              </Button>
              <Button
                onClick={handleExtractStyle}
                loading={isExtracting}
                disabled={!newStyleName.trim() || !newStyleContent.trim()}
              >
                提取风格
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
            <h3>从素材库选择原文</h3>
            <div className="material-picker-toolbar">
              <input
                value={materialPickerKeyword}
                onChange={(event) => {
                  setMaterialPickerKeyword(event.target.value);
                  setMaterialPickerPage(1);
                }}
                placeholder="搜索标题、内容、来源"
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
                  清空
                </button>
              )}
            </div>

            <div className="material-picker-list">
              {isMaterialPickerLoading ? (
                <div className="material-picker-empty">加载中...</div>
              ) : materialPickerItems.length === 0 ? (
                <div className="material-picker-empty">暂无可选素材</div>
              ) : (
                materialPickerItems.map((material) => (
                  <button
                    key={material.id}
                    type="button"
                    className="material-picker-item"
                    onClick={() => handleSelectMaterialAsSource(material)}
                  >
                    <div className="material-picker-item-head">
                      <strong>{material.title || `素材 #${material.id}`}</strong>
                      <span>{formatTime(material.created_at)}</span>
                    </div>
                    <p>{summarize(material.content || "", 160)}</p>
                    {material.source_url && (
                      <div className="material-picker-item-meta">
                        来源：{material.source_url}
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
                关闭
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
            <h3>改写详情 #{selectedHistory.id}</h3>
            <div className="history-detail-meta">
              <span>状态：{selectedHistory.status}</span>
              <span>目标字数：{selectedHistory.target_words}</span>
              <span>
                实际字数：
                {selectedHistory.actual_words ||
                  countWords(selectedHistory.final_content || "")}
              </span>
              <span>时间：{formatTime(selectedHistory.created_at)}</span>
            </div>
            <div className="history-detail-block">
              <label>原文</label>
              <pre>{selectedHistory.source_article}</pre>
            </div>
            <div className="history-detail-block">
              <label>改写结果</label>
              <pre>{selectedHistory.final_content || "暂无结果"}</pre>
            </div>
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setSelectedHistory(null)}>
                关闭
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
