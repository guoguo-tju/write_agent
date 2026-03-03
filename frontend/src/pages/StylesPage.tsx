import React, { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  Loader2,
  Minus,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { AppTopNav } from "../components";
import {
  deleteStyle,
  extractStyleWithStream,
  getStyles,
  type WritingStyle,
} from "../services/api";
import "./StylesPage.css";

interface StyleDescription {
  persona?: string;
  thinking_pattern?: string;
  opening_pattern?: string;
  transition_pattern?: string;
  sentence_rhythm?: string;
  vocabulary?: string;
  rhetorical_devices?: string;
  ending_pattern?: string;
  format_layout?: string;
  signature_moves?: string[];
  anti_ai_features?: string;
  paragraph_templates?: Record<string, string | undefined>;
  overall_summary?: string;
}

const STYLE_SECTION_CONFIG: Array<{ key: keyof StyleDescription; label: string }> = [
  { key: "persona", label: "人设定位" },
  { key: "thinking_pattern", label: "思维模式" },
  { key: "opening_pattern", label: "开头模式" },
  { key: "transition_pattern", label: "过渡模式" },
  { key: "sentence_rhythm", label: "句子节奏" },
  { key: "vocabulary", label: "用词特点" },
  { key: "rhetorical_devices", label: "修辞手法" },
  { key: "ending_pattern", label: "结尾模式" },
  { key: "format_layout", label: "格式布局" },
  { key: "signature_moves", label: "标志性手法" },
  { key: "anti_ai_features", label: "反 AI 特征" },
  { key: "overall_summary", label: "整体总结" },
];

const formatTime = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const summarize = (value: string, maxLength = 54) => {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}...`;
};

const parseStyleDescription = (raw?: string): StyleDescription | null => {
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as StyleDescription;
  } catch {
    return null;
  }
};

const getStyleSummary = (style: WritingStyle) => {
  const parsed = parseStyleDescription(style.style_description);
  if (parsed?.overall_summary) {
    return summarize(parsed.overall_summary, 70);
  }
  if (style.tone) {
    return style.tone;
  }
  if (style.visual_style) {
    return style.visual_style;
  }
  if (style.language_characteristics) {
    return summarize(style.language_characteristics, 70);
  }
  return "暂无摘要";
};

export const StylesPage: React.FC = () => {
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [selectedStyleId, setSelectedStyleId] = useState<number | null>(null);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newStyleName, setNewStyleName] = useState("");
  const [newStyleArticles, setNewStyleArticles] = useState<string[]>([""]);
  const [extractStatus, setExtractStatus] = useState("");
  const [extractPreview, setExtractPreview] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);

  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set([
      "persona",
      "thinking_pattern",
      "opening_pattern",
      "transition_pattern",
      "sentence_rhythm",
      "vocabulary",
      "rhetorical_devices",
      "ending_pattern",
      "format_layout",
      "signature_moves",
      "anti_ai_features",
      "paragraph_templates",
      "overall_summary",
    ]),
  );

  useEffect(() => {
    void loadStyles();
  }, []);

  const selectedStyle = useMemo(
    () => styles.find((item) => item.id === selectedStyleId) || null,
    [styles, selectedStyleId],
  );

  const loadStyles = async () => {
    try {
      const data = await getStyles();
      setStyles(data);
      setSelectedStyleId((prev) => {
        if (prev && data.some((item) => item.id === prev)) {
          return prev;
        }
        return data[0]?.id ?? null;
      });
    } catch (error) {
      console.error("加载风格失败:", error);
    }
  };

  const openCreateModal = () => {
    setShowCreateModal(true);
    setExtractStatus("");
    setExtractPreview("");
    if (newStyleArticles.length === 0) {
      setNewStyleArticles([""]);
    }
  };

  const closeCreateModal = () => {
    if (isExtracting) {
      return;
    }
    setShowCreateModal(false);
  };

  const updateArticle = (index: number, value: string) => {
    setNewStyleArticles((prev) => {
      const next = [...prev];
      next[index] = value;
      return next;
    });
  };

  const addArticleInput = (afterIndex: number) => {
    setNewStyleArticles((prev) => {
      const next = [...prev];
      next.splice(afterIndex + 1, 0, "");
      return next;
    });
  };

  const removeArticleInput = (index: number) => {
    setNewStyleArticles((prev) => {
      if (prev.length <= 1) {
        return [""];
      }
      return prev.filter((_, currentIndex) => currentIndex !== index);
    });
  };

  const handleExtract = async () => {
    const styleName = newStyleName.trim();
    const articles = newStyleArticles.map((item) => item.trim()).filter(Boolean);

    if (!styleName || articles.length === 0) {
      return;
    }

    setIsExtracting(true);
    setExtractStatus("正在启动风格分析...");
    setExtractPreview("");

    try {
      await extractStyleWithStream(
        {
          style_name: styleName,
          articles,
        },
        {
          onStart: (data) => {
            const count = Number(data.articles_count || articles.length);
            setExtractStatus(`已接收 ${count} 篇参考文章，开始分析...`);
          },
          onProgress: (data) => {
            setExtractStatus(String(data.message || "正在提炼写作特征..."));
          },
          onChunk: (delta) => {
            setExtractPreview((prev) => (prev + delta).slice(-4500));
          },
        },
      );

      await loadStyles();
      setShowCreateModal(false);
      setNewStyleName("");
      setNewStyleArticles([""]);
      setExtractStatus("");
      setExtractPreview("");
    } catch (error) {
      console.error("提取风格失败:", error);
      setExtractStatus(error instanceof Error ? error.message : "提取失败");
    } finally {
      setIsExtracting(false);
    }
  };

  const handleDelete = async (style: WritingStyle) => {
    const confirmed = window.confirm(`确定删除风格“${style.name}”吗？`);
    if (!confirmed) {
      return;
    }

    try {
      await deleteStyle(style.id);
      await loadStyles();
    } catch (error) {
      console.error("删除风格失败:", error);
    }
  };

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  const renderDescriptionSection = (
    label: string,
    sectionKey: string,
    value: string | string[] | undefined,
  ) => {
    if (!value) {
      return null;
    }

    const expanded = expandedSections.has(sectionKey);
    const isArray = Array.isArray(value);

    return (
      <div className="styles-v2-detail-section" key={sectionKey}>
        <button
          type="button"
          className="styles-v2-detail-toggle"
          onClick={() => toggleSection(sectionKey)}
        >
          <span>{label}</span>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        {expanded && (
          <div className="styles-v2-detail-content">
            {isArray ? (
              <ul>
                {value.map((item, index) => (
                  <li key={`${sectionKey}-${index}`}>{item}</li>
                ))}
              </ul>
            ) : (
              <p>{value}</p>
            )}
          </div>
        )}
      </div>
    );
  };

  const parsedDescription = parseStyleDescription(selectedStyle?.style_description);

  return (
    <div className="styles-v2-page">
      <AppTopNav />

      <main className="styles-v2-main">
        <aside className="styles-v2-sidebar">
          <div className="styles-v2-sidebar-head">
            <div>
              <h1>我的风格</h1>
              <p>管理并复用写作风格 DNA</p>
            </div>
            <button type="button" className="styles-v2-create-btn" onClick={openCreateModal}>
              <Plus size={14} />
              创建新风格
            </button>
          </div>

          <div className="styles-v2-list">
            {styles.length === 0 ? (
              <div className="styles-v2-empty">暂无风格，点击上方按钮创建。</div>
            ) : (
              styles.map((style) => (
                <article
                  key={style.id}
                  className={`styles-v2-item ${selectedStyleId === style.id ? "active" : ""}`}
                  onClick={() => setSelectedStyleId(style.id)}
                >
                  <div className="styles-v2-item-header">
                    <h3>{style.name}</h3>
                    <span>{formatTime(style.created_at)}</span>
                  </div>
                  <p>{getStyleSummary(style)}</p>
                  <div className="styles-v2-item-actions">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedStyleId(style.id);
                      }}
                    >
                      <Eye size={13} /> 查看
                    </button>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleDelete(style);
                      }}
                    >
                      <Trash2 size={13} /> 删除
                    </button>
                  </div>
                </article>
              ))
            )}
          </div>
        </aside>

        <section className="styles-v2-detail">
          {selectedStyle ? (
            <>
              <div className="styles-v2-detail-head">
                <div>
                  <h2>{selectedStyle.name}</h2>
                  <p>创建于 {new Date(selectedStyle.created_at).toLocaleString("zh-CN")}</p>
                </div>
                <div className="styles-v2-detail-tags">
                  <span>
                    <Sparkles size={12} />
                    可用于改写
                  </span>
                </div>
              </div>

              <div className="styles-v2-detail-meta-grid">
                {selectedStyle.tone && (
                  <div>
                    <label>语气</label>
                    <p>{selectedStyle.tone}</p>
                  </div>
                )}
                {selectedStyle.article_type && (
                  <div>
                    <label>文章类型</label>
                    <p>{selectedStyle.article_type}</p>
                  </div>
                )}
                {selectedStyle.target_audience && (
                  <div>
                    <label>目标读者</label>
                    <p>{selectedStyle.target_audience}</p>
                  </div>
                )}
                {selectedStyle.language_characteristics && (
                  <div>
                    <label>语言特点</label>
                    <p>{selectedStyle.language_characteristics}</p>
                  </div>
                )}
              </div>

              {parsedDescription ? (
                <div className="styles-v2-detail-sections">
                  {STYLE_SECTION_CONFIG.map((section) =>
                    renderDescriptionSection(
                      section.label,
                      section.key,
                      parsedDescription[section.key] as string | string[] | undefined,
                    ),
                  )}

                  {parsedDescription.paragraph_templates &&
                    Object.keys(parsedDescription.paragraph_templates).length > 0 && (
                      <div className="styles-v2-detail-section">
                        <button
                          type="button"
                          className="styles-v2-detail-toggle"
                          onClick={() => toggleSection("paragraph_templates")}
                        >
                          <span>段落模板</span>
                          {expandedSections.has("paragraph_templates") ? (
                            <ChevronDown size={14} />
                          ) : (
                            <ChevronRight size={14} />
                          )}
                        </button>
                        {expandedSections.has("paragraph_templates") && (
                          <div className="styles-v2-detail-content">
                            <ul>
                              {Object.entries(parsedDescription.paragraph_templates)
                                .filter(([, value]) => Boolean(value))
                                .map(([key, value]) => (
                                  <li key={key}>
                                    <strong>{key}：</strong>
                                    {value}
                                  </li>
                                ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                </div>
              ) : (
                <div className="styles-v2-empty">暂无结构化风格详情。</div>
              )}

              {selectedStyle.sample_content && (
                <div className="styles-v2-sample-block">
                  <h3>示例内容</h3>
                  <pre>{selectedStyle.sample_content}</pre>
                </div>
              )}
            </>
          ) : (
            <div className="styles-v2-empty styles-v2-detail-empty">
              请选择一个风格查看详情
            </div>
          )}
        </section>
      </main>

      {showCreateModal && (
        <div className="styles-v2-modal-mask" onClick={closeCreateModal}>
          <div className="styles-v2-modal" onClick={(event) => event.stopPropagation()}>
            <h3>提炼新风格</h3>
            <label>
              风格名称
              <input
                value={newStyleName}
                onChange={(event) => setNewStyleName(event.target.value)}
                placeholder="例如：简洁洞察、故事型口播、技术报告"
              />
            </label>

            <div className="styles-v2-article-list">
              {newStyleArticles.map((article, index) => (
                <div key={`article-${index}`} className="styles-v2-article-item">
                  <div className="styles-v2-article-head">
                    <span>参考文章 {index + 1}</span>
                    <div>
                      <button
                        type="button"
                        onClick={() => addArticleInput(index)}
                        disabled={isExtracting}
                      >
                        <Plus size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => removeArticleInput(index)}
                        disabled={isExtracting || newStyleArticles.length <= 1}
                      >
                        <Minus size={13} />
                      </button>
                    </div>
                  </div>
                  <textarea
                    value={article}
                    onChange={(event) => updateArticle(index, event.target.value)}
                    placeholder="粘贴该风格的代表文章..."
                  />
                </div>
              ))}
            </div>

            {(isExtracting || extractStatus || extractPreview) && (
              <div className="styles-v2-stream-box">
                <div className="styles-v2-stream-status">
                  {isExtracting && <Loader2 size={14} className="spin" />}
                  <span>{extractStatus || "准备中..."}</span>
                </div>
                {extractPreview && <pre>{extractPreview}</pre>}
              </div>
            )}

            <div className="styles-v2-modal-actions">
              <button type="button" className="ghost" onClick={closeCreateModal} disabled={isExtracting}>
                取消
              </button>
              <button
                type="button"
                className="primary"
                onClick={handleExtract}
                disabled={
                  isExtracting ||
                  !newStyleName.trim() ||
                  newStyleArticles.every((article) => !article.trim())
                }
              >
                {isExtracting ? "提炼中..." : "开始提炼"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
