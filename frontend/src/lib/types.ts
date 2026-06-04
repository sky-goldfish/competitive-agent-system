export type Run = {
  id: string;
  title: string;
  user_requirement: string;
  requirement_summary: string | null;
  status: string;
  current_stage: string;
  error_message: string | null;
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
  dimension: string;
  severity: string;
  competitor_name: string;
  description: string;
  fix_suggestion: string;
};

export type QAResult = {
  id: string;
  run_id: string;
  iteration: number;
  overall_score: number;
  decision: string;
  issues: QAIssue[];
  retry_instructions: string | null;
  created_at: string;
};
