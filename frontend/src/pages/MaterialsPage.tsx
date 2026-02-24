import React, { useState, useEffect } from "react";
import { Plus, Trash2, FileText } from "lucide-react";
import { Button, Input, Textarea, Card } from "../components";
import {
  getMaterials,
  addMaterial,
  deleteMaterial,
  type Material,
} from "../services/api";
import "./MaterialsPage.css";

export const MaterialsPage: React.FC = () => {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [newContent, setNewContent] = useState("");
  const [newSource, setNewSource] = useState("");
  const [newTags, setNewTags] = useState("");

  useEffect(() => {
    loadMaterials();
  }, []);

  const loadMaterials = async () => {
    try {
      const data = await getMaterials();
      setMaterials(data);
    } catch (error) {
      console.error("加载素材失败:", error);
    }
  };

  const handleAdd = async () => {
    if (!newContent) return;

    setIsLoading(true);
    try {
      await addMaterial(
        newContent,
        newSource || undefined,
        newTags || undefined,
      );
      await loadMaterials();
      setShowModal(false);
      setNewContent("");
      setNewSource("");
      setNewTags("");
    } catch (error) {
      console.error("添加素材失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("确定要删除这个素材吗？")) return;

    try {
      await deleteMaterial(id);
      await loadMaterials();
    } catch (error) {
      console.error("删除素材失败:", error);
    }
  };

  return (
    <div className="materials-page">
      <div className="page-header">
        <h1 className="page-title">素材库</h1>
        <p className="page-description">管理RAG增强的参考素材</p>
      </div>

      <div className="materials-toolbar">
        <Button onClick={() => setShowModal(true)} icon={<Plus size={16} />}>
          添加素材
        </Button>
      </div>

      <div className="materials-list">
        {materials.length === 0 ? (
          <div className="empty-state">
            <FileText size={48} strokeWidth={1} />
            <p>暂无素材</p>
            <Button onClick={() => setShowModal(true)}>添加第一个素材</Button>
          </div>
        ) : (
          materials.map((material) => (
            <Card key={material.id} className="material-card">
              <div className="material-header">
                <h4>{material.title || "未命名素材"}</h4>
                <div className="material-actions">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 size={14} />}
                    onClick={() => handleDelete(material.id)}
                  >
                    删除
                  </Button>
                </div>
              </div>
              <p className="material-content">
                {material.content.length > 200
                  ? material.content.slice(0, 200) + "..."
                  : material.content}
              </p>
              {material.tags && (
                <div className="material-tags">
                  {material.tags
                    .split(",")
                    .map((tag: string, index: number) => (
                      <span key={index} className="tag">
                        {tag.trim()}
                      </span>
                    ))}
                </div>
              )}
              <div className="material-meta">
                <span>
                  添加于 {new Date(material.created_at).toLocaleDateString()}
                </span>
                {material.source_url && <span>来源: {material.source_url}</span>}
              </div>
            </Card>
          ))
        )}
      </div>

      {/* 添加素材弹窗 */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>添加素材</h3>
            <Textarea
              label="素材内容"
              placeholder="输入素材内容，用于RAG检索..."
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              style={{ minHeight: "200px", marginBottom: "12px" }}
            />
            <Input
              label="来源（可选）"
              placeholder="素材来源，如URL或文件名"
              value={newSource}
              onChange={(e) => setNewSource(e.target.value)}
              style={{ marginBottom: "12px" }}
            />
            <Input
              label="标签（可选）"
              placeholder="用逗号分隔多个标签"
              value={newTags}
              onChange={(e) => setNewTags(e.target.value)}
              style={{ marginBottom: "12px" }}
            />
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setShowModal(false)}>
                取消
              </Button>
              <Button
                onClick={handleAdd}
                loading={isLoading}
                disabled={!newContent}
              >
                添加
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
