import React, { useEffect, useRef, useState } from "react";
import {
  Clipboard,
  Copy,
  Download,
  Loader2,
  Plus,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { AppTopNav, Button, Input, Textarea } from "../components";
import {
  extractStyle,
  getRewrites,
  getStyles,
  rewriteWithStream,
  type RewriteRecord,
  type WritingStyle,
} from "../services/api";
import "./HomePage.css";

const TARGET_WORD_OPTIONS = [500, 800, 1000, 1500, 2000];
const IMAGE_PLACEHOLDER_REGEX = /\[配图建议\|名称:[^\]]+\]/g;

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

export const HomePage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const rewriteIdFromQuery = parseRewriteId(searchParams.get("rewrite_id"));
  const [sourceContent, setSourceContent] = useState("");
  const [selectedStyleId, setSelectedStyleId] = useState<number | undefined>();
  const [targetLength, setTargetLength] = useState<number>(1000);
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);

  const [isLoading, setIsLoading] = useState(false);
  const [rewrittenContent, setRewrittenContent] = useState("");
  const [resultWordCount, setResultWordCount] = useState(0);

  const [selectedHistory, setSelectedHistory] = useState<RewriteRecord | null>(
    null,
  );

  const [showNewStyle, setShowNewStyle] = useState(false);
  const [newStyleName, setNewStyleName] = useState("");
  const [newStyleContent, setNewStyleContent] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);

  const countWords = (content: string) => {
    const cleaned = content
      .replace(IMAGE_PLACEHOLDER_REGEX, "")
      .replace(/\s+/g, "");
    return cleaned.length;
  };

  useEffect(() => {
    void loadData();
  }, []);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, []);

  const loadData = async () => {
    try {
      const [stylesData, rewritesData] = await Promise.all([
        getStyles(),
        getRewrites(),
      ]);
      setStyles(stylesData);
      if (!selectedStyleId && stylesData.length > 0) {
        setSelectedStyleId(stylesData[0].id);
      }
      setRewrites(rewritesData);

      if (rewritesData.length > 0) {
        const hasQuery = rewriteIdFromQuery
          ? rewritesData.some((item) => item.id === rewriteIdFromQuery)
          : false;
        if (!hasQuery) {
          const next = new URLSearchParams(searchParams);
          next.set("rewrite_id", String(rewritesData[0].id));
          setSearchParams(next, { replace: true });
        }
      }
    } catch (error) {
      console.error("加载数据失败:", error);
    }
  };

  const handleExtractStyle = async () => {
    if (!newStyleName.trim() || !newStyleContent.trim()) {
      return;
    }

    setIsExtracting(true);
    try {
      await extractStyle(newStyleContent.trim(), newStyleName.trim());
      await loadData();
      setShowNewStyle(false);
      setNewStyleName("");
      setNewStyleContent("");
    } catch (error) {
      console.error("提取风格失败:", error);
    } finally {
      setIsExtracting(false);
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
    let currentRewriteId: number | null = null;

    eventSourceRef.current = rewriteWithStream(
      {
        source_article: sourceContent,
        style_id: selectedStyleId,
        target_words: targetLength,
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
        }
        void loadData();
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
              <span>草稿 V1</span>
            </div>
            <div className="home-v2-source-actions">
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
        </section>

        <aside className="home-v2-history">
          <div className="home-v2-panel-header">
            <div>
              <h2>历史记录</h2>
              <span>最近 {Math.min(rewrites.length, 20)} 条</span>
            </div>
          </div>
          <div className="home-v2-history-list">
            {rewrites.length === 0 ? (
              <div className="home-v2-empty">暂无历史记录</div>
            ) : (
              rewrites.slice(0, 20).map((item) => (
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
