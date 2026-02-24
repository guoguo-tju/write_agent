import React, { useState, useEffect } from "react";
import {
  Image as ImageIcon,
  RefreshCw,
  Download,
  Plus,
  Trash2,
  Palette,
} from "lucide-react";
import { Button, Card, Input, Textarea } from "../components";
import {
  getRewrites,
  getCoversByRewrites,
  startCover,
  getCoverStyles,
  createCoverStyle,
  deleteCoverStyle,
  type CoverRequest,
  type RewriteRecord,
  type CoverRecord,
  type CoverStyle,
} from "../services/api";
import "./CoversPage.css";

export const CoversPage: React.FC = () => {
  const ratioOptions = [
    { value: "2.35:1", label: "2.35:1（公众号封面）" },
    { value: "1:1", label: "1:1（方图）" },
    { value: "9:16", label: "9:16（竖版）" },
    { value: "3:4", label: "3:4（海报）" },
  ] as const;

  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [covers, setCovers] = useState<Map<number, CoverRecord>>(new Map());
  const [coverStyles, setCoverStyles] = useState<CoverStyle[]>([]);
  const [selectedRewriteId, setSelectedRewriteId] = useState<number | null>(
    null,
  );
  const [selectedStyleId, setSelectedStyleId] = useState<number | null>(null);
  const [customPrompt, setCustomPrompt] = useState("");
  const [promptMode, setPromptMode] = useState<"auto" | "style" | "custom">(
    "auto",
  );
  const [selectedRatio, setSelectedRatio] =
    useState<(typeof ratioOptions)[number]["value"]>("2.35:1");
  const [isGenerating, setIsGenerating] = useState(false);

  // 新建风格弹窗
  const [showStyleModal, setShowStyleModal] = useState(false);
  const [newStyleName, setNewStyleName] = useState("");
  const [newStylePrompt, setNewStylePrompt] = useState("");
  const [newStyleDesc, setNewStyleDesc] = useState("");
  const [isCreatingStyle, setIsCreatingStyle] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [rewritesData, stylesData] = await Promise.all([
        getRewrites(),
        getCoverStyles(),
      ]);
      const completed = rewritesData.filter((r) => r.status === "completed");
      setRewrites(completed);
      setCoverStyles(stylesData);

      // 批量加载封面，避免逐条 404 噪音
      const loadedCovers = await getCoversByRewrites(
        completed.map((rewrite) => rewrite.id),
      );
      const coverMap = new Map<number, CoverRecord>(
        loadedCovers.map((cover) => [cover.rewrite_id, cover]),
      );
      setCovers(coverMap);
    } catch (error) {
      console.error("加载数据失败:", error);
    }
  };

  const handleGenerateCover = async () => {
    if (!selectedRewriteId) return;

    setIsGenerating(true);
    try {
      // 根据模式传递不同参数
      const request: CoverRequest = { rewrite_id: selectedRewriteId };

      if (promptMode === "style" && selectedStyleId) {
        request.style_id = selectedStyleId;
      } else if (promptMode === "custom" && customPrompt.trim()) {
        request.custom_prompt = customPrompt.trim();
      }
      request.size = selectedRatio;

      const cover = await startCover(request);
      setCovers((prev) => new Map(prev).set(selectedRewriteId, cover));
    } catch (error) {
      console.error("生成封面失败:", error);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCreateStyle = async () => {
    if (!newStyleName || !newStylePrompt) return;

    setIsCreatingStyle(true);
    try {
      await createCoverStyle({
        name: newStyleName,
        prompt_template: newStylePrompt,
        description: newStyleDesc || undefined,
      });
      await loadData();
      setShowStyleModal(false);
      setNewStyleName("");
      setNewStylePrompt("");
      setNewStyleDesc("");
    } catch (error) {
      console.error("创建风格失败:", error);
    } finally {
      setIsCreatingStyle(false);
    }
  };

  const handleDeleteStyle = async (id: number) => {
    if (!confirm("确定要删除这个风格吗？")) return;

    try {
      await deleteCoverStyle(id);
      await loadData();
    } catch (error) {
      console.error("删除风格失败:", error);
    }
  };

  const selectedCover = selectedRewriteId
    ? covers.get(selectedRewriteId)
    : null;

  return (
    <div className="covers-page">
      <div className="page-header">
        <h1 className="page-title">封面生成</h1>
        <p className="page-description">为你的文章生成AI封面</p>
      </div>

      <div className="covers-grid">
        <Card>
          <h3>选择文章</h3>
          <p className="card-description">选择已完成改写的文章来生成封面</p>

          <select
            className="select-input"
            value={selectedRewriteId || ""}
            onChange={(e) =>
              setSelectedRewriteId(
                e.target.value ? Number(e.target.value) : null,
              )
            }
          >
            <option value="">请选择文章</option>
            {rewrites.map((rewrite) => (
              <option key={rewrite.id} value={rewrite.id}>
                #{rewrite.id} - {rewrite.source_article?.slice(0, 50)}...
              </option>
            ))}
          </select>

          {/* Prompt模式选择 */}
          <div className="prompt-mode-selector">
            <label>生成方式</label>
            <div className="mode-buttons">
              <button
                className={`mode-btn ${promptMode === "auto" ? "active" : ""}`}
                onClick={() => setPromptMode("auto")}
              >
                自动生成
              </button>
              <button
                className={`mode-btn ${promptMode === "style" ? "active" : ""}`}
                onClick={() => setPromptMode("style")}
              >
                选择风格
              </button>
              <button
                className={`mode-btn ${promptMode === "custom" ? "active" : ""}`}
                onClick={() => setPromptMode("custom")}
              >
                自定义
              </button>
            </div>
          </div>

          {/* 风格选择 */}
          {promptMode === "style" && (
            <div className="style-selector">
              <div className="style-header">
                <label>封面风格</label>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Plus size={14} />}
                  onClick={() => setShowStyleModal(true)}
                >
                  新建
                </Button>
              </div>
              {coverStyles.length === 0 ? (
                <p className="no-styles">暂无封面风格，请先创建</p>
              ) : (
                <select
                  className="select-input"
                  value={selectedStyleId || ""}
                  onChange={(e) =>
                    setSelectedStyleId(
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                >
                  <option value="">请选择风格</option>
                  {coverStyles.map((style) => (
                    <option key={style.id} value={style.id}>
                      {style.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* 自定义Prompt */}
          {promptMode === "custom" && (
            <div className="custom-prompt">
              <Textarea
                label="自定义提示词"
                placeholder="输入自定义的封面提示词（英文）..."
                value={customPrompt}
                onChange={(e) => setCustomPrompt(e.target.value)}
                style={{ minHeight: "100px" }}
              />
            </div>
          )}

          <div className="ratio-selector">
            <label>封面比例</label>
            <select
              className="select-input"
              value={selectedRatio}
              onChange={(e) =>
                setSelectedRatio(
                  e.target.value as (typeof ratioOptions)[number]["value"],
                )
              }
            >
              {ratioOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <Button
            onClick={handleGenerateCover}
            disabled={!selectedRewriteId || isGenerating}
            loading={isGenerating}
            icon={<ImageIcon size={16} />}
            style={{ width: "100%", marginTop: "16px" }}
          >
            {isGenerating ? "生成中..." : "生成封面"}
          </Button>
        </Card>

        <Card>
          <h3>封面预览</h3>
          <p className="card-description">生成的封面将显示在这里</p>

          {selectedCover?.image_url ? (
            <div className="cover-preview">
              <img src={selectedCover.image_url} alt="封面" />
              <div className="cover-actions">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Download size={14} />}
                  onClick={() => window.open(selectedCover.image_url, "_blank")}
                >
                  下载
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<RefreshCw size={14} />}
                  onClick={handleGenerateCover}
                  disabled={isGenerating}
                >
                  重新生成
                </Button>
              </div>
            </div>
          ) : (
            <div className="cover-placeholder">
              <ImageIcon size={48} strokeWidth={1} />
              <span>请选择文章生成封面</span>
            </div>
          )}
        </Card>
      </div>

      {/* 风格管理 */}
      <div className="styles-section">
        <h3>
          <Palette size={18} />
          封面风格管理
        </h3>
        {coverStyles.length === 0 ? (
          <div className="empty-state">
            <p>暂无封面风格</p>
            <Button onClick={() => setShowStyleModal(true)}>
              创建第一个风格
            </Button>
          </div>
        ) : (
          <div className="styles-list">
            {coverStyles.map((style) => (
              <div key={style.id} className="style-card">
                <div className="style-card-top">
                  <div className="style-info">
                    <h4>{style.name}</h4>
                    <p className="style-desc">{style.description || "无描述"}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="style-delete-btn"
                    icon={<Trash2 size={14} />}
                    onClick={() => handleDeleteStyle(style.id)}
                    title={`删除风格：${style.name}`}
                    aria-label={`删除风格：${style.name}`}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 封面历史 */}
      <div className="covers-history">
        <h3>封面历史</h3>
        <div className="covers-list">
          {Array.from(covers.entries()).length === 0 ? (
            <div className="empty-state">暂无封面记录</div>
          ) : (
            Array.from(covers.entries()).map(([rewriteId, cover]) => (
              <div key={rewriteId} className="cover-item">
                {cover.image_url && (
                  <img src={cover.image_url} alt={`封面 #${rewriteId}`} />
                )}
                <div className="cover-item-info">
                  <span>文章 #{rewriteId}</span>
                  <span className={`cover-status status-${cover.status}`}>
                    {cover.status === "completed"
                      ? "已完成"
                      : cover.status === "failed"
                        ? "失败"
                        : "处理中"}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 新建风格弹窗 */}
      {showStyleModal && (
        <div className="modal-overlay" onClick={() => setShowStyleModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>新建封面风格</h3>
            <Input
              label="风格名称"
              placeholder="如：油画风格、赛博朋克、水彩画"
              value={newStyleName}
              onChange={(e) => setNewStyleName(e.target.value)}
              style={{ marginBottom: "12px" }}
            />
            <Textarea
              label="提示词模板"
              placeholder="输入封面提示词模板，可以使用 {content} 和 {title} 作为占位符"
              value={newStylePrompt}
              onChange={(e) => setNewStylePrompt(e.target.value)}
              style={{ minHeight: "150px", marginBottom: "12px" }}
            />
            <Input
              label="描述（可选）"
              placeholder="简短描述这个风格的特点"
              value={newStyleDesc}
              onChange={(e) => setNewStyleDesc(e.target.value)}
              style={{ marginBottom: "12px" }}
            />
            <div className="modal-actions">
              <Button
                variant="secondary"
                onClick={() => setShowStyleModal(false)}
              >
                取消
              </Button>
              <Button
                onClick={handleCreateStyle}
                loading={isCreatingStyle}
                disabled={!newStyleName || !newStylePrompt}
              >
                创建
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
