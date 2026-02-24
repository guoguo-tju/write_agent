import React, { useState, useEffect } from "react";
import {
  CheckCircle,
  XCircle,
  Clock,
  Eye,
  FileText,
  Sparkles,
  Calendar,
} from "lucide-react";
import { Button, Card } from "../components";
import { getRewrites, type RewriteRecord } from "../services/api";
import "./ReviewsPage.css";

export const ReviewsPage: React.FC = () => {
  const [rewrites, setRewrites] = useState<RewriteRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedRewrite, setSelectedRewrite] = useState<RewriteRecord | null>(
    null,
  );

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setIsLoading(true);
    try {
      const data = await getRewrites();
      setRewrites(data);
    } catch (error) {
      console.error("加载数据失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CheckCircle size={16} className="status-icon success" />;
      case "failed":
        return <XCircle size={16} className="status-icon error" />;
      default:
        return <Clock size={16} className="status-icon pending" />;
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  // 截断文本显示
  const truncateText = (text: string, maxLength: number = 100) => {
    if (!text) return "";
    return text.length > maxLength ? text.slice(0, maxLength) + "..." : text;
  };

  return (
    <div className="reviews-page">
      <div className="page-header">
        <h1 className="page-title">审核记录</h1>
        <p className="page-description">查看所有改写审核状态</p>
      </div>

      <div className="reviews-list">
        {isLoading ? (
          <div className="loading">加载中...</div>
        ) : rewrites.length === 0 ? (
          <div className="empty-state">
            <p>暂无审核记录</p>
          </div>
        ) : (
          rewrites.map((rewrite) => (
            <Card key={rewrite.id} className="review-card">
              {/* 头部：ID、风格、状态、时间 */}
              <div className="review-header">
                <div className="review-info">
                  <span className="review-id">#{rewrite.id}</span>
                  <span className="review-style-badge">
                    <Sparkles size={12} />
                    {rewrite.style_name || "未知风格"}
                  </span>
                  {getStatusIcon(rewrite.status)}
                  <span className={`review-status status-${rewrite.status}`}>
                    {rewrite.status === "completed"
                      ? "已完成"
                      : rewrite.status === "failed"
                        ? "失败"
                        : "处理中"}
                  </span>
                </div>
                <div className="review-time">
                  <Calendar size={12} />
                  {formatDate(rewrite.created_at)}
                </div>
              </div>

              {/* 内容区域：原文和改写结果 */}
              <div className="review-content-grid">
                <div className="review-content-box source">
                  <div className="review-content-box-header">
                    <FileText size={14} />
                    <span>原文</span>
                  </div>
                  <div className="review-content-box-text">
                    {truncateText(rewrite.source_article, 200)}
                  </div>
                </div>
                <div className="review-content-box result">
                  <div className="review-content-box-header">
                    <Sparkles size={14} />
                    <span>改写结果</span>
                  </div>
                  <div className="review-content-box-text">
                    {rewrite.final_content
                      ? truncateText(rewrite.final_content, 200)
                      : "暂无改写结果"}
                  </div>
                </div>
              </div>

              {/* 底部操作 */}
              <div className="review-footer">
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Eye size={14} />}
                  onClick={() => setSelectedRewrite(rewrite)}
                >
                  查看详情
                </Button>
              </div>
            </Card>
          ))
        )}
      </div>

      {/* 详情弹窗 */}
      {selectedRewrite && (
        <div className="modal-overlay" onClick={() => setSelectedRewrite(null)}>
          <div className="modal modal-xl" onClick={(e) => e.stopPropagation()}>
            <div className="detail-header">
              <h3>改写详情 #{selectedRewrite.id}</h3>
              <div className="detail-meta">
                <span className="detail-meta-item">
                  <Sparkles size={14} />
                  {selectedRewrite.style_name || "未知风格"}
                </span>
                <span className="detail-meta-item">
                  <Calendar size={14} />
                  {formatDate(selectedRewrite.created_at)}
                </span>
                <span
                  className={`detail-status status-${selectedRewrite.status}`}
                >
                  {getStatusIcon(selectedRewrite.status)}
                  {selectedRewrite.status === "completed"
                    ? "已完成"
                    : selectedRewrite.status === "failed"
                      ? "失败"
                      : "处理中"}
                </span>
              </div>
            </div>

            <div className="detail-body">
              <div className="detail-section">
                <label>
                  <FileText size={14} />
                  原文
                </label>
                <div className="detail-content">
                  {selectedRewrite.source_article}
                </div>
              </div>

              {selectedRewrite.final_content && (
                <div className="detail-section">
                  <label>
                    <Sparkles size={14} />
                    改写结果
                  </label>
                  <div className="detail-content rewrite-result">
                    {selectedRewrite.final_content}
                  </div>
                </div>
              )}

              {selectedRewrite.error_message && (
                <div className="detail-section">
                  <label>错误信息</label>
                  <div className="detail-content error">
                    {selectedRewrite.error_message}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-actions">
              <Button
                variant="secondary"
                onClick={() => setSelectedRewrite(null)}
              >
                关闭
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
