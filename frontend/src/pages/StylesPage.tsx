import React, { useEffect, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Eye,
  Loader2,
  Minus,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { AppTopNav } from "../components";
import {
  deleteStyle,
  extractStyleWithStream,
  getStyles,
  updateStyle,
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

interface StyleEditForm {
  name: string;
  tags: string;
  example_text: string;
  persona: string;
  thinking_pattern: string;
  opening_pattern: string;
  transition_pattern: string;
  sentence_rhythm: string;
  vocabulary: string;
  rhetorical_devices: string;
  ending_pattern: string;
  format_layout: string;
  signature_moves: string;
  anti_ai_features: string;
  overall_summary: string;
  paragraph_viewpoint: string;
  paragraph_example: string;
  paragraph_transition: string;
  paragraph_closing: string;
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

const createEmptyEditForm = (): StyleEditForm => ({
  name: "",
  tags: "",
  example_text: "",
  persona: "",
  thinking_pattern: "",
  opening_pattern: "",
  transition_pattern: "",
  sentence_rhythm: "",
  vocabulary: "",
  rhetorical_devices: "",
  ending_pattern: "",
  format_layout: "",
  signature_moves: "",
  anti_ai_features: "",
  overall_summary: "",
  paragraph_viewpoint: "",
  paragraph_example: "",
  paragraph_transition: "",
  paragraph_closing: "",
});

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

const styleToEditForm = (style: WritingStyle): StyleEditForm => {
  const parsed = parseStyleDescription(style.style_description) || {};
  const templates = parsed.paragraph_templates || {};

  return {
    name: style.name || "",
    tags: style.tags || "",
    example_text: style.example_text || style.sample_content || "",
    persona: parsed.persona || "",
    thinking_pattern: parsed.thinking_pattern || "",
    opening_pattern: parsed.opening_pattern || "",
    transition_pattern: parsed.transition_pattern || "",
    sentence_rhythm: parsed.sentence_rhythm || "",
    vocabulary: parsed.vocabulary || "",
    rhetorical_devices: parsed.rhetorical_devices || "",
    ending_pattern: parsed.ending_pattern || "",
    format_layout: parsed.format_layout || "",
    signature_moves: Array.isArray(parsed.signature_moves)
      ? parsed.signature_moves.join("\n")
      : "",
    anti_ai_features: parsed.anti_ai_features || "",
    overall_summary: parsed.overall_summary || "",
    paragraph_viewpoint: templates["观点段"] || "",
    paragraph_example: templates["举例段"] || "",
    paragraph_transition: templates["转折段"] || "",
    paragraph_closing: templates["收尾段"] || "",
  };
};

const editFormToStyleDescription = (form: StyleEditForm): string => {
  const signatureMoves = form.signature_moves
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);

  const payload: StyleDescription = {
    persona: form.persona.trim(),
    thinking_pattern: form.thinking_pattern.trim(),
    opening_pattern: form.opening_pattern.trim(),
    transition_pattern: form.transition_pattern.trim(),
    sentence_rhythm: form.sentence_rhythm.trim(),
    vocabulary: form.vocabulary.trim(),
    rhetorical_devices: form.rhetorical_devices.trim(),
    ending_pattern: form.ending_pattern.trim(),
    format_layout: form.format_layout.trim(),
    signature_moves: signatureMoves,
    anti_ai_features: form.anti_ai_features.trim(),
    paragraph_templates: {
      观点段: form.paragraph_viewpoint.trim(),
      举例段: form.paragraph_example.trim(),
      转折段: form.paragraph_transition.trim(),
      收尾段: form.paragraph_closing.trim(),
    },
    overall_summary: form.overall_summary.trim(),
  };

  return JSON.stringify(payload, null, 2);
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

  const [showEditModal, setShowEditModal] = useState(false);
  const [editForm, setEditForm] = useState<StyleEditForm>(createEmptyEditForm());
  const [editError, setEditError] = useState("");
  const [isSavingEdit, setIsSavingEdit] = useState(false);

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

  const loadStyles = async (preferredId?: number | null) => {
    try {
      const data = await getStyles();
      setStyles(data);
      setSelectedStyleId((prev) => {
        const candidate = preferredId ?? prev;
        if (candidate && data.some((item) => item.id === candidate)) {
          return candidate;
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

  const openEditModal = (style: WritingStyle) => {
    setSelectedStyleId(style.id);
    setEditForm(styleToEditForm(style));
    setEditError("");
    setShowEditModal(true);
  };

  const closeEditModal = () => {
    if (isSavingEdit) {
      return;
    }
    setShowEditModal(false);
  };

  const updateEditField = (key: keyof StyleEditForm, value: string) => {
    setEditForm((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleSaveEdit = async () => {
    if (!selectedStyleId) {
      return;
    }

    if (!editForm.name.trim()) {
      setEditError("风格名称不能为空");
      return;
    }

    setIsSavingEdit(true);
    setEditError("");

    try {
      await updateStyle(selectedStyleId, {
        name: editForm.name.trim(),
        tags: editForm.tags.trim() || undefined,
        example_text: editForm.example_text.trim() || undefined,
        style_description: editFormToStyleDescription(editForm),
      });

      await loadStyles(selectedStyleId);
      setShowEditModal(false);
    } catch (error) {
      console.error("更新风格失败:", error);
      setEditError(error instanceof Error ? error.message : "更新失败，请重试");
    } finally {
      setIsSavingEdit(false);
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
                        openEditModal(style);
                      }}
                    >
                      <Pencil size={13} /> 编辑
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
                  <p>
                    创建于 {new Date(selectedStyle.created_at).toLocaleString("zh-CN")}
                    {selectedStyle.updated_at
                      ? ` · 更新于 ${new Date(selectedStyle.updated_at).toLocaleString("zh-CN")}`
                      : ""}
                  </p>
                </div>
                <div className="styles-v2-detail-actions">
                  <div className="styles-v2-detail-tags">
                    <span>
                      <Sparkles size={12} />
                      可用于改写
                    </span>
                  </div>
                  <button
                    type="button"
                    className="styles-v2-secondary-btn"
                    onClick={() => openEditModal(selectedStyle)}
                  >
                    <Pencil size={13} /> 编辑风格
                  </button>
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

              {(selectedStyle.example_text || selectedStyle.sample_content) && (
                <div className="styles-v2-sample-block">
                  <h3>示例内容</h3>
                  <pre>{selectedStyle.example_text || selectedStyle.sample_content}</pre>
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

      {showEditModal && (
        <div className="styles-v2-modal-mask" onClick={closeEditModal}>
          <div className="styles-v2-modal styles-v2-edit-modal" onClick={(event) => event.stopPropagation()}>
            <h3>编辑风格</h3>

            <div className="styles-v2-edit-grid">
              <label className="styles-v2-edit-field">
                风格名称
                <input
                  value={editForm.name}
                  onChange={(event) => updateEditField("name", event.target.value)}
                  placeholder="请输入风格名称"
                />
              </label>
              <label className="styles-v2-edit-field">
                标签
                <input
                  value={editForm.tags}
                  onChange={(event) => updateEditField("tags", event.target.value)}
                  placeholder="例如：技术,口语化,故事感"
                />
              </label>
              <label className="styles-v2-edit-field styles-v2-edit-field-wide">
                示例文本
                <textarea
                  value={editForm.example_text}
                  onChange={(event) => updateEditField("example_text", event.target.value)}
                  placeholder="可选：用于补充风格样本"
                />
              </label>
            </div>

            <h4 className="styles-v2-edit-section-title">十二维风格字段</h4>
            <div className="styles-v2-edit-grid">
              <label className="styles-v2-edit-field">
                人设定位
                <textarea
                  value={editForm.persona}
                  onChange={(event) => updateEditField("persona", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                思维模式
                <textarea
                  value={editForm.thinking_pattern}
                  onChange={(event) => updateEditField("thinking_pattern", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                开头模式
                <textarea
                  value={editForm.opening_pattern}
                  onChange={(event) => updateEditField("opening_pattern", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                过渡模式
                <textarea
                  value={editForm.transition_pattern}
                  onChange={(event) => updateEditField("transition_pattern", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                句子节奏
                <textarea
                  value={editForm.sentence_rhythm}
                  onChange={(event) => updateEditField("sentence_rhythm", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                用词特点
                <textarea
                  value={editForm.vocabulary}
                  onChange={(event) => updateEditField("vocabulary", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                修辞手法
                <textarea
                  value={editForm.rhetorical_devices}
                  onChange={(event) => updateEditField("rhetorical_devices", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                结尾模式
                <textarea
                  value={editForm.ending_pattern}
                  onChange={(event) => updateEditField("ending_pattern", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                格式布局
                <textarea
                  value={editForm.format_layout}
                  onChange={(event) => updateEditField("format_layout", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                标志性手法（每行一条）
                <textarea
                  value={editForm.signature_moves}
                  onChange={(event) => updateEditField("signature_moves", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                反 AI 特征
                <textarea
                  value={editForm.anti_ai_features}
                  onChange={(event) => updateEditField("anti_ai_features", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                整体总结
                <textarea
                  value={editForm.overall_summary}
                  onChange={(event) => updateEditField("overall_summary", event.target.value)}
                />
              </label>
            </div>

            <h4 className="styles-v2-edit-section-title">段落模板</h4>
            <div className="styles-v2-edit-grid">
              <label className="styles-v2-edit-field">
                观点段
                <textarea
                  value={editForm.paragraph_viewpoint}
                  onChange={(event) => updateEditField("paragraph_viewpoint", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                举例段
                <textarea
                  value={editForm.paragraph_example}
                  onChange={(event) => updateEditField("paragraph_example", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                转折段
                <textarea
                  value={editForm.paragraph_transition}
                  onChange={(event) => updateEditField("paragraph_transition", event.target.value)}
                />
              </label>
              <label className="styles-v2-edit-field">
                收尾段
                <textarea
                  value={editForm.paragraph_closing}
                  onChange={(event) => updateEditField("paragraph_closing", event.target.value)}
                />
              </label>
            </div>

            {editError && <div className="styles-v2-edit-error">{editError}</div>}

            <div className="styles-v2-modal-actions">
              <button type="button" className="ghost" onClick={closeEditModal} disabled={isSavingEdit}>
                取消
              </button>
              <button
                type="button"
                className="primary"
                onClick={handleSaveEdit}
                disabled={isSavingEdit || !editForm.name.trim()}
              >
                {isSavingEdit ? (
                  <>
                    <Loader2 size={14} className="spin" /> 保存中...
                  </>
                ) : (
                  "保存风格"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
