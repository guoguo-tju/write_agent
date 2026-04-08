import axios, { AxiosError } from "axios";
import type {
  WritingStyle,
  Material,
  RewriteRecord,
  ReviewRecord,
  ManualEditRecord,
  CoverRecord,
  ManualCoverRewriteRequest,
  ManualCoverRewriteResponse,
  CoverStyle,
  SSEMessage,
  PaginatedResponse,
  RagRetrievedItem,
  MaterialRetrieveResponse,
  GithubTrendItem,
  GithubTrendEnrichMeta,
  GithubTrendSnapshot,
  GithubTrendWeekOption,
  GithubTrendPeriodOption,
  GithubTrendAddMaterialResponse,
  GithubTrendRewriteBuildResponse,
  LinuxDoTrendItem,
  LinuxDoTrendSnapshot,
  LinuxDoTrendPeriodOption,
  LinuxDoTrendTopicDetail,
  LinuxDoTrendRefreshResponse,
  LinuxDoTrendAddMaterialResponse,
  LinuxDoTrendRewriteBuildResponse,
  XhsTrendCategory,
  XhsTrendItem,
  XhsTrendListResponse,
  XhsTrendRefreshResponse,
  XhsTrendAnalysisDone,
  XhsTrendAnalysisStreamCallbacks,
  XhsTrendAnalysisStreamEvent,
  WorkflowLoopRequest,
  WorkflowJobCreateResponse,
  WorkflowJobStatusResponse,
  WorkflowStreamCallbacks,
  WorkflowStreamEvent,
  WorkflowSnapshot,
  WorkflowStepStatus,
} from "../types";

// Re-export types
export type {
  WritingStyle,
  Material,
  RewriteRecord,
  ReviewRecord,
  ManualEditRecord,
  CoverRecord,
  ManualCoverRewriteRequest,
  ManualCoverRewriteResponse,
  CoverStyle,
  SSEMessage,
  PaginatedResponse,
  RagRetrievedItem,
  MaterialRetrieveResponse,
  GithubTrendItem,
  GithubTrendEnrichMeta,
  GithubTrendSnapshot,
  GithubTrendWeekOption,
  GithubTrendPeriodOption,
  GithubTrendAddMaterialResponse,
  GithubTrendRewriteBuildResponse,
  LinuxDoTrendItem,
  LinuxDoTrendSnapshot,
  LinuxDoTrendPeriodOption,
  LinuxDoTrendTopicDetail,
  LinuxDoTrendRefreshResponse,
  LinuxDoTrendAddMaterialResponse,
  LinuxDoTrendRewriteBuildResponse,
  XhsTrendCategory,
  XhsTrendItem,
  XhsTrendListResponse,
  XhsTrendRefreshResponse,
  XhsTrendAnalysisDone,
  XhsTrendAnalysisStreamCallbacks,
  XhsTrendAnalysisStreamEvent,
  WorkflowLoopRequest,
  WorkflowJobCreateResponse,
  WorkflowJobStatusResponse,
  WorkflowStreamCallbacks,
  WorkflowStreamEvent,
  WorkflowSnapshot,
  WorkflowStepStatus,
};

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  headers: {
    "Content-Type": "application/json",
  },
});

const appendObsHint = (
  message: string,
  obs?: {
    trace_id?: string;
    node_id?: string;
    error_code?: string;
  },
): string => {
  if (!obs) {
    return message;
  }
  const traceId = (obs.trace_id || "").trim();
  const nodeId = (obs.node_id || "").trim();
  const errorCode = (obs.error_code || "").trim();
  const parts: string[] = [];
  if (traceId) {
    parts.push(`trace_id=${traceId}`);
  }
  if (nodeId) {
    parts.push(`node_id=${nodeId}`);
  }
  if (errorCode) {
    parts.push(`error_code=${errorCode}`);
  }
  if (parts.length === 0) {
    return message;
  }
  return `${message}（${parts.join(", ")}）`;
};

