import React, { useEffect, useMemo, useState } from "react";
import { FilePlus2, Search, Trash2, X } from "lucide-react";
import { AppTopNav, Pagination } from "../components";
import {
  addMaterial,
  deleteMaterial,
  getMaterialsPage,
  retrieveMaterials,
  updateMaterial,
  type Material,
  type RagRetrievedItem,
} from "../services/api";
import "./MaterialsPage.css";

const PAGE_SIZE = 10;
const RETRIEVE_TOP_K_OPTIONS = [3, 5, 8];

type MaterialInputMode = "text" | "link";
type SourcePlatform = "none" | "wechat" | "twitter" | "generic" | "invalid";

const summarize = (value: string, maxLength = 170) => {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}...`;
};

const formatDate = (value: string) => {
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

const splitTags = (tags?: string) =>
  (tags || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);

const extractErrorMessage = (error: unknown): string => {
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
  return "请求失败，请稍后重试";
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
  const [activeTag, setActiveTag] = useState<string>("全部");

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
    if (activeTag !== "全部") {
      tagSet.add(activeTag);
    }
    materials.forEach((item) => {
      splitTags(item.tags).forEach((tag) => tagSet.add(tag));
    });
    return ["全部", ...Array.from(tagSet).sort((left, right) => left.localeCompare(right, "zh-CN"))];
  }, [activeTag, materials]);

  const loadMaterials = async (requestedPage: number) => {
    setIsPageLoading(true);
    try {
      const response = await getMaterialsPage({
        page: requestedPage,
        limit: PAGE_SIZE,
        tags: activeTag === "全部" ? undefined : activeTag,
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
      setSubmitError("文本模式下请先输入素材正文。");
      return;
    }
    if (inputMode === "link" && !normalizedSource) {
      setSubmitError("链接模式下请先输入文章链接。");
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
      setActiveTag("全部");
    } catch (error) {
      console.error("添加素材失败:", error);
      setSubmitError(extractErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRetrieve = async () => {
    const query = retrieveQuery.trim();
    if (!query) {
      setRetrieveError("请输入检索问题。");
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
      setRetrieveError(extractErrorMessage(error));
    } finally {
      setIsRetrieving(false);
    }
  };

  const handleDelete = async (material: Material) => {
    const confirmed = window.confirm(`确定删除素材“${material.title || `#${material.id}`}”吗？`);
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

  const handleUpdateMaterial = async () => {
    if (!editingMaterial) {
      return;
    }

    const normalizedTitle = editTitle.trim();
    const normalizedContent = editContent.trim();
    const normalizedSource = editSource.trim();
    const normalizedTags = editTags.trim();

    if (!normalizedTitle) {
      setEditError("标题不能为空。");
      return;
    }
    if (!normalizedContent && !normalizedSource) {
      setEditError("正文和来源链接不能同时为空。");
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
      setEditError(extractErrorMessage(error));
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
            <h1>素材库</h1>
            <p>管理引用片段、资料线索和灵感卡片。</p>
          </div>

          <button className="materials-v2-create-btn" type="button" onClick={() => setShowModal(true)}>
            <FilePlus2 size={14} />
            新增素材
          </button>

          <label className="materials-v2-search">
            <Search size={14} />
            <input
              value={searchKeyword}
              onChange={(event) => setSearchKeyword(event.target.value)}
              placeholder="搜索标题、内容、来源、标签"
            />
            {searchKeyword && (
              <button type="button" onClick={() => setSearchKeyword("")}>
                <X size={13} />
              </button>
            )}
          </label>

          <div className="materials-v2-tag-panel">
            <h3>标签筛选</h3>
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
                  {tag}
                </button>
              ))}
            </div>
          </div>

          <div className="materials-v2-stats">
            <div>
              <strong>{total}</strong>
              <span>筛选总数</span>
            </div>
            <div>
              <strong>{materials.length}</strong>
              <span>当前页条数</span>
            </div>
          </div>
        </aside>

        <section className="materials-v2-content">
          <div className="materials-v2-content-head">
            <h2>素材卡片</h2>
            <span>共 {total} 条</span>
          </div>

          <section className="materials-v2-retrieve-panel">
            <div className="materials-v2-retrieve-head">
              <h3>RAG 检索测试</h3>
              <span>验证素材召回效果</span>
            </div>
            <div className="materials-v2-retrieve-controls">
              <input
                value={retrieveQuery}
                onChange={(event) => setRetrieveQuery(event.target.value)}
                placeholder="输入一个写作问题，如：如何解释 OpenClaw 的协作架构？"
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
                {isRetrieving ? "检索中..." : "开始检索"}
              </button>
            </div>

            {retrieveError && <div className="materials-v2-retrieve-error">{retrieveError}</div>}

            {isRetrieving ? (
              <div className="materials-v2-retrieve-empty">正在检索素材...</div>
            ) : retrieveItems.length > 0 ? (
              <div className="materials-v2-retrieve-list">
                {retrieveItems.map((item) => (
                  <article
                    key={`${item.material_id}-${item.score}`}
                    className="materials-v2-retrieve-item"
                  >
                    <div className="materials-v2-retrieve-item-head">
                      <strong>{item.title || `素材 #${item.material_id}`}</strong>
                      <span>相似度 {(item.score * 100).toFixed(1)}%</span>
                    </div>
                    <p>{summarize(item.content, 130)}</p>
                    <div className="materials-v2-retrieve-item-meta">
                      {item.tags ? <span>标签：{item.tags}</span> : <span>标签：-</span>}
                      {item.source_url ? (
                        <a href={item.source_url} target="_blank" rel="noreferrer">
                          来源链接
                        </a>
                      ) : (
                        <span>来源：-</span>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            ) : hasRetrieved ? (
              <div className="materials-v2-retrieve-empty">未召回到相关素材。</div>
            ) : (
              <div className="materials-v2-retrieve-empty">
                输入问题后可预览 RAG 召回素材。
              </div>
            )}
          </section>

          {isPageLoading ? (
            <div className="materials-v2-empty">加载中...</div>
          ) : materials.length === 0 ? (
            <div className="materials-v2-empty">
              {total === 0 ? "暂无素材，先新增一条吧。" : "当前页暂无数据。"}
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
                      <h3>{material.title || `素材 #${material.id}`}</h3>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleDelete(material);
                        }}
                        aria-label={`删除素材 ${material.title || material.id}`}
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
                      <span>{formatDate(material.created_at)}</span>
                      {material.source_url && <span>来源：{material.source_url}</span>}
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
            <h3>新增素材</h3>
            <div className="materials-v2-mode-switch">
              <button
                type="button"
                className={inputMode === "text" ? "active" : ""}
                onClick={() => {
                  setInputMode("text");
                  setSubmitError("");
                }}
              >
                文本模式
              </button>
              <button
                type="button"
                className={inputMode === "link" ? "active" : ""}
                onClick={() => {
                  setInputMode("link");
                  setSubmitError("");
                }}
              >
                链接模式
              </button>
            </div>
            <label>
              标题（可选）
              <input
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder="不填则自动从链接或正文推断"
              />
            </label>

            {inputMode === "text" && (
              <label>
                素材内容
                <textarea
                  value={newContent}
                  onChange={(event) => setNewContent(event.target.value)}
                  placeholder="输入素材正文，用于 RAG 检索与改写增强。"
                />
              </label>
            )}

            <label>
              {inputMode === "link" ? "文章链接" : "来源（可选）"}
              <input
                value={newSource}
                onChange={(event) => setNewSource(event.target.value)}
                placeholder={
                  inputMode === "link"
                    ? "粘贴公众号 / Twitter(X) / 其他网页链接"
                    : "例如：网页 URL / 文件名 / 访谈来源"
                }
              />
            </label>
            {detectedPlatform !== "none" && (
              <div className={`materials-v2-platform-hint ${detectedPlatform}`}>
                {detectedPlatform === "wechat" && "已识别为微信公众号链接，保存时将自动抓取正文。"}
                {detectedPlatform === "twitter" && "已识别为 Twitter/X 链接，保存时将尝试抓取推文正文。"}
                {detectedPlatform === "generic" && "已识别为网页链接，保存时将使用通用规则提取正文。"}
                {detectedPlatform === "invalid" && "链接格式不正确，请输入完整 http(s) URL。"}
              </div>
            )}
            {inputMode === "link" && (
              <label>
                手动正文（可选，抓取失败时建议填写）
                <textarea
                  value={newContent}
                  onChange={(event) => setNewContent(event.target.value)}
                  placeholder="可留空。若链接抓取失败，可手动粘贴正文后再提交。"
                />
              </label>
            )}
            <label>
              标签（可选）
              <input
                value={newTags}
                onChange={(event) => setNewTags(event.target.value)}
                placeholder="用逗号分隔多个标签，如：产品,案例,金句"
              />
            </label>
            {submitError && <div className="materials-v2-submit-error">{submitError}</div>}

            <div className="materials-v2-modal-actions">
              <button type="button" className="ghost" onClick={closeModal} disabled={isSubmitting}>
                取消
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
                {isSubmitting ? "保存中..." : "保存素材"}
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
            <h3>编辑素材 #{editingMaterial.id}</h3>
            <label>
              标题
              <input
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
                placeholder="素材标题"
              />
            </label>
            <label>
              素材正文
              <textarea
                value={editContent}
                onChange={(event) => setEditContent(event.target.value)}
                placeholder="可编辑完整素材正文"
              />
            </label>
            <label>
              来源链接（可选）
              <input
                value={editSource}
                onChange={(event) => setEditSource(event.target.value)}
                placeholder="http(s)://..."
              />
            </label>
            {detectedEditPlatform !== "none" && (
              <div className={`materials-v2-platform-hint ${detectedEditPlatform}`}>
                {detectedEditPlatform === "wechat" && "已识别为微信公众号链接，保存时可自动抓取正文。"}
                {detectedEditPlatform === "twitter" && "已识别为 Twitter/X 链接，保存时可尝试抓取推文正文。"}
                {detectedEditPlatform === "generic" && "已识别为网页链接，保存时将按通用规则提取正文。"}
                {detectedEditPlatform === "invalid" && "链接格式不正确，请输入完整 http(s) URL。"}
              </div>
            )}
            <label>
              标签（可选）
              <input
                value={editTags}
                onChange={(event) => setEditTags(event.target.value)}
                placeholder="用逗号分隔多个标签"
              />
            </label>
            {editError && <div className="materials-v2-submit-error">{editError}</div>}

            <div className="materials-v2-modal-actions">
              <button type="button" className="ghost" onClick={closeEditModal} disabled={isUpdating}>
                取消
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => void handleUpdateMaterial()}
                disabled={isUpdating}
              >
                {isUpdating ? "保存中..." : "保存修改"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
