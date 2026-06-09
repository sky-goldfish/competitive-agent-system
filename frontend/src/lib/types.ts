export type Run = {
  id: string;
  title: string;
  user_requirement: string;
  requirement_summary: string | null;
  status: string;
  current_stage: string;
  error_message: string | null;
  clarification_question: string | null;
  feedback_loop_count: number;
  active_revision_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type CustomCompetitorInput = {
  name: string;
  website?: string;
  category: string;
  region?: 'global' | 'china' | null;
};

export type OverlapDimension = {
  dimension: string;
  detail: string;
};

export type Competitor = {
  id: string;
  run_id: string;
  name: string;
  website: string | null;
  description: string;
  category: string;
  region: 'global' | 'china' | null;
  confidence: number;
  selected: boolean;
  discovery_source: string;
  relationship_type: 'direct' | 'indirect' | 'substitute';
  relationship_reason: string | null;
  overlap_dimensions: OverlapDimension[] | null;
  created_at: string;
  updated_at: string;
};

export type Trace = {
  id: string;
  run_id: string;
  stage: string;
  status: string;
  input_json: string | null;
  output_json: string | null;
  error_message: string | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  created_at: string;
};

export type Evidence = {
  id: string;
  run_id: string;
  source_id: string;
  related_product: string;
  related_dimension: string;
  quote: string;
  summary: string;
  confidence: number;
};

export type Analysis = {
  id: string;
  run_id: string;
  competitor_id: string;
  positioning: string;
  target_users: string;
  core_features_json: string;
  pricing_summary: string;
  strengths_json: string;
  weaknesses_json: string;
  opportunities_json: string;
  custom_focus_analysis_json: string;
  evidence_ids_json: string;
  analysis_iteration: number;
  created_at: string;
};

export type Source = {
  id: string;
  run_id: string;
  competitor_id: string | null;
  title: string;
  url: string;
  snippet: string;
  source_type: string;
  source_type_label: string | null;
  credibility_score: number | null;
  rank_score: number | null;
  classification_reason: string | null;
  metadata_json: string | null;
  reference_id: number | null;
  provider: string;
  retrieved_at: string;
};

export type Report = {
  id: string;
  run_id: string;
  iteration: number;
  title: string;
  markdown_content: string;
  summary: string;
  competitor_names: string[];
  competitor_names_json: string | null;
  created_at: string;
  updated_at: string;
};

export type CitationAnalysisRef = {
  id: string;
  competitor_id: string;
  competitor_name: string;
  claim_types: string[];
};

export type CitationMapItem = {
  reference_id: number;
  source: Source;
  evidence: Evidence[];
  analyses: CitationAnalysisRef[];
};

export type CitationBundleEvidence = {
  source_reference_id: number | null;
  source_title: string | null;
  source_url: string | null;
  related_dimension: string | null;
  summary: string | null;
  quote: string | null;
  confidence: number | null;
};

export type CitationBundleClaim = {
  claim_type: string;
  label: string;
  text: string;
  evidence: CitationBundleEvidence[];
};

export type CitationBundleCompetitor = {
  competitor_id: string;
  competitor_name: string;
  analysis_iteration: number;
  claims: CitationBundleClaim[];
};

export type QAIssue = {
  id: string | null;
  dimension: string;
  severity: string;
  competitor_name: string;
  description: string;
  fix_suggestion: string;
  status: string | null;
  first_seen_iteration: number | null;
  last_seen_iteration: number | null;
  resolved_iteration: number | null;
  resolution_reason: string | null;
};

export type QARetryQuery = {
  competitor_name: string;
  slot: string;
  query: string;
};

export type ChatMessage = {
  id: string;
  run_id: string;
  role: string;
  content: string;
  intent: string | null;
  action_type: string | null;
  report_version: number | null;
  metadata_json: string | null;
  created_at: string;
};

export type ChatResponse = {
  message: ChatMessage;
  report_version: number | null;
  intent: string | null;
  action_type: string | null;
};

export type Revision = {
  id: string;
  run_id: string;
  base_report_iteration: number;
  target_report_iteration: number | null;
  user_message: string;
  intent: string | null;
  status: string;
  error_message: string | null;
  summary: string | null;
  chat_user_message_id: string | null;
  chat_assistant_message_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
};

export type RevisionTrace = {
  id: string;
  revision_id: string;
  stage: string;
  status: string;
  input_json: string | null;
  output_json: string | null;
  error_message: string | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
};

export type QAResult = {
  id: string;
  run_id: string;
  iteration: number;
  overall_score: number;
  dimension_scores: Record<string, number>;
  decision: string;
  check_phase: string;
  forced_pass: boolean;
  quality_warning: boolean;
  issues: QAIssue[];
  issue_checklist: QAIssue[];
  retry_instructions: string | null;
  retry_queries: QARetryQuery[];
  created_at: string;
};
