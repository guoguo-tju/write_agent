import React, { useEffect, useMemo, useState } from "react";
import { FilePlus2, Search, Trash2, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { AppTopNav, Pagination } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  addMaterial,
  deleteMaterial,
  getMaterial,
  getMaterialsPage,
  retrieveMaterials,
  updateMaterial,
  type Material,
  type RagRetrievedItem,
} from "../services/api";
import "./MaterialsPage.css";

const PAGE_SIZE = 10;
const RETRIEVE_TOP_K_OPTIONS = [3, 5, 8];
const ALL_TAG = "__all__";

type MaterialInputMode = "text" | "link";
type SourcePlatform = "none" | "wechat" | "twitter" | "generic" | "invalid";

const summarize = (value: string, maxLength = 170) => {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}...`;
};

const formatDate = (value: string, locale = "zh-CN") => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  return date.toLocaleString(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const splitTags = (tags?: string) =>
  (tags || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);

const extractErrorMessage = (
  error: unknown,
  fallbackMessage: string,
): string => {
  if (typeof error === "object" && error !== null) {
    const maybeResponse = error as {
      response?: { data?: { detail?: string } };
      message?: string;
    };
    if (maybeResponse.response?.data?.detail) {
      return maybeResponse.response.data.detail;
    }
    if (maybeResponse.message) {
      return maybeResponse.message;
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallbackMessage;
};

const detectSourcePlatform = (value: string): SourcePlatform => {
  const url = value.trim();
  if (!url) {
    return "none";
  }

  try {
    const parsed = new URL(url);
    const hostname = parsed.hostname.toLowerCase();
    if (hostname === "mp.weixin.qq.com") {
      return "wechat";
    }
    if (
      hostname === "x.com" ||
      hostname === "www.x.com" ||
      hostname === "twitter.com" ||
      hostname === "www.twitter.com"
    ) {
      return "twitter";
    }
    return "generic";
  } catch {
    return "invalid";
  }
};

export const MaterialsPage: React.FC = () => {
  const { lang, text } = useLanguage();
  const [searchParams, setSearchParams] = useSearchParams();
  const materialsText = text.materials;
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const tx = (zh: string, en: string) => (lang === "zh" ? zh : en);
  const tf = (template: string, vars: Record<string, string | number>) =>
    formatMessage(template, vars);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [isPageLoading, setIsPageLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  const [showModal, setShowModal] = useState(false);
  const [inputMode, setInputMode] = useState<MaterialInputMode>("text");
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newSource, setNewSource] = useState("");
  const [newTags, setNewTags] = useState("");
  const [submitError, setSubmitError] = useState("");

  const [searchKeyword, setSearchKeyword] = useState("");
  const [debouncedKeyword, setDebouncedKeyword] = useState("");
  const [activeTag, setActiveTag] = useState<string>(ALL_TAG);

  const [retrieveQuery, setRetrieveQuery] = useState("");
  const [retrieveTopK, setRetrieveTopK] = useState(5);
  const [isRetrieving, setIsRetrieving] = useState(false);
  const [hasRetrieved, setHasRetrieved] = useState(false);
  const [retrieveError, setRetrieveError] = useState("");
  const [retrieveItems, setRetrieveItems] = useState<RagRetrievedItem[]>([]);

  const [editingMaterial, setEditingMaterial] = useState<Material | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editSource, setEditSource] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editError, setEditError] = useState("");

  const detectedPlatform = useMemo(
    () => detectSourcePlatform(newSource),
    [newSource],
  );
  const detectedEditPlatform = useMemo(
    () => detectSourcePlatform(editSource),
    [editSource],
  );
  const materialIdParam = searchParams.get("material_id");

  useEffect(() => {
    const timer = setTimeout(() => {
      const nextKeyword = searchKeyword.trim();
      setDebouncedKeyword(nextKeyword);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchKeyword]);

  useEffect(() => {
    void loadMaterials(page);
  }, [page, activeTag, debouncedKeyword]);

  const allTags = useMemo(() => {
    const tagSet = new Set<string>();
    if (activeTag !== ALL_TAG) {
      tagSet.add(activeTag);
    }
    materials.forEach((item) => {
      splitTags(item.tags).forEach((tag) => tagSet.add(tag));
    });
    return [
      ALL_TAG,
      ...Array.from(tagSet).sort((left, right) => left.localeCompare(right, locale)),
    ];
  }, [activeTag, locale, materials]);

  const loadMaterials = async (requestedPage: number) => {
    setIsPageLoading(true);
    try {
      const response = await getMaterialsPage({
        page: requestedPage,
        limit: PAGE_SIZE,
        tags: activeTag === ALL_TAG ? undefined : activeTag,
        keyword: debouncedKeyword || undefined,
      });

      if (response.items.length === 0 && response.total > 0 && requestedPage > 1) {
        setPage(requestedPage - 1);
        return;
      }

      setMaterials(response.items);
      setTotal(response.total);
    } catch (error) {
      console.error("加载素材失败:", error);
    } finally {
      setIsPageLoading(false);
    }
  };

  const resetModalForm = () => {
    setInputMode("text");
    setNewTitle("");
    setNewContent("");
    setNewSource("");
    setNewTags("");
    setSubmitError("");
  };

  const closeModal = () => {
    if (isSubmitting) {
      return;
    }
    resetModalForm();
    setShowModal(false);
  };

  const handleAddMaterial = async () => {
    const normalizedContent = newContent.trim();
    const normalizedSource = newSource.trim();
    const normalizedTitle = newTitle.trim();
    const normalizedTags = newTags.trim();

    if (inputMode === "text" && !normalizedContent) {
      setSubmitError(materialsText.textModeNeedContent);
      return;
    }
    if (inputMode === "link" && !normalizedSource) {
      setSubmitError(materialsText.linkModeNeedUrl);
      return;
    }

    setSubmitError("");
    setIsSubmitting(true);
    try {
      await addMaterial({
        title: normalizedTitle || undefined,
        content: normalizedContent || undefined,
        source: normalizedSource || undefined,
        tags: normalizedTags || undefined,
      });
      if (page !== 1) {
        setPage(1);
      } else {
        await loadMaterials(1);
      }
      setShowModal(false);
      resetModalForm();
      setActiveTag(ALL_TAG);
    } catch (error) {
      console.error("添加素材失败:", error);
      setSubmitError(extractErrorMessage(error, materialsText.requestFailed));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRetrieve = async () => {
    const query = retrieveQuery.trim();
    if (!query) {
      setRetrieveError(materialsText.needQuery);
      return;
    }

    setIsRetrieving(true);
    setRetrieveError("");
    setHasRetrieved(true);
    try {
      const response = await retrieveMaterials(query, retrieveTopK);
      setRetrieveItems(response.items);
    } catch (error) {
      console.error("素材检索失败:", error);
      setRetrieveItems([]);
      setRetrieveError(extractErrorMessage(error, materialsText.requestFailed));
    } finally {
      setIsRetrieving(false);
    }
  };

  const handleDelete = async (material: Material) => {
    const confirmed = window.confirm(
      tf(materialsText.deleteConfirm, {
        name: material.title || `#${material.id}`,
      }),
    );
    if (!confirmed) {
      return;
    }

    try {
      await deleteMaterial(material.id);
      await loadMaterials(page);
    } catch (error) {
      console.error("删除素材失败:", error);
    }
  };

  const openEditModal = (material: Material) => {
    setEditingMaterial(material);
    setEditTitle(material.title || "");
    setEditContent(material.content || "");
    setEditSource(material.source_url || "");
    setEditTags(material.tags || "");
    setEditError("");
  };

  const closeEditModal = () => {
    if (isUpdating) {
      return;
    }
    setEditingMaterial(null);
    setEditTitle("");
    setEditContent("");
    setEditSource("");
    setEditTags("");
    setEditError("");
  };

  useEffect(() => {
    if (!materialIdParam) {
      return;
    }

    const materialId = Number(materialIdParam);
    if (!Number.isInteger(materialId) || materialId <= 0) {
      setSearchParams({}, { replace: true });
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        const material = await getMaterial(materialId);
        if (cancelled) {
          return;
        }
        setEditingMaterial(material);
        setEditTitle(material.title || "");
        setEditContent(material.content || "");
        setEditSource(material.source_url || "");
        setEditTags(material.tags || "");
        setEditError("");
      } catch (error) {
        console.error("加载指定素材详情失败:", error);
      } finally {
        if (!cancelled) {
          setSearchParams({}, { replace: true });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [materialIdParam, setSearchParams]);

  const handleUpdateMaterial = async () => {
    if (!editingMaterial) {
      return;
    }

    const normalizedTitle = editTitle.trim();
    const normalizedContent = editContent.trim();
    const normalizedSource = editSource.trim();
    const normalizedTags = editTags.trim();

    if (!normalizedTitle) {
      setEditError(materialsText.titleRequired);
      return;
    }
    if (!normalizedContent && !normalizedSource) {
      setEditError(materialsText.contentOrUrlRequired);
      return;
    }

    setEditError("");
    setIsUpdating(true);
    try {
      await updateMaterial(editingMaterial.id, {
        title: normalizedTitle,
        content: normalizedContent || undefined,
        source: normalizedSource || undefined,
        tags: normalizedTags || undefined,
      });
      await loadMaterials(page);
      closeEditModal();
    } catch (error) {
      console.error("更新素材失败:", error);
      setEditError(extractErrorMessage(error, materialsText.requestFailed));
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <div className="materials-v2-page">
      <AppTopNav />

      <main className="materials-v2-main">
        <aside className="materials-v2-sidebar">
          <div className="materials-v2-sidebar-head">
            <h1>{materialsText.title}</h1>
            <p>{materialsText.subtitle}</p>
          </div>

          <button className="materials-v2-create-btn" type="button" onClick={() => setShowModal(true)}>
            <FilePlus2 size={14} />
            {materialsText.addMaterial}
          </button>

          <label className="materials-v2-search">
            <Search size={14} />
            <input
              value={searchKeyword}
              onChange={(event) => setSearchKeyword(event.target.value)}
              placeholder={materialsText.searchPlaceholder}
            />
            {searchKeyword && (
              <button type="button" onClick={() => setSearchKeyword("")}>
                <X size={13} />
              </button>
            )}
          </label>

          <div className="materials-v2-tag-panel">
            <h3>{materialsText.tagFilter}</h3>
            <div className="materials-v2-tags">
              {allTags.map((tag) => (
                <button
                  type="button"
                  key={tag}
                  className={activeTag === tag ? "active" : ""}
                  onClick={() => {
                    setActiveTag(tag);
                    setPage(1);
                  }}
                >
                  {tag === ALL_TAG ? materialsText.all : tag}
                </button>
              ))}
            </div>
          </div>

          <div className="materials-v2-stats">
            <div>
              <strong>{total}</strong>
              <span>{tx("筛选总数", "Filtered Total")}</span>
            </div>
            <div>
              <strong>{materials.length}</strong>
              <span>{tx("当前页条数", "Items on Page")}</span>
            </div>
          </div>
        </aside>

        <section className="materials-v2-content">
          <div className="materials-v2-content-head">
            <h2>{tx("素材卡片", "Material Cards")}</h2>
            <span>{tf(tx("共 {{count}} 条", "{{count}} total"), { count: total })}</span>
          </div>

          <section className="materials-v2-retrieve-panel">
            <div className="materials-v2-retrieve-head">
              <h3>{materialsText.retrievalTitle}</h3>
              <span>{materialsText.retrievalSubtitle}</span>
            </div>
            <div className="materials-v2-retrieve-controls">
              <input
                value={retrieveQuery}
                onChange={(event) => setRetrieveQuery(event.target.value)}
                placeholder={materialsText.retrievalPlaceholder}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void handleRetrieve();
                  }
                }}
              />
              <select
                value={String(retrieveTopK)}
                onChange={(event) => setRetrieveTopK(Number(event.target.value))}
              >
                {RETRIEVE_TOP_K_OPTIONS.map((count) => (
                  <option key={count} value={count}>
                    Top {count}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void handleRetrieve()}
                disabled={isRetrieving}
              >
                {isRetrieving ? materialsText.retrieving : materialsText.startRetrieve}
              </button>
            </div>

            {retrieveError && <div className="materials-v2-retrieve-error">{retrieveError}</div>}

            {isRetrieving ? (
              <div className="materials-v2-retrieve-empty">{materialsText.retrieving}</div>
            ) : retrieveItems.length > 0 ? (
              <div className="materials-v2-retrieve-list">
                {retrieveItems.map((item) => (
                  <article
                    key={`${item.material_id}-${item.score}`}
                    className="materials-v2-retrieve-item"
                  >
                    <div className="materials-v2-retrieve-item-head">
                      <strong>
                        {item.title || tf(materialsText.unnamedMaterial, { id: item.material_id })}
                      </strong>
                      <span>{materialsText.scoreLabel} {(item.score * 100).toFixed(1)}%</span>
                    </div>
                    <p>{summarize(item.content, 130)}</p>
                    <div className="materials-v2-retrieve-item-meta">
                      {item.tags ? <span>{item.tags}</span> : <span>-</span>}
                      {item.source_url ? (
                        <a href={item.source_url} target="_blank" rel="noreferrer">
                          {materialsText.sourceLink}
                        </a>
                      ) : (
                        <span>-</span>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            ) : hasRetrieved ? (
              <div className="materials-v2-retrieve-empty">{materialsText.emptyRetrieve}</div>
            ) : (
              <div className="materials-v2-retrieve-empty">
                {materialsText.retrievalSubtitle}
              </div>
            )}
          </section>

          {isPageLoading ? (
            <div className="materials-v2-empty">{tx("加载中...", "Loading...")}</div>
          ) : materials.length === 0 ? (
            <div className="materials-v2-empty">
              {total === 0 ? materialsText.noMaterials : materialsText.noMaterialsInPage}
            </div>
          ) : (
            <div className="materials-v2-grid">
              {materials.map((material) => {
                const tags = splitTags(material.tags);

                return (
                  <article
                    key={material.id}
                    className="materials-v2-card materials-v2-card-clickable"
                    role="button"
                    tabIndex={0}
                    onClick={() => openEditModal(material)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openEditModal(material);
                      }
                    }}
                  >
                    <div className="materials-v2-card-head">
                      <h3>{material.title || tf(materialsText.unnamedMaterial, { id: material.id })}</h3>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleDelete(material);
                        }}
                        aria-label={tf(materialsText.deleteConfirm, {
                          name: material.title || material.id,
                        })}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    <p>{summarize(material.content)}</p>

                    {tags.length > 0 && (
                      <div className="materials-v2-card-tags">
                        {tags.map((tag) => (
                          <span key={`${material.id}-${tag}`}>#{tag}</span>
                        ))}
                      </div>
                    )}

                    <div className="materials-v2-card-meta">
                      <span>{formatDate(material.created_at, locale)}</span>
                      {material.source_url && (
                        <span>{tf(materialsText.sourcePrefix, { url: material.source_url })}</span>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          <div className="materials-v2-pagination">
            <Pagination
              page={page}
              total={total}
              limit={PAGE_SIZE}
              onPageChange={(nextPage) => setPage(nextPage)}
            />
          </div>
        </section>
      </main>

      {showModal && (
        <div className="materials-v2-modal-mask" onClick={closeModal}>
          <div className="materials-v2-modal" onClick={(event) => event.stopPropagation()}>
            <h3>{materialsText.addMaterial}</h3>
            <div className="materials-v2-mode-switch">
              <button
                type="button"
                className={inputMode === "text" ? "active" : ""}
                onClick={() => {
                  setInputMode("text");
                  setSubmitError("");
                }}
              >
                {tx("文本模式", "Text Mode")}
              </button>
              <button
                type="button"
                className={inputMode === "link" ? "active" : ""}
                onClick={() => {
                  setInputMode("link");
                  setSubmitError("");
                }}
              >
                {tx("链接模式", "Link Mode")}
              </button>
            </div>
            <label>
              {tx("标题（可选）", "Title (Optional)")}
              <input
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder={materialsText.titlePlaceholder}
              />
            </label>

            {inputMode === "text" && (
              <label>
                {tx("素材内容", "Material Content")}
                <textarea
                  value={newContent}
                  onChange={(event) => setNewContent(event.target.value)}
                  placeholder={materialsText.contentPlaceholder}
                />
              </label>
            )}

            <label>
              {inputMode === "link" ? materialsText.sourceLink : materialsText.optionalSource}
              <input
                value={newSource}
                onChange={(event) => setNewSource(event.target.value)}
                placeholder={
                  inputMode === "link"
                    ? materialsText.sourcePlaceholderLink
                    : materialsText.sourcePlaceholderOptional
                }
              />
            </label>
            {detectedPlatform !== "none" && (
              <div className={`materials-v2-platform-hint ${detectedPlatform}`}>
                {detectedPlatform === "wechat" && materialsText.sourceLinkHintWechat}
                {detectedPlatform === "twitter" && materialsText.sourceLinkHintTwitter}
                {detectedPlatform === "generic" && materialsText.sourceLinkHintGeneric}
                {detectedPlatform === "invalid" && materialsText.sourceLinkHintInvalid}
              </div>
            )}
            {inputMode === "link" && (
              <label>
                {tx("手动正文（可选，抓取失败时建议填写）", "Manual Content (Optional)")}
                <textarea
                  value={newContent}
                  onChange={(event) => setNewContent(event.target.value)}
                  placeholder={materialsText.optionalContentPlaceholder}
                />
              </label>
            )}
            <label>
              {tx("标签（可选）", "Tags (Optional)")}
              <input
                value={newTags}
                onChange={(event) => setNewTags(event.target.value)}
                placeholder={materialsText.tagsPlaceholder}
              />
            </label>
            {submitError && <div className="materials-v2-submit-error">{submitError}</div>}

            <div className="materials-v2-modal-actions">
              <button type="button" className="ghost" onClick={closeModal} disabled={isSubmitting}>
                {tx("取消", "Cancel")}
              </button>
              <button
                type="button"
                className="primary"
                onClick={handleAddMaterial}
                disabled={
                  isSubmitting ||
                  (inputMode === "text" && !newContent.trim()) ||
                  (inputMode === "link" && !newSource.trim())
                }
              >
                {isSubmitting ? materialsText.saving : materialsText.saveMaterial}
              </button>
            </div>
          </div>
        </div>
      )}

      {editingMaterial && (
        <div className="materials-v2-modal-mask" onClick={closeEditModal}>
          <div
            className="materials-v2-modal materials-v2-modal-detail"
            onClick={(event) => event.stopPropagation()}
          >
            <h3>{tx("编辑素材", "Edit Material")} #{editingMaterial.id}</h3>
            <label>
              {tx("标题", "Title")}
              <input
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
                placeholder={materialsText.editTitlePlaceholder}
              />
            </label>
            <label>
              {tx("素材正文", "Content")}
              <textarea
                value={editContent}
                onChange={(event) => setEditContent(event.target.value)}
                placeholder={materialsText.editContentPlaceholder}
              />
            </label>
            <label>
              {tx("来源链接（可选）", "Source URL (Optional)")}
              <input
                value={editSource}
                onChange={(event) => setEditSource(event.target.value)}
                placeholder="http(s)://..."
              />
            </label>
            {detectedEditPlatform !== "none" && (
              <div className={`materials-v2-platform-hint ${detectedEditPlatform}`}>
                {detectedEditPlatform === "wechat" && tx(
                  "已识别为微信公众号链接，保存时可自动抓取正文。",
                  "WeChat link detected. Content can be auto-fetched on save.",
                )}
                {detectedEditPlatform === "twitter" && tx(
                  "已识别为 Twitter/X 链接，保存时可尝试抓取推文正文。",
                  "Twitter/X link detected. Tweet text can be fetched on save.",
                )}
                {detectedEditPlatform === "generic" && tx(
                  "已识别为网页链接，保存时将按通用规则提取正文。",
                  "Web link detected. Generic extraction will run on save.",
                )}
                {detectedEditPlatform === "invalid" && materialsText.sourceLinkHintInvalid}
              </div>
            )}
            <label>
              {tx("标签（可选）", "Tags (Optional)")}
              <input
                value={editTags}
                onChange={(event) => setEditTags(event.target.value)}
                placeholder={materialsText.editTagsPlaceholder}
              />
            </label>
            {editError && <div className="materials-v2-submit-error">{editError}</div>}

            <div className="materials-v2-modal-actions">
              <button type="button" className="ghost" onClick={closeEditModal} disabled={isUpdating}>
                {tx("取消", "Cancel")}
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => void handleUpdateMaterial()}
                disabled={isUpdating}
              >
                {isUpdating ? materialsText.saving : materialsText.saveChanges}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
