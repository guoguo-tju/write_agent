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
import { useNavigate, useSearchParams } from "react-router-dom";
import { AppTopNav } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  coverWithStream,
  createManualCoverRewrite,
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
type CoverSourceMode = "rewrite" | "manual";
type StreamStatus = "idle" | "running" | "success" | "error";

const ratioOptions = [
  { value: "2.35:1", label: "2.35:1" },
  { value: "1:1", label: "1:1" },
  { value: "9:16", label: "9:16" },
  { value: "3:4", label: "3:4" },
] as const;
const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const NORMALIZED_API_BASE_URL = API_BASE_URL.replace(/\/+$/, "");

const summarize = (value: string, maxLength = 40) => {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength)}...`;
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

const resolveImageUrl = (imageUrl?: string | null): string => {
  if (!imageUrl) {
    return "";
  }
  if (/^https?:\/\//i.test(imageUrl)) {
    return imageUrl;
  }
  if (imageUrl.startsWith("/")) {
    return `${NORMALIZED_API_BASE_URL}${imageUrl}`;
  }
  return `${NORMALIZED_API_BASE_URL}/${imageUrl}`;
};

export const CoversPage: React.FC = () => {
  const navigate = useNavigate();
  const { lang, text } = useLanguage();
  const coversText = text.covers;
  const tx = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const tf = (template: string, vars: Record<string, string | number>) =>
    formatMessage(template, vars);
  const stageLabel: Partial<Record<SSEMessage["type"], string>> = {
    start: coversText.stageStart,
    progress: coversText.stageProgress,
    prompt: coversText.stagePrompt,
    prompt_done: coversText.stagePromptDone,
    generating: coversText.stageGenerating,
    saving: coversText.stageSaving,
    done: coversText.stageDone,
  };
  const [searchParams, setSearchParams] = useSearchParams();
  const rewriteIdFromQuery = parseRewriteId(searchParams.get("rewrite_id"));
  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [covers, setCovers] = useState<Map<number, CoverRecord>>(new Map());
  const [coverStyles, setCoverStyles] = useState<CoverStyle[]>([]);

  const [selectedRewriteId, setSelectedRewriteId] = useState<number | null>(
    null,
  );
  const [selectedStyleId, setSelectedStyleId] = useState<number | null>(null);
  const [coverSourceMode, setCoverSourceMode] =
    useState<CoverSourceMode>("rewrite");
  const [promptMode, setPromptMode] = useState<PromptMode>("auto");
  const [customPrompt, setCustomPrompt] = useState("");
  const [manualTitle, setManualTitle] = useState("");
  const [manualContent, setManualContent] = useState("");
  const [selectedRatio, setSelectedRatio] =
    useState<(typeof ratioOptions)[number]["value"]>("2.35:1");

  const [isGenerating, setIsGenerating] = useState(false);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("idle");
  const [streamMessage, setStreamMessage] = useState<string>(coversText.waiting);

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
    if (
      rewriteIdFromQuery &&
      rewrites.some((item) => item.id === rewriteIdFromQuery)
    ) {
      setSelectedRewriteId(rewriteIdFromQuery);
    }
  }, [rewriteIdFromQuery, rewrites]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (streamStatus === "idle") {
      setStreamMessage(coversText.waiting);
    }
  }, [coversText.waiting, streamStatus]);

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
      if (completedRewrites.length > 0) {
        const preferredRewriteId =
          rewriteIdFromQuery &&
          completedRewrites.some((item) => item.id === rewriteIdFromQuery)
            ? rewriteIdFromQuery
            : completedRewrites[0].id;
        setSelectedRewriteId(preferredRewriteId);

        const next = new URLSearchParams(searchParams);
        next.set("rewrite_id", String(preferredRewriteId));
        setSearchParams(next, { replace: true });
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
      setStreamMessage(coversText.loadFailed);
    }
  };

  const closeCurrentStream = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
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

  const handleGenerateCover = async () => {
    let rewriteId = selectedRewriteId;

    if (coverSourceMode === "manual") {
      const title = manualTitle.trim();
      const content = manualContent.trim();
      if (title.length < 2) {
        setStreamStatus("error");
        setStreamMessage(coversText.needManualTitle);
        return;
      }
      if (content.length < 20) {
        setStreamStatus("error");
        setStreamMessage(coversText.needManualContent);
        return;
      }

      try {
        setStreamStatus("running");
        setStreamMessage(coversText.manualCreateStart);
        const created = await createManualCoverRewrite({ title, content });
        rewriteId = created.rewrite_id;
        setSelectedRewriteId(created.rewrite_id);
        syncRewriteQuery(created.rewrite_id);
        setRewrites((previous) => {
          const next = previous.filter((item) => item.id !== created.rewrite_id);
          return [
            {
              id: created.rewrite_id,
              source_article: created.title,
              final_content: created.content_excerpt,
              style_id: 0,
              target_words: 0,
              actual_words: created.content_excerpt.length,
              enable_rag: false,
              rag_top_k: 0,
              status: "completed",
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
            ...next,
          ];
        });
      } catch (error) {
        const detail =
          error instanceof Error ? error.message : coversText.manualCreateFailed;
        setStreamStatus("error");
        setStreamMessage(detail || coversText.manualCreateFailed);
        return;
      }
    }

    if (!rewriteId) {
      setStreamStatus("error");
      setStreamMessage(coversText.needArticle);
      return;
    }
    if (promptMode === "style" && !selectedStyleId) {
      setStreamStatus("error");
      setStreamMessage(coversText.needStyle);
      return;
    }
    if (promptMode === "custom" && !customPrompt.trim()) {
      setStreamStatus("error");
      setStreamMessage(coversText.needPrompt);
      return;
    }

    closeCurrentStream();

    const request: CoverRequest = {
      rewrite_id: rewriteId,
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
    setStreamMessage(coversText.startTask);

    eventSourceRef.current = coverWithStream(
      request,
      (event) => {
        const message =
          String(event.message || "").trim() ||
          stageLabel[event.type] ||
          coversText.processing;
        setStreamStatus("running");
        setStreamMessage(message);
      },
      (errorMessage) => {
        setIsGenerating(false);
        setStreamStatus("error");
        setStreamMessage(errorMessage || coversText.generateFailed);
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
            setStreamMessage(coversText.generatedNoResult);
            return;
          }

          setCovers((previous) => {
            const nextMap = new Map(previous);
            nextMap.set(cover.rewrite_id, cover);
            return nextMap;
          });
          setSelectedRewriteId(cover.rewrite_id);
          syncRewriteQuery(cover.rewrite_id);
          setStreamStatus("success");
          setStreamMessage(coversText.generatedOk);
        } catch (error) {
          console.error("获取封面结果失败:", error);
          setStreamStatus("error");
          setStreamMessage(coversText.generatedReadFailed);
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
      setStreamMessage(tf(coversText.styleCreated, { name: created.name }));
    } catch (error) {
      console.error("创建封面风格失败:", error);
      setStreamStatus("error");
      setStreamMessage(coversText.styleCreateFailed);
    } finally {
      setIsCreatingStyle(false);
    }
  };

  const handleDeleteStyle = async (style: CoverStyle) => {
    const confirmed = window.confirm(
      tf(coversText.styleDeleteConfirm, { name: style.name }),
    );
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
      setStreamMessage(tf(coversText.styleDeleted, { name: style.name }));
    } catch (error) {
      console.error("删除封面风格失败:", error);
      setStreamStatus("error");
      setStreamMessage(coversText.styleDeleteFailed);
    }
  };

  const downloadCover = () => {
    if (!selectedCover?.image_url) {
      return;
    }
    const resolvedUrl = resolveImageUrl(selectedCover.image_url);
    if (!resolvedUrl) {
      return;
    }
    const link = document.createElement("a");
    link.href = resolvedUrl;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.click();
  };

  const canGenerate =
    !isGenerating &&
    !(
      coverSourceMode === "rewrite" &&
      !selectedRewriteId
    ) &&
    !(
      coverSourceMode === "manual" &&
      (manualTitle.trim().length < 2 || manualContent.trim().length < 20)
    ) &&
    !(promptMode === "style" && !selectedStyleId) &&
    !(promptMode === "custom" && !customPrompt.trim());

  return (
    <div className="covers-v2-page">
      <AppTopNav />

      <main className="covers-v2-main">
        <section className="covers-v2-config">
          <div className="covers-v2-title">
            <h1>{coversText.pageTitle}</h1>
            <p>{coversText.pageSubtitle}</p>
          </div>

          <div className="covers-v2-field">
            <label>{coversText.sourceLabel}</label>
            <div className="covers-v2-source-grid">
              <button
                className={coverSourceMode === "rewrite" ? "active" : ""}
                onClick={() => setCoverSourceMode("rewrite")}
                type="button"
              >
                {coversText.sourceRewrite}
              </button>
              <button
                className={coverSourceMode === "manual" ? "active" : ""}
                onClick={() => setCoverSourceMode("manual")}
                type="button"
              >
                {coversText.sourceManual}
              </button>
            </div>
          </div>

          {coverSourceMode === "rewrite" ? (
            <div className="covers-v2-field">
              <label>{coversText.targetArticle}</label>
              <select
                value={selectedRewriteId || ""}
                onChange={(event) => {
                  const rewriteId = event.target.value
                    ? Number(event.target.value)
                    : null;
                  setSelectedRewriteId(rewriteId);
                  syncRewriteQuery(rewriteId);
                }}
              >
                <option value="">{coversText.chooseArticle}</option>
                {rewrites.map((rewrite) => (
                  <option key={rewrite.id} value={rewrite.id}>
                    #{rewrite.id} - {summarize(rewrite.source_article)}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <>
              <div className="covers-v2-field">
                <label>{coversText.manualTitleLabel}</label>
                <input
                  value={manualTitle}
                  onChange={(event) => setManualTitle(event.target.value)}
                  placeholder={coversText.manualTitlePlaceholder}
                />
              </div>
              <div className="covers-v2-field">
                <label>{coversText.manualContentLabel}</label>
                <textarea
                  value={manualContent}
                  onChange={(event) => setManualContent(event.target.value)}
                  placeholder={coversText.manualContentPlaceholder}
                />
              </div>
            </>
          )}

          <div className="covers-v2-field">
            <label>{coversText.modeLabel}</label>
            <div className="covers-v2-mode-grid">
              <button
                className={promptMode === "auto" ? "active" : ""}
                onClick={() => setPromptMode("auto")}
                type="button"
              >
                {coversText.modeAuto}
              </button>
              <button
                className={promptMode === "style" ? "active" : ""}
                onClick={() => setPromptMode("style")}
                type="button"
              >
                {coversText.modeStyle}
              </button>
              <button
                className={promptMode === "custom" ? "active" : ""}
                onClick={() => setPromptMode("custom")}
                type="button"
              >
                {coversText.modeCustom}
              </button>
            </div>
          </div>

          {promptMode === "style" && (
            <div className="covers-v2-field">
              <div className="covers-v2-inline-header">
                <label>{coversText.styleLabel}</label>
                <button
                  className="ghost-btn"
                  onClick={() => setShowStyleModal(true)}
                  type="button"
                >
                  <Plus size={14} />
                  {tx("新建", "New")}
                </button>
              </div>
              {coverStyles.length === 0 ? (
                <div className="covers-v2-empty-tips">{tx("暂无风格，请先创建", "No styles yet. Create one first.")}</div>
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
              <label>{coversText.customPrompt}</label>
              <textarea
                value={customPrompt}
                onChange={(event) => setCustomPrompt(event.target.value)}
                placeholder={coversText.customPromptPlaceholder}
              />
            </div>
          )}

          <div className="covers-v2-field">
            <label>{coversText.ratioLabel}</label>
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
            <span>{isGenerating ? coversText.generateLoading : coversText.generate}</span>
          </button>
        </section>

        <section className="covers-v2-preview">
          <div className="covers-v2-preview-header">
            <div>
              <h2>{tx("预览", "Preview")}</h2>
            </div>
            <div className="covers-v2-actions">
              <button
                type="button"
                className="ghost-btn"
                onClick={downloadCover}
                disabled={!selectedCover?.image_url}
                aria-label={coversText.downloadImage}
              >
                <Download size={14} />
                {tx("下载", "Download")}
              </button>
              <button
                type="button"
                className="ghost-btn"
                onClick={() => {
                  if (selectedRewriteId) {
                    navigate(`/layout?rewrite_id=${selectedRewriteId}`);
                  }
                }}
                disabled={!selectedRewriteId}
              >
                {coversText.goToLayout}
              </button>
              <button
                type="button"
                className="ghost-btn"
                onClick={handleGenerateCover}
                disabled={!canGenerate}
                aria-label={coversText.regenerate}
              >
                <RefreshCw size={14} />
                {coversText.regenerate}
              </button>
              <button
                type="button"
                className="ghost-btn"
                disabled
                title={coversText.saveMaterialSoon}
              >
                {tx("保存至素材库", "Save to Materials")}
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
              <img src={resolveImageUrl(selectedCover.image_url)} alt={coversText.coverPreview} />
            ) : (
              <div className="covers-v2-preview-placeholder">
                <ImageIcon size={40} />
                <p>
                  {coverSourceMode === "manual"
                    ? coversText.manualHint
                    : tx("请选择文章并生成封面", "Select an article and generate a cover")}
                </p>
              </div>
            )}
          </div>

          <div className="covers-v2-history">
            <div className="covers-v2-inline-header">
              <h3>{tx("最近生成", "Recent Covers")}</h3>
              <span>{orderedCoverHistory.length} {tx("张", "items")}</span>
            </div>
            {orderedCoverHistory.length === 0 ? (
              <div className="covers-v2-empty-tips">{tx("暂无封面历史", "No cover history yet")}</div>
            ) : (
              <div className="covers-v2-history-list">
                {orderedCoverHistory.map((cover) => (
                  <button
                    key={cover.id}
                    type="button"
                    className={`covers-v2-history-item ${selectedRewriteId === cover.rewrite_id ? "active" : ""}`}
                    onClick={() => {
                      setSelectedRewriteId(cover.rewrite_id);
                      syncRewriteQuery(cover.rewrite_id);
                    }}
                    title={tx(`文章 #${cover.rewrite_id}`, `Article #${cover.rewrite_id}`)}
                  >
                    {cover.image_url ? (
                      <img
                        src={resolveImageUrl(cover.image_url)}
                        alt={tx(`封面 #${cover.rewrite_id}`, `Cover #${cover.rewrite_id}`)}
                      />
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
            {tx("封面风格管理", "Cover Style Management")}
          </h3>
          <button
            className="ghost-btn"
            onClick={() => setShowStyleModal(true)}
            type="button"
          >
            <Plus size={14} />
            {tx("新建风格", "New Style")}
          </button>
        </div>
        {coverStyles.length === 0 ? (
          <div className="covers-v2-empty-tips">
            {tx("暂无封面风格，点击右上角创建。", "No cover styles yet. Click top-right to create one.")}
          </div>
        ) : (
          <div className="covers-v2-style-grid">
            {coverStyles.map((style) => (
              <article key={style.id} className="covers-v2-style-card">
                <div className="covers-v2-style-card-head">
                  <h4>{style.name}</h4>
                  <button
                    type="button"
                    onClick={() => handleDeleteStyle(style)}
                    aria-label={tx(`删除风格：${style.name}`, `Delete style: ${style.name}`)}
                    className="icon-btn"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <p>{style.description || coversText.noDescription}</p>
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
            aria-label={coversText.createStyleAria}
          >
            <h3>{tx("新建封面风格", "Create Cover Style")}</h3>
            <label>
              {tx("风格名称", "Style Name")}
              <input
                value={newStyleName}
                onChange={(event) => setNewStyleName(event.target.value)}
                placeholder={coversText.styleNamePlaceholder}
              />
            </label>
            <label>
              {tx("提示词模板", "Prompt Template")}
              <textarea
                value={newStylePrompt}
                onChange={(event) => setNewStylePrompt(event.target.value)}
                placeholder={coversText.stylePromptPlaceholder}
              />
            </label>
            <label>
              {tx("描述（可选）", "Description (Optional)")}
              <input
                value={newStyleDesc}
                onChange={(event) => setNewStyleDesc(event.target.value)}
                placeholder={coversText.styleDescPlaceholder}
              />
            </label>
            <div className="covers-v2-modal-actions">
              <button
                type="button"
                className="ghost-btn"
                onClick={() => setShowStyleModal(false)}
              >
                {tx("取消", "Cancel")}
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
                    {tx("创建中...", "Creating...")}
                  </>
                ) : (
                  coversText.createStyle
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
