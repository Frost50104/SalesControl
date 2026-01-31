import { getToken, getBaseUrl } from '../auth/tokenStore';
import type {
  DailyAnalyticsResponse,
  DialogueListResponse,
  DialogueDetail,
  PointsResponse,
  CreateReviewRequest,
  ReviewResponse,
  ReviewListResponse,
  RerunResponse,
  ReviewReason,
  ReviewStatus,
} from './types';

class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const baseUrl = getBaseUrl();
  const token = getToken();

  if (!baseUrl || !token) {
    throw new ApiError(401, 'Not authenticated');
  }

  const url = `${baseUrl}${endpoint}`;
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
    ...options?.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const errorData = await response.json();
      message = errorData.detail || message;
    } catch {
      // ignore JSON parse error
    }
    throw new ApiError(response.status, message);
  }

  return response.json();
}

export async function checkHealth(): Promise<boolean> {
  const baseUrl = getBaseUrl();
  if (!baseUrl) return false;

  try {
    const response = await fetch(`${baseUrl}/health`);
    return response.ok;
  } catch {
    return false;
  }
}

export async function validateToken(): Promise<boolean> {
  const today = new Date().toISOString().split('T')[0];
  try {
    await fetchApi<DailyAnalyticsResponse>(`/api/v1/analytics/daily?date=${today}`);
    return true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return false;
    }
    // Other errors (like 500 or network issues) might mean the API is reachable but has issues
    // We'll treat non-401 errors as "token valid but other issue"
    throw error;
  }
}

export async function fetchDaily(
  date: string,
  pointId?: string
): Promise<DailyAnalyticsResponse> {
  let endpoint = `/api/v1/analytics/daily?date=${date}`;
  if (pointId) {
    endpoint += `&point_id=${pointId}`;
  }
  return fetchApi<DailyAnalyticsResponse>(endpoint);
}

export async function fetchDialogues(
  date: string,
  options?: {
    pointId?: string;
    attempted?: string;
    minQuality?: number;
    limit?: number;
    offset?: number;
  }
): Promise<DialogueListResponse> {
  const params = new URLSearchParams({ date });

  if (options?.pointId) {
    params.append('point_id', options.pointId);
  }
  if (options?.attempted) {
    params.append('attempted', options.attempted);
  }
  if (options?.minQuality !== undefined) {
    params.append('min_quality', options.minQuality.toString());
  }
  if (options?.limit !== undefined) {
    params.append('limit', options.limit.toString());
  }
  if (options?.offset !== undefined) {
    params.append('offset', options.offset.toString());
  }

  return fetchApi<DialogueListResponse>(`/api/v1/analytics/dialogues?${params}`);
}

export async function fetchDialogueDetail(
  dialogueId: string
): Promise<DialogueDetail> {
  return fetchApi<DialogueDetail>(`/api/v1/analytics/dialogues/${dialogueId}`);
}

export async function fetchPoints(days: number = 30): Promise<PointsResponse> {
  return fetchApi<PointsResponse>(`/api/v1/analytics/points?days=${days}`);
}

// Review API functions
export async function createReview(
  dialogueId: string,
  request: CreateReviewRequest
): Promise<ReviewResponse> {
  return fetchApi<ReviewResponse>(`/api/v1/reviews/${dialogueId}`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export async function fetchReviews(options?: {
  date?: string;
  pointId?: string;
  status?: ReviewStatus;
  reason?: ReviewReason;
  limit?: number;
  offset?: number;
}): Promise<ReviewListResponse> {
  const params = new URLSearchParams();

  if (options?.date) {
    params.append('date', options.date);
  }
  if (options?.pointId) {
    params.append('point_id', options.pointId);
  }
  if (options?.status) {
    params.append('status', options.status);
  }
  if (options?.reason) {
    params.append('reason', options.reason);
  }
  if (options?.limit !== undefined) {
    params.append('limit', options.limit.toString());
  }
  if (options?.offset !== undefined) {
    params.append('offset', options.offset.toString());
  }

  const query = params.toString();
  return fetchApi<ReviewListResponse>(`/api/v1/reviews${query ? `?${query}` : ''}`);
}

export async function resolveReview(
  reviewId: string,
  resolved: boolean = true
): Promise<ReviewResponse> {
  return fetchApi<ReviewResponse>(
    `/api/v1/reviews/${reviewId}?resolved=${resolved}`,
    { method: 'PATCH' }
  );
}

export async function rerunAnalysis(dialogueId: string): Promise<RerunResponse> {
  return fetchApi<RerunResponse>(`/api/v1/analysis/rerun/${dialogueId}`, {
    method: 'POST',
  });
}

export function getExportUrl(
  dateFrom: string,
  dateTo: string,
  format: 'csv' | 'json' = 'json'
): string {
  const baseUrl = getBaseUrl();
  return `${baseUrl}/api/v1/exports/reviews?from=${dateFrom}&to=${dateTo}&format=${format}`;
}

export { ApiError };
