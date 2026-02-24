import React, { useState, useEffect } from 'react';
import { Plus, Minus, Trash2, Eye, ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { Button, Input, Textarea, Card } from '../components';
import { getStyles, deleteStyle, extractStyleWithStream, type WritingStyle } from '../services/api';
import './StylesPage.css';

const STYLE_SECTION_KEYS = [
  'persona',
  'thinking_pattern',
  'opening_pattern',
  'transition_pattern',
  'sentence_rhythm',
  'vocabulary',
  'rhetorical_devices',
  'ending_pattern',
  'format_layout',
  'signature_moves',
  'anti_ai_features',
  'paragraph_templates',
  'overall_summary',
];

export const StylesPage: React.FC = () => {
  const [styles, setStyles] = useState<WritingStyle[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [newStyleName, setNewStyleName] = useState('');
  const [newStyleArticles, setNewStyleArticles] = useState<string[]>(['']);
  const [extractStatus, setExtractStatus] = useState('');
  const [extractPreview, setExtractPreview] = useState('');
  const [selectedStyle, setSelectedStyle] = useState<WritingStyle | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(STYLE_SECTION_KEYS));

  useEffect(() => {
    loadStyles();
  }, []);

  useEffect(() => {
    if (selectedStyle) {
      setExpandedSections(new Set(STYLE_SECTION_KEYS));
    }
  }, [selectedStyle]);

  const loadStyles = async () => {
    try {
      const data = await getStyles();
      setStyles(data);
    } catch (error) {
      console.error('加载风格失败:', error);
    }
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
      next.splice(afterIndex + 1, 0, '');
      return next;
    });
  };

  const removeArticleInput = (index: number) => {
    setNewStyleArticles((prev) => {
      if (prev.length <= 1) {
        return [''];
      }
      return prev.filter((_, i) => i !== index);
    });
  };

  const handleExtract = async () => {
    const styleName = newStyleName.trim();
    const articles = newStyleArticles.map((item) => item.trim()).filter(Boolean);
    if (!styleName || articles.length === 0) return;

    setIsLoading(true);
    setExtractPreview('');
    setExtractStatus('正在启动风格分析...');
    try {
      await extractStyleWithStream(
        {
          articles,
          style_name: styleName,
        },
        {
          onStart: (data) => {
            const count = Number(data.articles_count || articles.length);
            setExtractStatus(`已接收 ${count} 篇参考文章，开始分析...`);
          },
          onProgress: (data) => {
            setExtractStatus(String(data.message || '正在分析风格特征...'));
          },
          onChunk: (delta) => {
            setExtractPreview((prev) => (prev + delta).slice(-4000));
          },
        }
      );
      await loadStyles();
      setShowModal(false);
      setNewStyleName('');
      setNewStyleArticles(['']);
      setExtractStatus('');
      setExtractPreview('');
    } catch (error) {
      console.error('提取风格失败:', error);
      setExtractStatus(error instanceof Error ? error.message : '提取失败');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个风格吗？')) return;

    try {
      await deleteStyle(id);
      await loadStyles();
    } catch (error) {
      console.error('删除风格失败:', error);
    }
  };

  const openCreateModal = () => {
    setShowModal(true);
    if (newStyleArticles.length === 0) {
      setNewStyleArticles(['']);
    }
    setExtractStatus('');
    setExtractPreview('');
  };

  const closeCreateModal = () => {
    if (isLoading) return;
    setShowModal(false);
    setExtractStatus('');
    setExtractPreview('');
  };

  // 解析风格描述 JSON
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
    paragraph_templates?: {
      观点段?: string;
      举例段?: string;
      转折段?: string;
      收尾段?: string;
      [key: string]: string | undefined;
    };
    overall_summary?: string;
  }

  const parseStyleDescription = (jsonString: string): StyleDescription | null => {
    try {
      return JSON.parse(jsonString);
    } catch {
      return null;
    }
  };

  // 风格描述字段的中文映射
  const fieldLabels: Record<keyof StyleDescription, string> = {
    persona: '人设定位',
    thinking_pattern: '思维模式',
    opening_pattern: '开头模式',
    transition_pattern: '过渡模式',
    sentence_rhythm: '句子节奏',
    vocabulary: '用词特点',
    rhetorical_devices: '修辞手法',
    ending_pattern: '结尾模式',
    format_layout: '格式布局',
    signature_moves: '标志性手法',
    anti_ai_features: '反AI特征',
    paragraph_templates: '段落模板',
    overall_summary: '整体总结',
  };

  // 渲染单个风格描述字段
  const renderStyleDescriptionField = (
    label: string,
    value: string | string[] | undefined,
    isExpanded: boolean,
    onToggle: () => void
  ) => {
    if (!value) return null;

    const isArray = Array.isArray(value);
    const isLongText = isArray ? value.join('').length > 100 : value.length > 100;

    return (
      <div className="style-desc-item">
        <div className="style-desc-header" onClick={onToggle}>
          <span className="style-desc-label">{label}</span>
          {isLongText && (
            <span className="style-desc-toggle">
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </span>
          )}
        </div>
        <div className={`style-desc-content ${isExpanded ? 'expanded' : ''}`}>
          {isArray ? (
            <ul className="style-desc-list">
              {value.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>{value}</p>
          )}
        </div>
      </div>
    );
  };

  // 渲染段落模板
  const renderParagraphTemplates = (
    templates: StyleDescription['paragraph_templates'],
    isExpanded: boolean,
    onToggle: () => void
  ) => {
    if (!templates) return null;

    const templateKeys = Object.keys(templates);
    if (templateKeys.length === 0) return null;

    return (
      <div className="style-desc-item">
        <div className="style-desc-header" onClick={onToggle}>
          <span className="style-desc-label">段落模板</span>
          <span className="style-desc-toggle">
            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
        </div>
        {isExpanded && (
          <div className="style-desc-content expanded">
            <div className="paragraph-templates">
              {templateKeys.map((key) => (
                templates[key] && (
                  <div key={key} className="paragraph-template">
                    <span className="template-name">{key}</span>
                    <p className="template-content">{templates[key]}</p>
                  </div>
                )
              ))}
            </div>
          </div>
        )}
      </div>
    );
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

  // 渲染风格描述卡片
  const renderStyleDescription = (styleDescription: StyleDescription) => {
    if (!styleDescription) return null;

    return (
      <div className="style-description-card">
        <h4 className="style-desc-title">风格特征详情</h4>
        <div className="style-desc-grid">
          {renderStyleDescriptionField(
            fieldLabels.persona,
            styleDescription.persona,
            expandedSections.has('persona'),
            () => toggleSection('persona')
          )}
          {renderStyleDescriptionField(
            fieldLabels.thinking_pattern,
            styleDescription.thinking_pattern,
            expandedSections.has('thinking_pattern'),
            () => toggleSection('thinking_pattern')
          )}
          {renderStyleDescriptionField(
            fieldLabels.opening_pattern,
            styleDescription.opening_pattern,
            expandedSections.has('opening_pattern'),
            () => toggleSection('opening_pattern')
          )}
          {renderStyleDescriptionField(
            fieldLabels.transition_pattern,
            styleDescription.transition_pattern,
            expandedSections.has('transition_pattern'),
            () => toggleSection('transition_pattern')
          )}
          {renderStyleDescriptionField(
            fieldLabels.sentence_rhythm,
            styleDescription.sentence_rhythm,
            expandedSections.has('sentence_rhythm'),
            () => toggleSection('sentence_rhythm')
          )}
          {renderStyleDescriptionField(
            fieldLabels.vocabulary,
            styleDescription.vocabulary,
            expandedSections.has('vocabulary'),
            () => toggleSection('vocabulary')
          )}
          {renderStyleDescriptionField(
            fieldLabels.rhetorical_devices,
            styleDescription.rhetorical_devices,
            expandedSections.has('rhetorical_devices'),
            () => toggleSection('rhetorical_devices')
          )}
          {renderStyleDescriptionField(
            fieldLabels.ending_pattern,
            styleDescription.ending_pattern,
            expandedSections.has('ending_pattern'),
            () => toggleSection('ending_pattern')
          )}
          {renderStyleDescriptionField(
            fieldLabels.format_layout,
            styleDescription.format_layout,
            expandedSections.has('format_layout'),
            () => toggleSection('format_layout')
          )}
          {renderStyleDescriptionField(
            fieldLabels.signature_moves,
            styleDescription.signature_moves,
            expandedSections.has('signature_moves'),
            () => toggleSection('signature_moves')
          )}
          {renderStyleDescriptionField(
            fieldLabels.anti_ai_features,
            styleDescription.anti_ai_features,
            expandedSections.has('anti_ai_features'),
            () => toggleSection('anti_ai_features')
          )}
          {renderParagraphTemplates(
            styleDescription.paragraph_templates,
            expandedSections.has('paragraph_templates'),
            () => toggleSection('paragraph_templates')
          )}
          {renderStyleDescriptionField(
            fieldLabels.overall_summary,
            styleDescription.overall_summary,
            expandedSections.has('overall_summary'),
            () => toggleSection('overall_summary')
          )}
        </div>
      </div>
    );
  };

  const renderStyleDetail = (style: WritingStyle) => {
    const fields = [
      { label: '视觉风格', value: style.visual_style },
      { label: '语气', value: style.tone },
      { label: '情感基调', value: style.emotional_tone },
      { label: '文章类型', value: style.article_type },
      { label: '目标读者', value: style.target_audience },
      { label: '语言特点', value: style.language_characteristics },
      { label: '结构偏好', value: style.structure_preferences },
      { label: '内容倾向', value: style.content_tendencies },
      { label: '禁忌元素', value: style.prohibited_elements },
    ];

    return (
      <div className="style-detail">
        <h3>{style.name}</h3>
        <p className="style-date">创建于 {new Date(style.created_at).toLocaleDateString()}</p>

        <div className="style-fields">
          {fields.map((field) => (
            field.value && (
              <div key={field.label} className="style-field">
                <label>{field.label}</label>
                <p>{field.value}</p>
              </div>
            )
          ))}
        </div>

        {style.sample_content && (
          <div className="style-field">
            <label>示例内容</label>
            <p className="sample-content">{style.sample_content}</p>
          </div>
        )}

        {/* 风格描述详情 */}
        {style.style_description && (() => {
          const parsed = parseStyleDescription(style.style_description);
          return parsed ? renderStyleDescription(parsed) : null;
        })()}
      </div>
    );
  };

  return (
    <div className="styles-page">
      <div className="page-header">
        <h1 className="page-title">风格管理</h1>
        <p className="page-description">管理你的写作风格模板</p>
      </div>

      <div className="styles-toolbar">
        <Button
          onClick={openCreateModal}
          icon={<Plus size={16} />}
        >
          新建风格
        </Button>
      </div>

      <div className="styles-grid">
        {styles.length === 0 ? (
          <div className="empty-state">
            <p>暂无风格模板</p>
            <Button onClick={openCreateModal}>创建第一个风格</Button>
          </div>
        ) : (
          styles.map((style) => (
            <Card key={style.id} hoverable onClick={() => setSelectedStyle(style)}>
              <div className="style-card">
                <h4>{style.name}</h4>
                <p className="style-preview">
                  {style.tone || style.visual_style || '未设置'}
                </p>
                <div className="style-meta">
                  <span>{new Date(style.created_at).toLocaleDateString()}</span>
                </div>
                <div className="style-actions">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Eye size={14} />}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedStyle(style);
                    }}
                  >
                    查看
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 size={14} />}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(style.id);
                    }}
                  >
                    删除
                  </Button>
                </div>
              </div>
            </Card>
          ))
        )}
      </div>

      {/* 新建风格弹窗 */}
      {showModal && (
        <div className="modal-overlay" onClick={closeCreateModal}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>提取写作风格</h3>
            <Input
              label="风格名称"
              placeholder="给风格起个名字"
              value={newStyleName}
              onChange={(e) => setNewStyleName(e.target.value)}
              style={{ marginBottom: '12px' }}
            />
            <div className="article-inputs">
              {newStyleArticles.map((article, index) => (
                <div key={index} className="article-input-group">
                  <div className="article-input-header">
                    <label>参考文章 {index + 1}</label>
                    <div className="article-input-actions">
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<Plus size={14} />}
                        onClick={() => addArticleInput(index)}
                        disabled={isLoading}
                      >
                        新增
                      </Button>
                      {newStyleArticles.length > 1 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Minus size={14} />}
                          onClick={() => removeArticleInput(index)}
                          disabled={isLoading}
                        >
                          删除
                        </Button>
                      )}
                    </div>
                  </div>
                  <Textarea
                    placeholder="粘贴该风格的代表文章内容..."
                    value={article}
                    onChange={(e) => updateArticle(index, e.target.value)}
                    style={{ minHeight: '120px' }}
                  />
                </div>
              ))}
            </div>
            {(isLoading || extractStatus || extractPreview) && (
              <div className="extract-stream-panel">
                <div className="extract-stream-status">
                  {isLoading && <Loader2 size={14} className="spin" />}
                  <span>{extractStatus || '准备中...'}</span>
                </div>
                {extractPreview && (
                  <pre className="extract-stream-preview">{extractPreview}</pre>
                )}
              </div>
            )}
            <div className="modal-actions">
              <Button variant="secondary" onClick={closeCreateModal} disabled={isLoading}>
                取消
              </Button>
              <Button
                onClick={handleExtract}
                loading={isLoading}
                disabled={!newStyleName.trim() || newStyleArticles.every((article) => !article.trim())}
              >
                提取风格
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* 风格详情弹窗 */}
      {selectedStyle && (
        <div className="modal-overlay" onClick={() => setSelectedStyle(null)}>
          <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
            {renderStyleDetail(selectedStyle)}
            <div className="modal-actions">
              <Button variant="secondary" onClick={() => setSelectedStyle(null)}>
                关闭
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
