import React, { useEffect, useMemo, useState } from "react";
import { FilePlus2, Search, Trash2, X } from "lucide-react";
import { AppTopNav } from "../components";
import {
  addMaterial,
  deleteMaterial,
  getMaterials,
  type Material,
} from "../services/api";
import "./MaterialsPage.css";

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

export const MaterialsPage: React.FC = () => {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const [showModal, setShowModal] = useState(false);
  const [newContent, setNewContent] = useState("");
  const [newSource, setNewSource] = useState("");
  const [newTags, setNewTags] = useState("");

  const [searchKeyword, setSearchKeyword] = useState("");
  const [activeTag, setActiveTag] = useState<string>("全部");

  useEffect(() => {
    void loadMaterials();
  }, []);

  const allTags = useMemo(() => {
    const tagSet = new Set<string>();
    materials.forEach((item) => {
      splitTags(item.tags).forEach((tag) => tagSet.add(tag));
    });
    return ["全部", ...Array.from(tagSet).sort((left, right) => left.localeCompare(right, "zh-CN"))];
  }, [materials]);

  const filteredMaterials = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase();

    return materials.filter((item) => {
      const matchTag =
        activeTag === "全部" || splitTags(item.tags).some((tag) => tag === activeTag);

      if (!matchTag) {
        return false;
      }

      if (!keyword) {
        return true;
      }

      const target = `${item.title} ${item.content} ${item.source_url || ""} ${item.tags || ""}`.toLowerCase();
      return target.includes(keyword);
    });
  }, [activeTag, materials, searchKeyword]);

  const loadMaterials = async () => {
    try {
      const data = await getMaterials();
      setMaterials(data);
    } catch (error) {
      console.error("加载素材失败:", error);
    }
  };

  const closeModal = () => {
    if (isLoading) {
      return;
    }
    setShowModal(false);
  };

  const handleAddMaterial = async () => {
    if (!newContent.trim()) {
      return;
    }

    setIsLoading(true);
    try {
      await addMaterial(newContent.trim(), newSource.trim() || undefined, newTags.trim() || undefined);
      await loadMaterials();
      setShowModal(false);
      setNewContent("");
      setNewSource("");
      setNewTags("");
      setActiveTag("全部");
    } catch (error) {
      console.error("添加素材失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (material: Material) => {
    const confirmed = window.confirm(`确定删除素材“${material.title || `#${material.id}`}”吗？`);
    if (!confirmed) {
      return;
    }

    try {
      await deleteMaterial(material.id);
      await loadMaterials();
    } catch (error) {
      console.error("删除素材失败:", error);
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
                  onClick={() => setActiveTag(tag)}
                >
                  {tag}
                </button>
              ))}
            </div>
          </div>

          <div className="materials-v2-stats">
            <div>
              <strong>{materials.length}</strong>
              <span>素材总数</span>
            </div>
            <div>
              <strong>{filteredMaterials.length}</strong>
              <span>当前筛选</span>
            </div>
          </div>
        </aside>

        <section className="materials-v2-content">
          <div className="materials-v2-content-head">
            <h2>素材卡片</h2>
            <span>共 {filteredMaterials.length} 条</span>
          </div>

          {filteredMaterials.length === 0 ? (
            <div className="materials-v2-empty">
              {materials.length === 0 ? "暂无素材，先新增一条吧。" : "当前筛选条件下没有结果。"}
            </div>
          ) : (
            <div className="materials-v2-grid">
              {filteredMaterials.map((material) => {
                const tags = splitTags(material.tags);

                return (
                  <article key={material.id} className="materials-v2-card">
                    <div className="materials-v2-card-head">
                      <h3>{material.title || `素材 #${material.id}`}</h3>
                      <button
                        type="button"
                        onClick={() => void handleDelete(material)}
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
        </section>
      </main>

      {showModal && (
        <div className="materials-v2-modal-mask" onClick={closeModal}>
          <div className="materials-v2-modal" onClick={(event) => event.stopPropagation()}>
            <h3>新增素材</h3>
            <label>
              素材内容
              <textarea
                value={newContent}
                onChange={(event) => setNewContent(event.target.value)}
                placeholder="输入素材正文，用于 RAG 检索与改写增强。"
              />
            </label>
            <label>
              来源（可选）
              <input
                value={newSource}
                onChange={(event) => setNewSource(event.target.value)}
                placeholder="例如：网页 URL / 文件名 / 访谈来源"
              />
            </label>
            <label>
              标签（可选）
              <input
                value={newTags}
                onChange={(event) => setNewTags(event.target.value)}
                placeholder="用逗号分隔多个标签，如：产品,案例,金句"
              />
            </label>

            <div className="materials-v2-modal-actions">
              <button type="button" className="ghost" onClick={closeModal} disabled={isLoading}>
                取消
              </button>
              <button
                type="button"
                className="primary"
                onClick={handleAddMaterial}
                disabled={isLoading || !newContent.trim()}
              >
                {isLoading ? "保存中..." : "保存素材"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
