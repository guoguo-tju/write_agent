import axios, { AxiosError } from "axios";
import type {
  WritingStyle,
  Material,
  RewriteRecord,
  ReviewRecord,
  CoverRecord,
  CoverStyle,
  SSEMessage,
} from "../types";

// Re-export types
export type {
  WritingStyle,
  Material,
  RewriteRecord,
  ReviewRecord,
  CoverRecord,
  CoverStyle,
  SSEMessage,
};

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  headers: {
    "Content-Type": "application/json",
  },
});

// 错误处理
const handleError = (error: unknown): string => {
  if (error instanceof AxiosError) {
    return error.response?.data?.detail || error.message;
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

export const deleteStyle = async (id: number): Promise<void> => {
  await api.delete(`/api/styles/${id}`);
};

// ========== 素材管理 ==========

export const addMaterial = async (
  content: string,
  source?: string,
  tags?: string,
  title?: string,
): Promise<Material> => {
  const derivedTitle =
    title?.trim() ||
    source?.trim() ||
    content.trim().split("\n")[0].slice(0, 50) ||
    "未命名素材";

  const response = await api.post<Material>("/api/materials", {
    title: derivedTitle,
    content,
    source_url: source,
    tags,
  });
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
        onError(String(data.message || "Unknown error"));
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
        onError(String(data.message || "Unknown error"));
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
): Promise<ReviewRecord> => {
  const response = await api.post<ReviewRecord>("/api/reviews/manual-edit", {
    review_id: reviewId,
    edited_content: editedContent,
    edit_note: editNote,
  });
  return response.data;
};

// ========== 封面 ==========

export interface CoverRequest {
  rewrite_id: number;
  style_id?: number;
  custom_prompt?: string;
  size?: "2.35:1" | "1:1" | "9:16" | "3:4" | "1k" | "2k" | "4k";
}

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
      onError(String(data.message || data.error || "Unknown error"));
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

interface WorkflowStreamEvent {
  node: string;
  state: Record<string, unknown>;
}

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

  const response = await fetch(`${API_BASE_URL}/api/reviews/workflow`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_article: sourceArticle,
      style_id: styleId,
      target_words: targetWords || 1000,
      enable_rag: false,
      max_retries: 3,
    }),
  });

  if (!response.ok || !response.body) {
    throw new Error(`Workflow request failed: ${response.status}`);
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
    }
  }

  const lastState = events[events.length - 1]?.state;
  const rewriteId = Number(lastState?.rewrite_id || 0);
  const reviewId = Number(lastState?.review_id || 0);

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