// 错误处理
const handleError = (error: unknown): string => {
  if (error instanceof AxiosError) {
    const payload = (error.response?.data || {}) as {
      detail?: string;
      trace_id?: string;
      node_id?: string;
      error_code?: string;
    };
    const traceId =
      payload.trace_id ||
      String(error.response?.headers?.["x-trace-id"] || "").trim();
    const nodeId = payload.node_id || "";
    const errorCode = payload.error_code || "";
    const base = payload.detail || error.message;
    return appendObsHint(base, {
      trace_id: traceId,
      node_id: nodeId,
      error_code: errorCode,
    });
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
};

const parseSseJson = (raw: string): Record<string, unknown> | null => {
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
};

const sseErrorWithObs = (
  data: Record<string, unknown>,
  fallback: string,
): string => {
  const message = String(data.message || fallback);
  const obs = (data.obs || {}) as {
    trace_id?: string;
    node_id?: string;
    error_code?: string;
  };
  return appendObsHint(message, {
    trace_id: obs.trace_id || String(data.trace_id || ""),
    node_id: obs.node_id || String(data.node_id || ""),
    error_code: String(data.error_code || ""),
  });
};

// ========== 风格管理 ==========

export const extractStyle = async (
  contentOrArticles: string | string[],
  name: string,
): Promise<WritingStyle> => {
  const articles = Array.isArray(contentOrArticles)
    ? contentOrArticles
    : [contentOrArticles];
  const response = await api.post<WritingStyle>("/api/styles/extract", {
    articles,
    style_name: name,
  });
  return response.data;
};

interface ExtractStyleStreamRequest {
  articles: string[];
  style_name: string;
  tags?: string;
}

interface ExtractStyleStreamCallbacks {
  onStart?: (data: Record<string, unknown>) => void;
  onProgress?: (data: Record<string, unknown>) => void;
  onChunk?: (delta: string) => void;
}

export const extractStyleWithStream = async (
  request: ExtractStyleStreamRequest,
  callbacks: ExtractStyleStreamCallbacks = {},
): Promise<WritingStyle> => {
  const response = await fetch(`${API_BASE_URL}/api/styles/extract/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok || !response.body) {
    const message = await response.text();
    throw new Error(message || `Extract style failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let createdStyle: WritingStyle | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const dataLine = chunk
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) {
        continue;
      }

      const parsed = parseSseJson(dataLine.slice(6));
      if (!parsed) {
        continue;
      }

      const eventType = String(parsed.type || "");
      if (eventType === "start") {
        callbacks.onStart?.(parsed);
        continue;
      }
      if (eventType === "progress") {
        callbacks.onProgress?.(parsed);
        continue;
      }
      if (eventType === "content") {
        callbacks.onChunk?.(String(parsed.delta || ""));
        continue;
      }
      if (eventType === "error") {
        throw new Error(String(parsed.message || "风格提取失败"));
      }
      if (eventType === "done") {
        createdStyle = {
          id: Number(parsed.id || 0),
          name: String(parsed.name || request.style_name),
          style_description: String(parsed.style_description || ""),
          tags: parsed.tags ? String(parsed.tags) : undefined,
          created_at: String(parsed.created_at || new Date().toISOString()),
        };
      }
    }
  }

  if (!createdStyle) {
    throw new Error("风格提取未返回完成结果");
  }

  return createdStyle;
};

export const getStyles = async (): Promise<WritingStyle[]> => {
  const response = await api.get<WritingStyle[]>("/api/styles");
  return response.data;
};

export const getStyle = async (id: number): Promise<WritingStyle> => {
  const response = await api.get<WritingStyle>(`/api/styles/${id}`);
  return response.data;
};

export interface UpdateStyleRequest {
  name: string;
  tags?: string;
  example_text?: string;
  style_description: string;
}

export const updateStyle = async (
  id: number,
  data: UpdateStyleRequest,
): Promise<WritingStyle> => {
  const response = await api.patch<WritingStyle>(`/api/styles/${id}`, data);
  return response.data;
};

export const deleteStyle = async (id: number): Promise<void> => {
  await api.delete(`/api/styles/${id}`);
};

// ========== 素材管理 ==========

export interface AddMaterialRequest {
  content?: string;
  source?: string;
  tags?: string;
  title?: string;
}

export interface UpdateMaterialRequest {
  title?: string;
  content?: string;
  source?: string;
  tags?: string;
}

export const addMaterial = async (
  payloadOrContent: AddMaterialRequest | string,
  source?: string,
  tags?: string,
  title?: string,
): Promise<Material> => {
  const payload: AddMaterialRequest =
    typeof payloadOrContent === "string"
      ? {
          content: payloadOrContent,
          source,
          tags,
          title,
        }
      : payloadOrContent;

  const content = payload.content?.trim();
  const sourceUrl = payload.source?.trim();
  const derivedTitle = payload.title?.trim() || content?.split("\n")[0].slice(0, 50);

  const response = await api.post<Material>("/api/materials", {
    title: derivedTitle || undefined,
    content,
    source_url: sourceUrl,
    tags: payload.tags?.trim() || undefined,
  });
  return response.data;
};

export interface MaterialsPageQuery {
  page?: number;
  limit?: number;
  tags?: string;
  keyword?: string;
}

export const getMaterialsPage = async (
  query: MaterialsPageQuery = {},
): Promise<PaginatedResponse<Material>> => {
  const params = new URLSearchParams();
  params.set("page", String(query.page ?? 1));
  params.set("limit", String(query.limit ?? 10));
  if (query.tags) {
    params.set("tags", query.tags);
  }
  if (query.keyword) {
    params.set("keyword", query.keyword);
  }

  const response = await api.get<PaginatedResponse<Material>>(
    `/api/materials?${params.toString()}`,
  );
  return response.data;
};

