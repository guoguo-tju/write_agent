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
  example_text?: string;
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

export interface RagRetrievedItem {
  material_id: number;
  title: string;
  source_url?: string;
  tags?: string;
  content: string;
  score: number;
}

export interface MaterialRetrieveResponse {
  items: RagRetrievedItem[];
  total: number;
}

export interface GithubTrendItem {
  rank: number;
  repo_full_name: string;
  repo_name: string;
  owner: string;
  description?: string;
  description_zh?: string;
  repo_url: string;
  stars_this_week: number;
  language?: string;
  total_stars?: number;
}

export interface GithubTrendSnapshot {
  period_type?: "daily" | "weekly";
  period_key?: string;
  week_key: string;
  requested_week_key?: string;
  requested_period_type?: "daily" | "weekly";
  requested_period_key?: string;
  snapshot_date: string;
  captured_at: string;
  is_weekly_archive: boolean;
  is_stale: boolean;
  is_refreshing: boolean;
  fetch_error?: string;
  items: GithubTrendItem[];
}

export interface GithubTrendWeekOption {
  week_key: string;
  latest_snapshot_date: string;
  latest_captured_at: string;
  has_archive: boolean;
}

export interface GithubTrendPeriodOption {
  period_type: "daily" | "weekly";
  period_key: string;
  latest_snapshot_date: string;
  latest_captured_at: string;
  has_archive: boolean;
}

export interface GithubTrendEnrichMeta {
  attempted: boolean;
  cache_hit: boolean;
  degraded: boolean;
  degrade_reason: string;
  duration_ms: number;
  fetched_at: string;
  sources: string[];
}

export interface GithubTrendAddMaterialResponse {
  status: string;
  material_id: number;
  created: boolean;
  updated?: boolean;
  enrich?: GithubTrendEnrichMeta;
}

export interface GithubTrendRewriteBuildResponse {
  status: string;
  title: string;
  content: string;
  enrich?: GithubTrendEnrichMeta;
}

export interface LinuxDoTrendItem {
  topic_id: number;
  title: string;
  content?: string;
  summary?: string;
  content_excerpt?: string;
  excerpt?: string;
  author?: string;
  tags?: string[] | string;
  replies_count?: number;
  views_count?: number;
  likes_count?: number;
  publish_time?: string;
  created_at?: string;
  source_url?: string;
}

export interface LinuxDoTrendSnapshot {
  period_type: "weekly" | "monthly";
  period_key: string;
  period_label?: string;
  updated_at: string;
  captured_at?: string;
  is_stale?: boolean;
  is_refreshing?: boolean;
  fetch_error?: string | null;
  available_tags?: string[];
  items: LinuxDoTrendItem[];
}

export interface LinuxDoTrendPeriodOption {
  period_type: "weekly" | "monthly";
  period_key: string;
  label: string;
  latest_snapshot_date?: string;
  latest_captured_at?: string;
  has_archive?: boolean;
}

export interface LinuxDoTrendTopicDetail {
  topic_id: number;
  title: string;
  content: string;
  author?: string;
  tags?: string[] | string;
  source_url?: string;
  created_at?: string;
  updated_at?: string;
  replies_count?: number;
  views_count?: number;
  likes_count?: number;
}

export interface LinuxDoTrendRefreshResponse {
  status: string;
  period_type: "weekly" | "monthly";
  period_key?: string;
  updated_at: string;
  errors?: Record<string, string>;
}

export interface LinuxDoTrendAddMaterialResponse {
  status: string;
  material_id: number;
  created: boolean;
  updated?: boolean;
}

export interface LinuxDoTrendRewriteBuildResponse {
  status: string;
  title: string;
  content: string;
}

export interface XhsTrendCategory {
  key: string;
  name: string;
  name_en: string;
}

export interface XhsTrendItem {
  id: string;
  title: string;
  content: string;
  content_type: string;
  like_count: number;
  favorite_count: number;
  comment_count: number;
  publish_time: string;
  source_url: string;
  hot_score: number;
  interactions: number;
}

export interface XhsTrendListResponse {
  category_key: string;
  category_name: string;
  category_name_en: string;
  sort: string;
  lookback_days: number;
  min_interactions: number;
  updated_at: string;
  fetch_error?: string | null;
  is_stale: boolean;
  items: XhsTrendItem[];
}

export interface XhsTrendRefreshResponse {
  status: string;
  updated_at: string;
  refreshed_categories: string[];
  errors: Record<string, string>;
}

