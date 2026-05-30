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
  provider: string;
  retrieved_at: string;
};

export type Report = {
  id: string;
  run_id: string;
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
