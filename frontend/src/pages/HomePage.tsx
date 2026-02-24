import React, { useState, useRef, useEffect } from "react";
import { Send, Loader2, Sparkles, X } from "lucide-react";
import { Button, Input, Textarea, Card } from "../components";
import {
  extractStyle,
  getStyles,
  getRewrites,
  rewriteWithStream,
  type RewriteRecord,
  type WritingStyle,
} from "../services/api";
import "./HomePage.css";

const TARGET_WORD_OPTIONS = [500, 1000, 1500, 2000];
const IMAGE_PLACEHOLDER_REGEX = /\[配图建议\|名称:[^\]]+\]/g;

export const HomePage: React.FC = () => {
  const [sourceContent, setSourceContent] = useState("");
  const [selectedStyleId, setSelectedStyleId] = useState<number | undefined>();
  const [targetLength, setTargetLength] = useState<number>(1000);
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [rewrittenContent, setRewrittenContent] = useState("");
  const [resultWordCount, setResultWordCount] = useState(0);
  const [selectedHistory, setSelectedHistory] = useState<RewriteRecord | null>(null);
  const [showNewStyle, setShowNewStyle] = useState(false);
  const [newStyleName, setNewStyleName] = useState("");
  const [newStyleContent, setNewStyleContent] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);

  const rewriteRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const countWords = (content: string) => {
    const cleaned = content.replace(IMAGE_PLACEHOLDER_REGEX, "").replace(/\s+/g, "");
    return cleaned.length;
  };

  // 加载风格和历史
  useEffect(() => {
    loadData();
  }, []);

  // 组件卸载时关闭 EventSource 连接
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
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
    } catch (error) {
      console.error("加载数据失败:", error);
    }
  };

  // 提取新风格
  const handleExtractStyle = async () => {
    if (!newStyleName || !newStyleContent) return;

    setIsExtracting(true);
    try {
      await extractStyle(newStyleContent, newStyleName);
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

  // 开始改写 - 使用 SSE 流式输出
  const handleRewrite = async () => {
    if (!sourceContent || !selectedStyleId) return;

    // 如果已有连接，先关闭
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsLoading(true);
    setRewrittenContent("");
    setResultWordCount(0);

    try {
      // 使用 SSE 流式接收改写结果
      eventSourceRef.current = rewriteWithStream(
        {
          source_article: sourceContent,
          style_id: selectedStyleId,
          target_words: targetLength,
        },
        (chunk) => {
          // 流式接收内容，逐步显示
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
          // 完成
          setIsLoading(false);
          // 刷新历史记录
          loadData();
          // 滚动到结果
          setTimeout(() => {
            rewriteRef.current?.scrollIntoView({ behavior: "smooth" });
          }, 100);
        },
      );
    } catch (error) {
      console.error("改写失败:", error);
      setIsLoading(false);
    }
  };

  // 复制内容
  const handleCopy = () => {
    navigator.clipboard.writeText(rewrittenContent);
  };

  const handleOpenHistory = (item: RewriteRecord) => {
    setSelectedHistory(item);
  };

  return (
    <div className="home-page">
      <div className="page-header">
        <h1 className="page-title">写作改写</h1>
        <p className="page-description">
          输入文章内容，选择写作风格，开始AI改写
        </p>
      </div>

      <div className="home-grid">
        {/* 左侧：输入区域 */}
        <div className="input-section">
          <Card>
            <div className="card-header-custom">
              <h3>原文输入</h3>
            </div>
            <Textarea
              placeholder="请输入需要改写的文章内容，或粘贴URL对应的文章内容..."
              value={sourceContent}
              onChange={(e) => setSourceContent(e.target.value)}
              style={{ minHeight: "200px" }}
            />

            <div className="options-row">
              <div className="option-item">
                <label>写作风格</label>
                <select
                  value={selectedStyleId || ""}
                  onChange={(e) =>
                    setSelectedStyleId(
                      e.target.value ? Number(e.target.value) : undefined,
                    )
                  }
                  className="select-input"
                >
                  <option value="">请选择风格</option>
                  {styles.map((style) => (
                    <option key={style.id} value={style.id}>
                      {style.name}
                    </option>
                  ))}
                </select>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowNewStyle(true)}
                  icon={<Sparkles size={14} />}
                >
                  新建
                </Button>
              </div>

              <div className="option-item">
                <label>目标字数</label>
                <select
                  value={targetLength}
                  onChange={(e) => setTargetLength(Number(e.target.value))}
                  className="select-input"
                >
                  {TARGET_WORD_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option} 字
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="button-group">
              <Button
                onClick={handleRewrite}
                disabled={!sourceContent || !selectedStyleId || isLoading}
                loading={isLoading}
                icon={<Send size={16} />}
                style={{ flex: 1, marginTop: "16px" }}
              >
                {isLoading ? "改写中..." : "开始改写"}
              </Button>
              {isLoading && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (eventSourceRef.current) {
                      eventSourceRef.current.close();
                      eventSourceRef.current = null;
                    }
                    setIsLoading(false);
                  }}
                  icon={<X size={16} />}
                  style={{ marginTop: "16px", marginLeft: "8px" }}
                >
                  取消
                </Button>
              )}
            </div>
          </Card>

          {/* 新建风格弹窗 */}
          {showNewStyle && (
            <div
              className="modal-overlay"
              onClick={() => setShowNewStyle(false)}
            >
              <div className="modal" onClick={(e) => e.stopPropagation()}>
                <h3>提取写作风格</h3>
                <Input
                  label="风格名称"
                  placeholder="输入风格名称"
                  value={newStyleName}
                  onChange={(e) => setNewStyleName(e.target.value)}
                  style={{ marginBottom: "12px" }}
                />
                <Textarea
                  label="参考文章"
                  placeholder="粘贴一篇代表该风格的文章，用于提取写作特征..."
                  value={newStyleContent}
                  onChange={(e) => setNewStyleContent(e.target.value)}
                  style={{ minHeight: "150px" }}
                />
                <div className="modal-actions">
                  <Button
                    variant="secondary"
                    onClick={() => setShowNewStyle(false)}
                  >
                    取消
                  </Button>
                  <Button
                    onClick={handleExtractStyle}
                    loading={isExtracting}
                    disabled={!newStyleName || !newStyleContent}
                  >
                    提取风格
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 右侧：结果区域 */}
        <div className="output-section" ref={rewriteRef}>
          <Card>
            <div className="card-header-custom">
              <div className="result-header-left">
                <h3>改写结果</h3>
                {resultWordCount > 0 && (
                  <span className="word-count">字数：{resultWordCount}</span>
                )}
              </div>
              <div className="result-header-actions">
                {rewrittenContent && (
                  <Button variant="ghost" size="sm" onClick={handleCopy}>
                    复制
                  </Button>
                )}
              </div>
            </div>
            {isLoading && !rewrittenContent ? (
              <div className="loading-placeholder">
                <Loader2 className="spin" size={24} />
                <span>AI正在改写中...</span>
              </div>
            ) : rewrittenContent ? (
              <div className="result-content">
                {rewrittenContent}
                {isLoading && (
                  <span className="streaming-indicator">
                    <Loader2 className="spin" size={16} />
                    <span>正在接收内容...</span>
                  </span>
                )}
              </div>
            ) : (
              <div className="empty-placeholder">
                <Sparkles size={48} strokeWidth={1} />
                <span>改写结果将显示在这里</span>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* 历史记录 */}
      <div className="history-section">
        <h3>改写历史</h3>
        <div className="history-list">
          {rewrites.length === 0 ? (
            <div className="empty-history">暂无改写历史</div>
          ) : (
            rewrites.slice(0, 10).map((item) => (
              <button
                key={item.id}
                type="button"
                className="history-item"
                onClick={() => handleOpenHistory(item)}
              >
                <div className="history-content">
                  <div className="history-title">
                    {item.source_article?.slice(0, 100)}...
                  </div>
                  <div className="history-date">
                    {new Date(item.created_at).toLocaleString()}
                  </div>
                </div>
                <div className={`history-status status-${item.status}`}>
                  {item.status === "completed"
                    ? "已完成"
                    : item.status === "running"
                      ? "处理中"
                      : item.status === "failed"
                      ? "失败"
                      : "待处理"}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {selectedHistory && (
        <div className="modal-overlay" onClick={() => setSelectedHistory(null)}>
          <div className="modal modal-lg history-detail-modal" onClick={(e) => e.stopPropagation()}>
            <h3>改写详情 #{selectedHistory.id}</h3>
            <div className="history-detail-meta">
              <span>状态：{selectedHistory.status}</span>
              <span>目标字数：{selectedHistory.target_words}</span>
              <span>实际字数：{selectedHistory.actual_words || countWords(selectedHistory.final_content || "")}</span>
              <span>时间：{new Date(selectedHistory.created_at).toLocaleString()}</span>
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
