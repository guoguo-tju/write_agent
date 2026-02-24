// 写作风格
export interface WritingStyle {
  id: number;
  name: string;
  visual_style?: string;
  tone?: string;
  emotional_tone?: string;
  article_type?: string;
  target_audience?: string;
  language_characteristics?: string;
  structure_preferences?: string;
  content_tendencies?: string;
  prohibited_elements?: string;
  sample_content?: string;
  style_description?: string; // JSON 字符串，包含详细的风格描述
  tags?: string;
  created_at: string;
  updated_at?: string;
}

// 素材
export interface Material {
  id: number;
  title: string;
  content: string;
  source_url?: string;
  tags?: string;
  embedding_status?: string;
  embedding_error?: string;
  created_at: string;
  updated_at?: string;
}

// 改写记录
export interface RewriteRecord {
  id: number;
  source_article: string;
  final_content: string;
  style_id: number;
  style_name?: string;
  target_words: number;
  actual_words: number;
  enable_rag: boolean;
  rag_top_k: number;
  rag_retrieved?: string;
  status: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

// 审核记录
export interface ReviewRecord {
  id: number;
  rewrite_id: number;
  result?: string;
  feedback?: string;
  ai_score?: number;
  total_score?: number;
  round?: number;
  status: string;
  error_message?: string;
  created_at: string;
  updated_at?: string;
}

// 封面记录
export interface CoverRecord {
  id: number;
  rewrite_id: number;
  prompt?: string;
  image_url?: string;
  size?: string;
  status: "pending" | "generating" | "completed" | "failed";
  error_message?: string;
  created_at: string;
  updated_at: string;
}

// 封面风格
export interface CoverStyle {
  id: number;
  name: string;
  prompt_template: string;
  description?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// API响应类型
export interface ApiResponse<T> {
  data?: T;
  error?: string;
  message?: string;
}

// SSE消息类型
export interface SSEMessage {
  type:
    | "start"
    | "progress"
    | "content"
    | "prompt"
    | "prompt_done"
    | "saving"
    | "generating"
    | "style"
    | "error"
    | "done";
  data?: string;
  error?: string;
  message?: string;
  delta?: string;
  id?: number;
  rewrite_id?: number;
  image_url?: string;
  size?: string;
  prompt?: string;
}

// 工作流状态
export interface WorkflowState {
  rewrite_id?: number;
  review_id?: number;
  cover_id?: number;
  status:
    | "idle"
    | "rewriting"
    | "reviewing"
    | "cover_generating"
    | "completed"
    | "failed";
  message?: string;
}