export const getMaterials = async (): Promise<Material[]> => {
  const response = await api.get<{ items: Material[] }>("/api/materials");
  return response.data.items;
};

export const getMaterial = async (id: number): Promise<Material> => {
  const response = await api.get<Material>(`/api/materials/${id}`);
  return response.data;
};

export const deleteMaterial = async (id: number): Promise<void> => {
  await api.delete(`/api/materials/${id}`);
};

export const updateMaterial = async (
  id: number,
  payload: UpdateMaterialRequest,
): Promise<Material> => {
  const response = await api.patch<Material>(`/api/materials/${id}`, {
    title: payload.title,
    content: payload.content,
    source_url: payload.source,
    tags: payload.tags,
  });
  return response.data;
};

export const retrieveMaterials = async (
  query: string,
  topK = 5,
): Promise<MaterialRetrieveResponse> => {
  const response = await api.post<MaterialRetrieveResponse>("/api/materials/retrieve", {
    query,
    top_k: topK,
  });
  return response.data;
};

// ========== GitHub 趋势 ==========

export const getGithubTrends = async (
  query?: {
    weekKey?: string;
    periodType?: "daily" | "weekly";
    periodKey?: string;
  } | string,
): Promise<GithubTrendSnapshot> => {
  const params = new URLSearchParams();
  if (typeof query === "string") {
    if (query) {
      params.set("week_key", query);
    }
  } else if (query) {
    if (query.weekKey) {
      params.set("week_key", query.weekKey);
    }
    if (query.periodType) {
      params.set("period_type", query.periodType);
    }
    if (query.periodKey) {
      params.set("period_key", query.periodKey);
    }
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await api.get<GithubTrendSnapshot>(
    `/api/github-trends${suffix}`,
  );
  return response.data;
};

export const getGithubTrendWeeks = async (): Promise<GithubTrendWeekOption[]> => {
  const response = await api.get<GithubTrendWeekOption[]>("/api/github-trends/weeks");
  return response.data;
};

export const getGithubTrendPeriods = async (
  periodType: "daily" | "weekly",
): Promise<GithubTrendPeriodOption[]> => {
  const response = await api.get<GithubTrendPeriodOption[]>(
    `/api/github-trends/periods?${new URLSearchParams({ period_type: periodType }).toString()}`,
  );
  return response.data;
};

export const refreshGithubTrends = async (query?: {
  periodType?: "daily" | "weekly";
  periodKey?: string;
  retryUntranslatedOnly?: boolean;
}): Promise<GithubTrendSnapshot> => {
  const response = await api.post<GithubTrendSnapshot>("/api/github-trends/refresh", {
    period_type: query?.periodType || "weekly",
    period_key: query?.periodKey,
    retry_untranslated_only: Boolean(query?.retryUntranslatedOnly),
  });
  return response.data;
};

export const addGithubTrendItemToMaterials = async (
  query:
    | string
    | {
        weekKey?: string;
        periodType?: "daily" | "weekly";
        periodKey?: string;
      },
  repoFullName: string,
  enhance = true,
): Promise<GithubTrendAddMaterialResponse> => {
  const payload: Record<string, string | boolean> = { repo_full_name: repoFullName, enhance };
  if (typeof query === "string") {
    payload.week_key = query;
  } else {
    if (query.weekKey) {
      payload.week_key = query.weekKey;
    }
    if (query.periodType) {
      payload.period_type = query.periodType;
    }
    if (query.periodKey) {
      payload.period_key = query.periodKey;
    }
  }
  const response = await api.post<GithubTrendAddMaterialResponse>(
    "/api/github-trends/materials/add-item",
    payload,
  );
  return response.data;
};

export const addGithubTrendWeekDigestToMaterials = async (
  weekKey: string,
): Promise<{ status: string; material_id: number; created: boolean }> => {
  const response = await api.post<{ status: string; material_id: number; created: boolean }>(
    "/api/github-trends/materials/add-week-digest",
    {
      week_key: weekKey,
    },
  );
  return response.data;
};

export const buildGithubTrendItemRewrite = async (
  query:
    | string
    | {
        weekKey?: string;
        periodType?: "daily" | "weekly";
        periodKey?: string;
      },
  repoFullName: string,
  enhance = true,
): Promise<GithubTrendRewriteBuildResponse> => {
  const payload: Record<string, string | boolean> = { repo_full_name: repoFullName, enhance };
  if (typeof query === "string") {
    payload.week_key = query;
  } else {
    if (query.weekKey) {
      payload.week_key = query.weekKey;
    }
    if (query.periodType) {
      payload.period_type = query.periodType;
    }
    if (query.periodKey) {
      payload.period_key = query.periodKey;
    }
  }
  const response = await api.post<GithubTrendRewriteBuildResponse>(
    "/api/github-trends/rewrite/build-item",
    payload,
  );
  return response.data;
};

// ========== Linux.do 趋势 ==========

export interface LinuxDoTrendsQuery {
  periodType: "weekly" | "monthly";
  periodKey?: string;
  tag?: string;
  limit?: number;
}

const normalizeLinuxDoTrendItem = (
  item: Record<string, unknown>,
): LinuxDoTrendItem => ({
  topic_id: Number(item.topic_id || 0),
  title: String(item.title || ""),
  content: String(item.content || item.summary || item.content_excerpt || item.excerpt || ""),
  summary: String(item.summary || item.content || item.content_excerpt || item.excerpt || ""),
  content_excerpt: String(item.content_excerpt || item.content || item.summary || item.excerpt || ""),
  excerpt: String(item.excerpt || item.content || item.summary || item.content_excerpt || ""),
  author: String(item.author || ""),
  tags: Array.isArray(item.tags)
    ? (item.tags as unknown[]).map((value) => String(value || "").trim()).filter(Boolean)
    : String(item.tags || "")
        .split(/[,，\s]+/)
        .map((value) => value.trim())
        .filter(Boolean),
  replies_count: Number(item.replies_count ?? item.reply_count ?? 0),
  views_count: Number(item.views_count ?? item.view_count ?? 0),
  likes_count: Number(item.likes_count ?? item.like_count ?? 0),
  publish_time: String(item.publish_time || ""),
  created_at: String(item.created_at || ""),
  source_url: String(item.source_url || item.topic_url || ""),
});

const normalizeLinuxDoTrendSnapshot = (
  data: Record<string, unknown>,
): LinuxDoTrendSnapshot => ({
  period_type: data.period_type === "monthly" ? "monthly" : "weekly",
  period_key: String(data.period_key || ""),
  period_label: String(data.requested_period_key || data.period_key || ""),
  updated_at: String(data.updated_at || data.captured_at || data.snapshot_date || ""),
  captured_at: String(data.captured_at || ""),
  is_stale: Boolean(data.is_stale),
  is_refreshing: Boolean(data.is_refreshing),
  fetch_error: (data.fetch_error as string | null | undefined) ?? null,
  available_tags: Array.isArray(data.available_tags)
    ? (data.available_tags as unknown[]).map((value) => String(value || "").trim()).filter(Boolean)
    : [],
  items: Array.isArray(data.items)
    ? (data.items as Record<string, unknown>[]).map(normalizeLinuxDoTrendItem)
    : [],
});

export const getLinuxDoTrends = async (
  query: LinuxDoTrendsQuery,
): Promise<LinuxDoTrendSnapshot> => {
  const params = new URLSearchParams({
    period_type: query.periodType,
    limit: String(query.limit ?? 20),
  });
  if (query.periodKey) {
    params.set("period_key", query.periodKey);
  }
  if (query.tag) {
    params.set("tag", query.tag);
  }
  const response = await api.get<LinuxDoTrendSnapshot>(
    `/api/linuxdo-trends?${params.toString()}`,
  );
  return normalizeLinuxDoTrendSnapshot(response.data as unknown as Record<string, unknown>);
};

export const getLinuxDoTrendPeriods = async (
  periodType: "weekly" | "monthly",
): Promise<LinuxDoTrendPeriodOption[]> => {
  const response = await api.get<LinuxDoTrendPeriodOption[]>(
    `/api/linuxdo-trends/periods?${new URLSearchParams({
      period_type: periodType,
    }).toString()}`,
  );
  const rows = Array.isArray(response.data)
    ? (response.data as unknown as Record<string, unknown>[])
    : [];
  return rows.map((row) => ({
    period_type: periodType,
    period_key: String(row.period_key || ""),
    label: String(row.period_key || ""),
    latest_snapshot_date: String(row.latest_snapshot_date || ""),
    latest_captured_at: String(row.latest_captured_at || ""),
    has_archive: true,
  }));
};

export const refreshLinuxDoTrends = async (
  periodType: "weekly" | "monthly",
): Promise<LinuxDoTrendSnapshot> => {
  const response = await api.post<LinuxDoTrendSnapshot>("/api/linuxdo-trends/refresh", {
    period_type: periodType,
  });
  return normalizeLinuxDoTrendSnapshot(response.data as unknown as Record<string, unknown>);
};

export const getLinuxDoTrendTopicDetail = async (
  topicId: number,
): Promise<LinuxDoTrendTopicDetail> => {
  const response = await api.get<LinuxDoTrendTopicDetail>(
    `/api/linuxdo-trends/topics/${topicId}`,
  );
  const raw = response.data as unknown as Record<string, unknown>;
  return {
    topic_id: Number(raw.topic_id || topicId),
    title: String(raw.title || ""),
    content: String(raw.content || ""),
    author: String(raw.author || ""),
    tags: Array.isArray(raw.tags)
      ? (raw.tags as unknown[]).map((value) => String(value || "").trim()).filter(Boolean)
      : String(raw.tags || "")
          .split(/[,，\s]+/)
          .map((value) => value.trim())
          .filter(Boolean),
    source_url: String(raw.source_url || raw.topic_url || ""),
    created_at: String(raw.created_at || raw.publish_time || ""),
    updated_at: String(raw.updated_at || raw.publish_time || ""),
    replies_count: Number(raw.replies_count ?? raw.reply_count ?? 0),
    views_count: Number(raw.views_count ?? raw.view_count ?? 0),
    likes_count: Number(raw.likes_count ?? raw.like_count ?? 0),
  };
};

export const addLinuxDoTrendItemToMaterials = async (
  periodType: "weekly" | "monthly",
  periodKey: string,
  topicId: number,
): Promise<LinuxDoTrendAddMaterialResponse> => {
  const response = await api.post<LinuxDoTrendAddMaterialResponse>(
    "/api/linuxdo-trends/materials/add-item",
    {
      period_type: periodType,
      period_key: periodKey,
      topic_id: topicId,
    },
  );
  return response.data;
};

export const buildLinuxDoTrendItemRewrite = async (
  periodType: "weekly" | "monthly",
  periodKey: string,
  topicId: number,
): Promise<LinuxDoTrendRewriteBuildResponse> => {
  const response = await api.post<LinuxDoTrendRewriteBuildResponse>(
    "/api/linuxdo-trends/rewrite/build-item",
    {
      period_type: periodType,
      period_key: periodKey,
      topic_id: topicId,
    },
  );
  return response.data;
};

// ========== 小红书热点 ==========

export const getXhsTrendCategories = async (): Promise<XhsTrendCategory[]> => {
  const response = await api.get<XhsTrendCategory[]>("/api/xhs-trends/categories");
  return response.data;
};

export const getXhsTrends = async (
  categoryKey: string,
  sort: "hot" | "latest" = "hot",
  limit = 10,
): Promise<XhsTrendListResponse> => {
  const params = new URLSearchParams({
    category_key: categoryKey,
    sort,
    limit: String(limit),
  });
  const response = await api.get<XhsTrendListResponse>(`/api/xhs-trends?${params.toString()}`);
  return response.data;
};

export interface RefreshXhsTrendsRequestOptions {
  background?: boolean;
  timeoutMs?: number;
}

export const refreshXhsTrends = async (
  categoryKey?: string,
  options: RefreshXhsTrendsRequestOptions = {},
): Promise<XhsTrendRefreshResponse> => {
  const response = await api.post<XhsTrendRefreshResponse>(
    "/api/xhs-trends/refresh",
    {
      category_key: categoryKey || undefined,
      background: options.background ?? false,
    },
    {
      timeout: options.timeoutMs ?? 60000,
    },
  );
  return response.data;
};

export const streamXhsTrendAnalysis = (
  categoryKey: string,
  callbacks: XhsTrendAnalysisStreamCallbacks = {},
): EventSource => {
  const eventSource = new EventSource(
    `${API_BASE_URL}/api/xhs-trends/analysis/stream?${new URLSearchParams({
      category_key: categoryKey,
    })}`,
  );

  eventSource.onmessage = (event) => {
    const data = parseSseJson(event.data);
    if (!data) {
      return;
    }

    const streamEvent = data as unknown as XhsTrendAnalysisStreamEvent;
    switch (streamEvent.type) {
      case "start":
        callbacks.onStart?.(streamEvent);
        break;
      case "progress":
        callbacks.onProgress?.(streamEvent);
        break;
      case "done":
        if (streamEvent.data) {
          callbacks.onDone?.(streamEvent.data);
        }
        eventSource.close();
        break;
      case "error": {
        const obs = (data.obs || {}) as {
          trace_id?: string;
          node_id?: string;
          error_code?: string;
        };
        callbacks.onError?.(
          sseErrorWithObs(data, "Unknown error"),
          String(obs.trace_id || data.trace_id || ""),
        );
        eventSource.close();
        break;
      }
      default:
        break;
    }
  };

  eventSource.onerror = () => {
    callbacks.onError?.("Connection error");
    eventSource.close();
  };

  return eventSource;
};

// ========== 改写 ==========

export interface RewriteRequest {
  source_article: string;
  style_id: number;
  target_words?: number;
  enable_rag?: boolean;
  rag_top_k?: number;
}

export const rewriteWithStream = (
  request: RewriteRequest,
  onChunk: (chunk: string) => void,
  onError: (error: string) => void,
  onDone: (data?: Record<string, unknown>) => void,
  onStart?: (taskId: number) => void,
): EventSource => {
  const eventSource = new EventSource(
    `${API_BASE_URL}/api/rewrites/stream?${new URLSearchParams({
      source_article: request.source_article,
      style_id: request.style_id.toString(),
      target_words: request.target_words?.toString() || "1000",
      enable_rag: request.enable_rag?.toString() || "false",
      rag_top_k: request.rag_top_k?.toString() || "3",
    })}`,
  );

  eventSource.onmessage = (event) => {
    const data = parseSseJson(event.data);
    if (!data) {
      return;
    }

    switch (data.type) {
      case "content":
        onChunk(String(data.delta || ""));
        break;
      case "start": {
        const taskId = Number(data.task_id || 0);
        if (taskId > 0) {
          onStart?.(taskId);
        }
        break;
      }
      case "done":
        onDone(data);
        eventSource.close();
        break;
      case "error":
        onError(sseErrorWithObs(data, "Unknown error"));
        eventSource.close();
        break;
      default:
        break;
    }
  };

  eventSource.onerror = () => {
    onError("Connection error");
    eventSource.close();
  };

  return eventSource;
};

export const startRewrite = async (
  request: RewriteRequest,
): Promise<RewriteRecord> => {
  return new Promise((resolve, reject) => {
    let taskId: number | null = null;
    let settled = false;

    rewriteWithStream(
      request,
      () => {
        // 内容由调用方决定是否展示
      },
      (error) => {
        if (!settled) {
          settled = true;
          reject(new Error(error));
        }
      },
      async () => {
        if (settled) {
          return;
        }
        if (!taskId) {
          settled = true;
          reject(new Error("未获取到改写任务ID"));
          return;
        }
        try {
          const record = await getRewrite(taskId);
          settled = true;
          resolve(record);
        } catch (e) {
          settled = true;
          reject(e);
        }
      },
      (id) => {
        taskId = id;
      },
    );
  });
};

export const getRewrite = async (id: number): Promise<RewriteRecord> => {
  const response = await api.get<RewriteRecord>(`/api/rewrites/${id}`);
  return response.data;
};

export interface RewritesPageQuery {
  page?: number;
  limit?: number;
  styleId?: number;
}

export const getRewritesPage = async (
  query: RewritesPageQuery = {},
): Promise<PaginatedResponse<RewriteRecord>> => {
  const params = new URLSearchParams();
  params.set("page", String(query.page ?? 1));
  params.set("limit", String(query.limit ?? 10));
  if (query.styleId !== undefined) {
    params.set("style_id", String(query.styleId));
  }

  const response = await api.get<PaginatedResponse<RewriteRecord>>(
    `/api/rewrites?${params.toString()}`,
  );
  return response.data;
};

export const getRewrites = async (): Promise<RewriteRecord[]> => {
  const response = await api.get<{ items: RewriteRecord[] }>("/api/rewrites");
  return response.data.items;
};

// ========== 审核 ==========

export interface ReviewRequest {
  rewrite_id: number;
}

export const reviewWithStream = (
  rewriteId: number,
  onChunk: (chunk: string) => void,
  onError: (error: string) => void,
  onDone: (data?: Record<string, unknown>) => void,
  onStart?: (reviewId: number) => void,
): EventSource => {
  const eventSource = new EventSource(
    `${API_BASE_URL}/api/reviews/stream?rewrite_id=${rewriteId}`,
  );

  eventSource.onmessage = (event) => {
    const data = parseSseJson(event.data);
    if (!data) {
      return;
    }

    switch (data.type) {
      case "content":
        onChunk(String(data.delta || ""));
        break;
      case "start": {
        const reviewId = Number(data.review_id || 0);
        if (reviewId > 0) {
          onStart?.(reviewId);
        }
        break;
      }
      case "done":
        onDone(data);
        eventSource.close();
        break;
      case "error":
        onError(sseErrorWithObs(data, "Unknown error"));
        eventSource.close();
        break;
      default:
        break;
    }
  };

  eventSource.onerror = () => {
    onError("Connection error");
    eventSource.close();
  };

  return eventSource;
};

export const startReview = async (
  request: ReviewRequest,
): Promise<ReviewRecord> => {
  return new Promise((resolve, reject) => {
    let reviewId: number | null = null;
    let settled = false;

    reviewWithStream(
      request.rewrite_id,
      () => {
        // 内容由调用方决定是否展示
      },
      (error) => {
        if (!settled) {
          settled = true;
          reject(new Error(error));
        }
      },
      async () => {
        if (settled) {
          return;
        }
        if (!reviewId) {
          settled = true;
          reject(new Error("未获取到审核ID"));
          return;
        }
        try {
          const record = await getReview(reviewId);
          settled = true;
          resolve(record);
        } catch (e) {
          settled = true;
          reject(e);
        }
      },
      (id) => {
        reviewId = id;
      },
    );
  });
};

export const getReview = async (id: number): Promise<ReviewRecord> => {
  const response = await api.get<ReviewRecord>(`/api/reviews/${id}`);
  return response.data;
};

export const getReviewsByRewrite = async (
  rewriteId: number,
): Promise<{ items: ReviewRecord[]; total: number }> => {
  const response = await api.get<{ items: ReviewRecord[]; total: number }>(
    `/api/reviews/rewrite/${rewriteId}`,
  );
  return response.data;
};

export const manualEdit = async (
  reviewId: number,
  editedContent: string,
  editNote?: string,
): Promise<ManualEditRecord> => {
  const response = await api.post<ManualEditRecord>("/api/reviews/manual-edit", {
    review_id: reviewId,
    edited_content: editedContent,
    edit_note: editNote,
  });
  return response.data;
};

export const getManualEdit = async (
  reviewId: number,
): Promise<ManualEditRecord> => {
  const response = await api.get<ManualEditRecord>(
    `/api/reviews/manual-edit/${reviewId}`,
  );
  return response.data;
};

// ========== 封面 ==========

export interface CoverRequest {
  rewrite_id: number;
  style_id?: number;
  custom_prompt?: string;
  size?: "2.35:1" | "1:1" | "9:16" | "3:4" | "1k" | "2k" | "4k";
}

export const createManualCoverRewrite = async (
  payload: ManualCoverRewriteRequest,
): Promise<ManualCoverRewriteResponse> => {
  const response = await api.post<ManualCoverRewriteResponse>(
    "/api/covers/manual-rewrite",
    payload,
  );
  return response.data;
};

export const getCover = async (id: number): Promise<CoverRecord> => {
  const response = await api.get<CoverRecord>(`/api/covers/${id}`);
  return response.data;
};

export const getCoverByRewrite = async (
  rewriteId: number,
): Promise<CoverRecord> => {
  const response = await api.get<CoverRecord>(`/api/covers/rewrite/${rewriteId}`);
  return response.data;
};

export const getCoversByRewrites = async (
  rewriteIds: number[],
): Promise<CoverRecord[]> => {
  if (rewriteIds.length === 0) {
    return [];
  }

  const params = new URLSearchParams();
  rewriteIds.forEach((id) => params.append("rewrite_ids", id.toString()));

  const response = await api.get<{ items: CoverRecord[] }>(
    `/api/covers/by-rewrites?${params.toString()}`,
  );
  return response.data.items;
};

export const coverWithStream = (
  request: CoverRequest,
  onProgress: (data: SSEMessage) => void,
  onError: (error: string) => void,
  onDone: (data: SSEMessage) => void,
): EventSource => {
  const params = new URLSearchParams({
    rewrite_id: request.rewrite_id.toString(),
  });
  if (request.style_id !== undefined) {
    params.set("style_id", request.style_id.toString());
  }
  if (request.custom_prompt) {
    params.set("custom_prompt", request.custom_prompt);
  }
  if (request.size) {
    params.set("size", request.size);
  }

  const eventSource = new EventSource(
    `${API_BASE_URL}/api/covers/stream?${params.toString()}`,
  );

  eventSource.onmessage = (event) => {
    const parsed = parseSseJson(event.data);
    if (!parsed) {
      return;
    }
    const data = parsed as unknown as SSEMessage;

    if (data.type === "error") {
      onError(
        sseErrorWithObs(
          data as unknown as Record<string, unknown>,
          String(data.error || "Unknown error"),
        ),
      );
      eventSource.close();
      return;
    }

    onProgress(data);

    if (data.type === "done") {
      onDone(data);
      eventSource.close();
    }
  };

  eventSource.onerror = () => {
    onError("Connection error");
    eventSource.close();
  };

  return eventSource;
};

export const startCover = async (
  request: CoverRequest,
): Promise<CoverRecord> => {
  return new Promise((resolve, reject) => {
    let settled = false;
    coverWithStream(
      request,
      () => {
        // 进度由调用方决定是否展示
      },
      (error) => {
        if (!settled) {
          settled = true;
          reject(new Error(error));
        }
      },
      async (data) => {
        if (settled) {
          return;
        }
        const coverId = Number(data.id || 0);
        if (!coverId) {
          settled = true;
          reject(new Error("未获取到封面ID"));
          return;
        }
        try {
          const cover = await getCover(coverId);
          settled = true;
          resolve(cover);
        } catch (e) {
          settled = true;
          reject(e);
        }
      },
    );
  });
};

// ========== 完整工作流 ==========

const readWorkflowSse = async (
  response: Response,
  callbacks: WorkflowStreamCallbacks = {},
): Promise<WorkflowStreamEvent[]> => {
  if (!response.ok || !response.body) {
    const message = await response.text();
    throw new Error(message || `Workflow request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  const events: WorkflowStreamEvent[] = [];

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const dataLine = chunk
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (!dataLine) {
        continue;
      }
      const parsed = parseSseJson(dataLine.slice(6));
      if (!parsed) {
        continue;
      }
      const event = parsed as unknown as WorkflowStreamEvent;
      events.push(event);

      switch (event.type) {
        case "stage":
          callbacks.onStage?.(event);
          break;
        case "progress":
          callbacks.onProgress?.(event);
          break;
        case "content":
          callbacks.onContent?.(event);
          break;
        case "review_done":
          callbacks.onReviewDone?.(event);
          break;
        case "done":
          callbacks.onDone?.(event);
          break;
        case "error":
          callbacks.onError?.(event);
          break;
        default:
          break;
      }
    }
  }

  return events;
};

export const createWorkflowJob = async (
  request: WorkflowLoopRequest,
  signal?: AbortSignal,
): Promise<WorkflowJobCreateResponse> => {
  const response = await api.post<WorkflowJobCreateResponse>(
    "/api/reviews/workflow/jobs",
    {
      source_article: request.source_article,
      style_id: request.style_id,
      target_words: request.target_words ?? 1000,
      enable_rag: request.enable_rag ?? false,
      rag_top_k: request.rag_top_k ?? 3,
      max_retries: request.max_retries ?? 1,
      idempotency_key: request.idempotency_key,
      force_new: request.force_new ?? false,
    },
    {
      signal,
    },
  );
  return response.data;
};

export const getLatestWorkflowJobByRewrite = async (
  rewriteId: number,
): Promise<WorkflowJobStatusResponse> => {
  const response = await api.get<WorkflowJobStatusResponse>(
    `/api/reviews/workflow/jobs/by-rewrite/${rewriteId}`,
  );
  return response.data;
};

export const streamWorkflowJobEvents = async (
  jobId: number,
  callbacks: WorkflowStreamCallbacks = {},
  signal?: AbortSignal,
  fromSeq = 0,
): Promise<WorkflowStreamEvent[]> => {
  const response = await fetch(
    `${API_BASE_URL}/api/reviews/workflow/jobs/${jobId}/stream?from_seq=${fromSeq}`,
    { signal },
  );
  return readWorkflowSse(response, callbacks);
};

export const runWorkflowWithStream = async (
  request: WorkflowLoopRequest,
  callbacks: WorkflowStreamCallbacks = {},
  signal?: AbortSignal,
): Promise<WorkflowStreamEvent[]> => {
  const { job_id } = await createWorkflowJob(request, signal);
  return streamWorkflowJobEvents(job_id, callbacks, signal, 0);
};

export const runFullWorkflow = async (
  sourceArticle: string,
  styleId?: number,
  targetWords?: number,
): Promise<{
  rewrite: RewriteRecord;
  review?: ReviewRecord;
  cover?: CoverRecord;
  events: WorkflowStreamEvent[];
}> => {
  if (!styleId) {
    throw new Error("styleId is required");
  }

  const events = await runWorkflowWithStream({
    source_article: sourceArticle,
    style_id: styleId,
    target_words: targetWords || 1000,
    enable_rag: false,
  });

  const doneEvent = [...events]
    .reverse()
    .find((event) => event.type === "done");
  const rewriteId = Number(doneEvent?.rewrite_id || 0);
  const reviewId = Number(doneEvent?.review_id || 0);

  if (!rewriteId) {
    throw new Error("Workflow completed but rewrite_id is missing");
  }

  const rewrite = await getRewrite(rewriteId);
  const review = reviewId ? await getReview(reviewId) : undefined;

  return {
    rewrite,
    review,
    cover: undefined,
    events,
  };
};

// ========== 封面风格管理 ==========

export interface CoverStyleCreate {
  name: string;
  prompt_template: string;
  description?: string;
}

export const createCoverStyle = async (
  data: CoverStyleCreate,
): Promise<CoverStyle> => {
  const response = await api.post<CoverStyle>("/api/covers/styles", data);
  return response.data;
};

export const getCoverStyles = async (): Promise<CoverStyle[]> => {
  const response = await api.get<CoverStyle[]>("/api/covers/styles");
  return response.data;
};

export const getCoverStyle = async (id: number): Promise<CoverStyle> => {
  const response = await api.get<CoverStyle>(`/api/covers/styles/${id}`);
  return response.data;
};

export const deleteCoverStyle = async (id: number): Promise<void> => {
  await api.delete(`/api/covers/styles/${id}`);
};

export { handleError };
