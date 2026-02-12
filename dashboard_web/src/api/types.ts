// API Response Types matching backend schemas

export interface HourlyStats {
  hour: number;
  dialogues_total: number;
  attempted_yes: number;
  attempted_no: number;
  attempted_uncertain: number;
  avg_quality: number;
  accepted_count: number;
  rejected_count: number;
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface DailyAnalyticsResponse {
  date: string;
  point_id: string | null;

  // Totals
  dialogues_total: number;
  dialogues_analyzed: number;
  dialogues_skipped: number;
  dialogues_error: number;

  // Upsell metrics
  attempted_yes: number;
  attempted_no: number;
  attempted_uncertain: number;
  attempted_rate: number;

  // Quality metrics
  avg_quality: number;
  quality_distribution: Record<number, number>;

  // Customer reaction
  accepted_count: number;
  rejected_count: number;
  unclear_count: number;
  accepted_rate: number;

  // Categories
  top_categories: CategoryCount[];

  // Hourly breakdown
  hourly: HourlyStats[];
}

export interface DialogueAnalysisSummary {
  dialogue_id: string;
  point_id?: string;
  point_name?: string;
  register_id?: string;
  register_name?: string;
  start_ts: string;
  end_ts: string;
  quality_score: number;
  attempted: string;
  categories: string[];
  customer_reaction: string;
  closing_question: boolean;
  summary: string;
  text_snippet: string | null;
}

export interface DialogueListResponse {
  date: string;
  point_id: string | null;
  total: number;
  dialogues: DialogueAnalysisSummary[];
}

export interface DialogueDetail {
  dialogue_id: string;
  point_id: string;
  point_name?: string;
  register_id: string;
  register_name?: string;
  start_ts: string;
  end_ts: string;

  // Analysis
  quality_score: number;
  attempted: string;
  categories: string[];
  customer_reaction: string;
  closing_question: boolean;
  summary: string;
  evidence_quotes: string[];
  confidence: number | null;

  // Review status
  review_status: string;

  // Transcript
  text: string;
}

export interface PointInfo {
  point_id: string;
  name: string | null;
  dialogue_count: number;
}

export interface PointsResponse {
  points: PointInfo[];
}

export interface ApiError {
  detail: string;
}

// Review types
export type ReviewReason =
  | 'bad_asr'
  | 'llm_missed_upsell'
  | 'llm_false_positive'
  | 'wrong_quality'
  | 'wrong_category'
  | 'other';

export type ReviewStatus = 'NONE' | 'FLAGGED' | 'RESOLVED';

export interface CorrectedAnalysis {
  attempted?: string;
  quality_score?: number;
  categories?: string[];
  closing_question?: boolean;
  customer_reaction?: string;
}

export interface CreateReviewRequest {
  reason: ReviewReason;
  notes?: string;
  corrected?: CorrectedAnalysis;
  reviewer?: string;
}

export interface ReviewResponse {
  review_id: string;
  dialogue_id: string;
  created_at: string;
  reviewer: string | null;
  flag: boolean;
  reason: string;
  notes: string | null;
  corrected: CorrectedAnalysis | null;
}

export interface ReviewWithDialogue {
  review_id: string;
  dialogue_id: string;
  created_at: string;
  reviewer: string | null;
  flag: boolean;
  reason: string;
  notes: string | null;
  corrected: CorrectedAnalysis | null;
  dialogue_start_ts: string;
  dialogue_end_ts: string;
  point_id: string;
  review_status: string;
  attempted: string | null;
  quality_score: number | null;
  categories: string[] | null;
  customer_reaction: string | null;
  text_snippet: string | null;
}

export interface ReviewListResponse {
  total: number;
  reviews: ReviewWithDialogue[];
}

export interface RerunResponse {
  dialogue_id: string;
  message: string;
  previous_analysis_archived: boolean;
}

// User management types
export interface UserResponse {
  user_id: string;
  username: string;
  full_name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: UserResponse;
}

export interface CreateUserRequest {
  username: string;
  password: string;
  full_name: string;
  is_admin: boolean;
}

export interface UpdateUserRequest {
  full_name?: string;
  password?: string;
  is_admin?: boolean;
  is_active?: boolean;
}

// Device management types
export interface Device {
  device_id: string;
  point_id: string;
  point_name?: string;
  register_id: string;
  register_name?: string;
  is_enabled: boolean;
  created_at: string;
  last_seen_at: string | null;
}
