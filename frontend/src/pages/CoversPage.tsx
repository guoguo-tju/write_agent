import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Image as ImageIcon,
  Loader2,
  Palette,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { AppTopNav } from "../components";
import {
  coverWithStream,
  createCoverStyle,
  deleteCoverStyle,
  getCover,
  getCoversByRewrites,
  getCoverStyles,
  getRewrites,
  type CoverRequest,
  type CoverRecord,
  type CoverStyle,
  type RewriteRecord,
  type SSEMessage,
} from "../services/api";
import "./CoversPage.css";

type PromptMode = "auto" | "style" | "custom";
type StreamStatus = "idle" | "running" | "success" | "error";

const ratioOptions = [
  { value: "2.35:1", label: "2.35:1" },
  { value: "1:1", label: "1:1" },
  { value: "9:16", label: "9:16" },
  { value: "3:4", label: "3:4" },
] as const;

const stageLabel: Partial<Record<SSEMessage["type"], string>> = {
  start: "准备生成...",
  progress: "处理中...",
  prompt: "正在构建提示词...",
  prompt_done: "提示词已生成",
  generating: "图像生成中...",
  saving: "保存结果中...",
  done: "生成完成",
};

const summarize = (value: string, maxLength = 40) => {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength)}...`;
};

export const CoversPage: React.FC = () => {
  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [covers, setCovers] = useState<Map<number, CoverRecord>>(new Map());
  const [coverStyles, setCoverStyles] = useState<CoverStyle[]>([]);

  const [selectedRewriteId, setSelectedRewriteId] = useState<number | null>(
    null,
  );
  const [selectedStyleId, setSelectedStyleId] = useState<number | null>(null);
  const [promptMode, setPromptMode] = useState<PromptMode>("auto");
  const [customPrompt, setCustomPrompt] = useState("");
  const [selectedRatio, setSelectedRatio] =
    useState<(typeof ratioOptions)[number]["value"]>("2.35:1");

  const [isGenerating, setIsGenerating] = useState(false);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("idle");
  const [streamMessage, setStreamMessage] = useState("等待生成");

  const [showStyleModal, setShowStyleModal] = useState(false);
  const [newStyleName, setNewStyleName] = useState("");
  const [newStylePrompt, setNewStylePrompt] = useState("");
  const [newStyleDesc, setNewStyleDesc] = useState("");
  const [isCreatingStyle, setIsCreatingStyle] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);

  const selectedCover = selectedRewriteId
    ? covers.get(selectedRewriteId) || null
    : null;

  const orderedCoverHistory = useMemo(() => {
    return Array.from(covers.values()).sort((left, right) => {
      const leftTime = Date.parse(left.updated_at || left.created_at);
      const rightTime = Date.parse(right.updated_at || right.created_at);
      return rightTime - leftTime;
    });
  }, [covers]);

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
      const [rewritesData, stylesData] = await Promise.all([
        getRewrites(),
        getCoverStyles(),
      ]);
      const completedRewrites = rewritesData.filter(
        (item) => item.status === "completed",
      );
      setRewrites(completedRewrites);
      setCoverStyles(stylesData);

      if (stylesData.length > 0 && !selectedStyleId) {
        setSelectedStyleId(stylesData[0].id);
      }
      if (
        completedRewrites.length > 0 &&
        !completedRewrites.some((item) => item.id === selectedRewriteId)
      ) {
        setSelectedRewriteId(completedRewrites[0].id);
      }

      const coverList = await getCoversByRewrites(
        completedRewrites.map((item) => item.id),
      );
      setCovers(
        new Map<number, CoverRecord>(
          coverList.map((cover) => [cover.rewrite_id, cover]),
        ),
      );
    } catch (error) {
      console.error("加载封面页面数据失败:", error);
      setStreamStatus("error");
      setStreamMessage("加载数据失败，请刷新后重试");
    }
  };

  const closeCurrentStream = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
  };

  const handleGenerateCover = () => {
    if (!selectedRewriteId) {
      setStreamStatus("error");
      setStreamMessage("请先选择目标文章");
      return;
    }
    if (promptMode === "style" && !selectedStyleId) {
      setStreamStatus("error");
      setStreamMessage("风格模式下请先选择一个封面风格");
      return;
    }
    if (promptMode === "custom" && !customPrompt.trim()) {
      setStreamStatus("error");
      setStreamMessage("自定义模式下请输入提示词");
      return;
    }

    closeCurrentStream();

    const request: CoverRequest = {
      rewrite_id: selectedRewriteId,
      size: selectedRatio,
    };
    if (promptMode === "style" && selectedStyleId) {
      request.style_id = selectedStyleId;
    }
    if (promptMode === "custom" && customPrompt.trim()) {
      request.custom_prompt = customPrompt.trim();
    }

    setIsGenerating(true);
    setStreamStatus("running");
    setStreamMessage("正在启动生成任务...");

    eventSourceRef.current = coverWithStream(
      request,
      (event) => {
        const message =
          String(event.message || "").trim() ||
          stageLabel[event.type] ||
          "处理中...";
        setStreamStatus("running");
        setStreamMessage(message);
      },
      (errorMessage) => {
        setIsGenerating(false);
        setStreamStatus("error");
        setStreamMessage(errorMessage || "封面生成失败");
        closeCurrentStream();
      },
      async (event) => {
        try {
          const coverId = Number(event.id || 0);
          let cover: CoverRecord | null = null;

          if (coverId > 0) {
            cover = await getCover(coverId);
          } else {
            const latest = await getCoversByRewrites([request.rewrite_id]);
            cover = latest[0] || null;
          }

          if (!cover) {
            setStreamStatus("error");
            setStreamMessage("封面生成成功，但未读取到结果");
            return;
          }

          setCovers((previous) => {
            const nextMap = new Map(previous);
            nextMap.set(cover.rewrite_id, cover);
            return nextMap;
          });
          setSelectedRewriteId(cover.rewrite_id);
          setStreamStatus("success");
          setStreamMessage("封面已生成");
        } catch (error) {
          console.error("获取封面结果失败:", error);
          setStreamStatus("error");
          setStreamMessage("封面生成完成，但读取结果失败");
        } finally {
          setIsGenerating(false);
          closeCurrentStream();
        }
      },
    );
  };

  const handleCreateStyle = async () => {
    if (!newStyleName.trim() || !newStylePrompt.trim()) {
      return;
    }

    setIsCreatingStyle(true);
    try {
      const created = await createCoverStyle({
        name: newStyleName.trim(),
        prompt_template: newStylePrompt.trim(),
        description: newStyleDesc.trim() || undefined,
      });
      setCoverStyles((prev) => [created, ...prev]);
      setSelectedStyleId(created.id);
      setShowStyleModal(false);
      setNewStyleName("");
      setNewStylePrompt("");
      setNewStyleDesc("");
      setStreamStatus("success");
      setStreamMessage(`已创建风格：${created.name}`);
    } catch (error) {
      console.error("创建封面风格失败:", error);
      setStreamStatus("error");
      setStreamMessage("创建封面风格失败，请重试");
    } finally {
      setIsCreatingStyle(false);
    }
  };

  const handleDeleteStyle = async (style: CoverStyle) => {
    const confirmed = window.confirm(`确定删除风格“${style.name}”吗？`);
    if (!confirmed) {
      return;
    }
    try {
      await deleteCoverStyle(style.id);
      setCoverStyles((prev) => prev.filter((item) => item.id !== style.id));
      if (selectedStyleId === style.id) {
        const fallback = coverStyles.find((item) => item.id !== style.id);
        setSelectedStyleId(fallback?.id ?? null);
      }
      setStreamStatus("success");
      setStreamMessage(`已删除风格：${style.name}`);
    } catch (error) {
      console.error("删除封面风格失败:", error);
      setStreamStatus("error");
      setStreamMessage("删除封面风格失败，请重试");
    }
  };

  const downloadCover = () => {
    if (!selectedCover?.image_url) {
      return;
    }
    const link = document.createElement("a");
    link.href = selectedCover.image_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.click();
  };

  const canGenerate =
    !!selectedRewriteId &&
    !isGenerating &&
    !(promptMode === "style" && !selectedStyleId) &&
    !(promptMode === "custom" && !customPrompt.trim());

  return (
    <div className="covers-v2-page">
      <AppTopNav />

      <main className="covers-v2-main">
        <section className="covers-v2-config">
          <div className="covers-v2-title">
            <h1>封面生成</h1>
            <p>基于改写结果生成视觉封面，支持风格模板与自定义提示词。</p>
          </div>

          <div className="covers-v2-field">
            <label>目标文章</label>
            <select
              value={selectedRewriteId || ""}
              onChange={(event) =>
                setSelectedRewriteId(
                  event.target.value ? Number(event.target.value) : null,
                )
              }
            >
              <option value="">请选择文章</option>
              {rewrites.map((rewrite) => (
                <option key={rewrite.id} value={rewrite.id}>
                  #{rewrite.id} - {summarize(rewrite.source_article)}
                </option>
              ))}
            </select>
          </div>

          <div className="covers-v2-field">
            <label>生成模式</label>
            <div className="covers-v2-mode-grid">
              <button
                className={promptMode === "auto" ? "active" : ""}
                onClick={() => setPromptMode("auto")}
                type="button"
              >
                自动
              </button>
              <button
                className={promptMode === "style" ? "active" : ""}
                onClick={() => setPromptMode("style")}
                type="button"
              >
                风格匹配
              </button>
              <button
                className={promptMode === "custom" ? "active" : ""}
                onClick={() => setPromptMode("custom")}
                type="button"
              >
                自定义
              </button>
            </div>
          </div>

          {promptMode === "style" && (
            <div className="covers-v2-field">
              <div className="covers-v2-inline-header">
                <label>封面风格</label>
                <button
                  className="ghost-btn"
                  onClick={() => setShowStyleModal(true)}
                  type="button"
                >
                  <Plus size={14} />
                  新建
                </button>
              </div>
              {coverStyles.length === 0 ? (
                <div className="covers-v2-empty-tips">暂无风格，请先创建</div>
              ) : (
                <div className="covers-v2-style-tags">
                  {coverStyles.map((style) => (
                    <button
                      key={style.id}
                      className={selectedStyleId === style.id ? "active" : ""}
                      onClick={() => setSelectedStyleId(style.id)}
                      title={style.description || style.name}
                      type="button"
                    >
                      {style.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {promptMode === "custom" && (
            <div className="covers-v2-field">
              <label>自定义提示词</label>
              <textarea
                value={customPrompt}
                onChange={(event) => setCustomPrompt(event.target.value)}
                placeholder="输入你希望的封面描述。建议包含：主题、场景、构图、风格、色调。"
              />
            </div>
          )}

          <div className="covers-v2-field">
            <label>尺寸比例</label>
            <div className="covers-v2-ratio-grid">
              {ratioOptions.map((option) => (
                <button
                  key={option.value}
                  className={selectedRatio === option.value ? "active" : ""}
                  onClick={() => setSelectedRatio(option.value)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <button
            className="covers-v2-generate-btn"
            onClick={handleGenerateCover}
            type="button"
            disabled={!canGenerate}
          >
            {isGenerating ? <Loader2 size={16} className="spin" /> : <ImageIcon size={16} />}
            <span>{isGenerating ? "生成中..." : "研墨并生成"}</span>
          </button>
        </section>

        <section className="covers-v2-preview">
          <div className="covers-v2-preview-header">
            <div>
              <h2>预览</h2>
              <span>V5.0 模型</span>
            </div>
            <div className="covers-v2-actions">
              <button
                type="button"
                className="ghost-btn"
                onClick={downloadCover}
                disabled={!selectedCover?.image_url}
                aria-label="下载封面图片"
              >
                <Download size={14} />
                下载
              </button>
              <button
                type="button"
                className="ghost-btn"
                onClick={handleGenerateCover}
                disabled={!canGenerate}
                aria-label="重新生成封面"
              >
                <RefreshCw size={14} />
                重新生成
              </button>
              <button
                type="button"
                className="ghost-btn"
                disabled
                title="后续会接入素材库存储能力"
              >
                保存至素材库
              </button>
            </div>
          </div>

          <div className="covers-v2-stage">
            {streamStatus === "running" && <Loader2 size={14} className="spin" />}
            {streamStatus === "success" && <CheckCircle2 size={14} />}
            {streamStatus === "error" && <AlertCircle size={14} />}
            <span>{streamMessage}</span>
          </div>

          <div className="covers-v2-preview-canvas">
            {selectedCover?.image_url ? (
              <img src={selectedCover.image_url} alt="封面预览图" />
            ) : (
              <div className="covers-v2-preview-placeholder">
                <ImageIcon size={40} />
                <p>请选择文章并生成封面</p>
              </div>
            )}
          </div>

          <div className="covers-v2-history">
            <div className="covers-v2-inline-header">
              <h3>最近生成</h3>
              <span>{orderedCoverHistory.length} 张</span>
            </div>
            {orderedCoverHistory.length === 0 ? (
              <div className="covers-v2-empty-tips">暂无封面历史</div>
            ) : (
              <div className="covers-v2-history-list">
                {orderedCoverHistory.map((cover) => (
                  <button
                    key={cover.id}
                    type="button"
                    className={`covers-v2-history-item ${selectedRewriteId === cover.rewrite_id ? "active" : ""}`}
                    onClick={() => setSelectedRewriteId(cover.rewrite_id)}
                    title={`文章 #${cover.rewrite_id}`}
                  >
                    {cover.image_url ? (
                      <img src={cover.image_url} alt={`封面 #${cover.rewrite_id}`} />
                    ) : (
                      <div className="covers-v2-mini-placeholder">
                        <ImageIcon size={18} />
                      </div>
                    )}
                    <span>#{cover.rewrite_id}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>
      </main>

      <section className="covers-v2-style-section">
        <div className="covers-v2-inline-header">
          <h3>
            <Palette size={16} />
            封面风格管理
          </h3>
          <button
            className="ghost-btn"
            onClick={() => setShowStyleModal(true)}
            type="button"
          >
            <Plus size={14} />
            新建风格
          </button>
        </div>
        {coverStyles.length === 0 ? (
          <div className="covers-v2-empty-tips">暂无封面风格，点击右上角创建。</div>
        ) : (
          <div className="covers-v2-style-grid">
            {coverStyles.map((style) => (
              <article key={style.id} className="covers-v2-style-card">
                <div className="covers-v2-style-card-head">
                  <h4>{style.name}</h4>
                  <button
                    type="button"
                    onClick={() => handleDeleteStyle(style)}
                    aria-label={`删除风格：${style.name}`}
                    className="icon-btn"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <p>{style.description || "暂无描述"}</p>
              </article>
            ))}
          </div>
        )}
      </section>

      {showStyleModal && (
        <div
          className="covers-v2-modal-mask"
          onClick={() => setShowStyleModal(false)}
          role="presentation"
        >
          <div
            className="covers-v2-modal"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="新建封面风格"
          >
            <h3>新建封面风格</h3>
            <label>
              风格名称
              <input
                value={newStyleName}
                onChange={(event) => setNewStyleName(event.target.value)}
                placeholder="如：极简线条、手绘插画、水墨留白"
              />
            </label>
            <label>
              提示词模板
              <textarea
                value={newStylePrompt}
                onChange={(event) => setNewStylePrompt(event.target.value)}
                placeholder="可使用 {title} 与 {content} 占位符。"
              />
            </label>
            <label>
              描述（可选）
              <input
                value={newStyleDesc}
                onChange={(event) => setNewStyleDesc(event.target.value)}
                placeholder="简要描述风格特点"
              />
            </label>
            <div className="covers-v2-modal-actions">
              <button
                type="button"
                className="ghost-btn"
                onClick={() => setShowStyleModal(false)}
              >
                取消
              </button>
              <button
                type="button"
                className="covers-v2-primary-small"
                onClick={handleCreateStyle}
                disabled={
                  isCreatingStyle ||
                  !newStyleName.trim() ||
                  !newStylePrompt.trim()
                }
              >
                {isCreatingStyle ? (
                  <>
                    <Loader2 size={14} className="spin" />
                    创建中...
                  </>
                ) : (
                  "创建风格"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