export interface XhsCommentTopic {
  topic: string;
  ratio: string;
  sample_comment: string;
}

export interface XhsInspirationCard {
  topic: string;
  content_type: string;
  title_hook: string;
  rationale: string;
}

export interface XhsTrendAnalysisDone {
  category_key: string;
  category_name: string;
  generated_at: string;
  reason_points: string[];
  comment_topics: XhsCommentTopic[];
  inspiration_cards: XhsInspirationCard[];
}

export interface XhsTrendAnalysisStreamEvent {
  type: string;
  category_key: string;
  stage?: string;
  message?: string;
  data?: XhsTrendAnalysisDone;
}

export interface XhsTrendAnalysisStreamCallbacks {
  onStart?: (event: XhsTrendAnalysisStreamEvent) => void;
  onProgress?: (event: XhsTrendAnalysisStreamEvent) => void;
  onDone?: (data: XhsTrendAnalysisDone) => void;
  onError?: (message: string, traceId?: string) => void;
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

// 人工编辑记录
export interface ManualEditRecord {
  id: number;
  review_id: number;
  rewrite_id: number;
  original_content: string;
  edited_content: string;
  status: string;
  created_at: string;
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

export interface ManualCoverRewriteRequest {
  title: string;
  content: string;
}

export interface ManualCoverRewriteResponse {
  rewrite_id: number;
  title: string;
  content_excerpt: string;
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

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

// API响应类型
export interface ApiResponse<T> {
  data?: T;
  error?: string;
  message?: string;
}

export interface ObservabilityMeta {
  trace_id?: string;
  request_id?: string;
  node_id?: string;
  node_key?: string;
  behavior_id?: string;
  behavior_key?: string;
  event_id?: string;
  ts?: string;
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
  source_mode?: "manual" | "rewrite";
  obs?: ObservabilityMeta;
  trace_id?: string;
  node_id?: string;
  behavior_id?: string;
  error_code?: string;
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

export interface WorkflowStreamEvent {
  type: string;
  stage?: string;
  round?: number;
  rewrite_id?: number;
  review_id?: number;
  job_id?: number;
  seq?: number;
  checkpoint_stage?: string;
  is_replay?: boolean;
  delta?: string;
  message?: string;
  passed?: boolean;
  score?: number;
  reason?: string;
  status?: "passed" | "reached_max_loops";
  retry_count?: number;
  max_retries?: number;
  actual_words?: number;
  obs?: ObservabilityMeta;
  trace_id?: string;
  request_id?: string;
  node_id?: string;
  node_key?: string;
  behavior_id?: string;
  behavior_key?: string;
  event_id?: string;
  ts?: string;
  error_code?: string;
}

export interface WorkflowStreamCallbacks {
  onStage?: (event: WorkflowStreamEvent) => void;
  onProgress?: (event: WorkflowStreamEvent) => void;
  onContent?: (event: WorkflowStreamEvent) => void;
  onReviewDone?: (event: WorkflowStreamEvent) => void;
  onDone?: (event: WorkflowStreamEvent) => void;
  onError?: (event: WorkflowStreamEvent) => void;
}

export type WorkflowStepStatus =
  | "completed"
  | "current"
  | "pending"
  | "failed";

export interface WorkflowSnapshot {
  rewriteId: number;
  reviewId?: number;
  hasManualEdit: boolean;
  coverId?: number;
  steps: {
    rewrite: WorkflowStepStatus;
    review: WorkflowStepStatus;
    manual_edit: WorkflowStepStatus;
    cover: WorkflowStepStatus;
  };
}

export interface WorkflowLoopRequest {
  source_article: string;
  style_id: number;
  target_words?: number;
  enable_rag?: boolean;
  rag_top_k?: number;
  max_retries?: number;
  idempotency_key?: string;
  force_new?: boolean;
}

export interface WorkflowJobCreateResponse {
  job_id: number;
  status: string;
  idempotent_hit: boolean;
  rewrite_id?: number;
  checkpoint_seq: number;
}

export interface WorkflowJobStatusResponse {
  job_id: number;
  status: string;
  current_stage: string;
  checkpoint_stage: string;
  checkpoint_seq: number;
  resume_count: number;
  rewrite_id?: number;
  review_id?: number;
  error_code?: string;
  error_message?: string;
}

export interface LayoutSeed {
  rewriteId: number;
  content: string;
  coverImageUrl?: string;
  hasCover: boolean;
}
