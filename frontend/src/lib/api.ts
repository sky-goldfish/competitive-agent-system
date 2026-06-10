import type { Analysis, CallTrace, ChatMessage, ChatResponse, CitationBundleCompetitor, CitationMapItem, Competitor, CustomCompetitorInput, Evidence, KnowledgeClearResult, KnowledgeItem, KnowledgeRebuildResult, ObservabilityData, QAResult, Report, Revision, RevisionTrace, Run, Source, Trace } from './types';

const API_BASE = '/api';

async function request<T>(path: string, options?: RequestInit & { signal?: AbortSignal }): Promise<T> {
  const { headers: optionHeaders, ...restOptions } = options ?? {};
  const response = await fetch(`${API_BASE}${path}`, {
    ...restOptions,
    headers: {
      'Content-Type': 'application/json',
      ...optionHeaders,
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  try {
    return await response.json() as Promise<T>;
  } catch {
    throw new Error('Invalid JSON response from server');
  }
}

export type CreateRunInput = {
  userRequirement: string;
  mockDiscovery?: boolean;
};

export function createRun(input: CreateRunInput): Promise<Run> {
  return request<Run>('/runs', {
    method: 'POST',
    body: JSON.stringify({
      user_requirement: input.userRequirement,
      mock_discovery: Boolean(input.mockDiscovery),
    }),
  });
}

export function listRuns(): Promise<Run[]> {
  return request<Run[]>('/runs');
}

export function getRun(runId: string): Promise<Run> {
  return request<Run>(`/runs/${runId}`);
}

export function answerRunClarification(runId: string, answer: string): Promise<Run> {
  return request<Run>(`/runs/${runId}/clarification`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  });
}

export function deleteRun(runId: string): Promise<void> {
  return request<void>(`/runs/${runId}`, { method: 'DELETE' });
}

export function getCompetitors(runId: string): Promise<Competitor[]> {
  return request<Competitor[]>(`/runs/${runId}/competitors`);
}

export function confirmCompetitors(runId: string, competitorIds: string[], customCompetitors: CustomCompetitorInput[] = []): Promise<Run> {
  return request<Run>(`/runs/${runId}/competitors/confirm`, {
    method: 'POST',
    body: JSON.stringify({ competitor_ids: competitorIds, custom_competitors: customCompetitors }),
  });
}

export function getTimeline(runId: string): Promise<Trace[]> {
  return request<Trace[]>(`/runs/${runId}/timeline`);
}

export function getSources(runId: string): Promise<Source[]> {
  return request<Source[]>(`/runs/${runId}/sources`);
}

export function getReport(runId: string, iteration?: number): Promise<Report> {
  const params = iteration != null ? `?iteration=${iteration}` : '';
  return request<Report>(`/runs/${runId}/report${params}`);
}

export function getReportVersions(runId: string): Promise<Report[]> {
  return request<Report[]>(`/runs/${runId}/report/versions`);
}

export function getReportCitations(runId: string, iteration?: number): Promise<CitationMapItem[]> {
  const params = iteration != null ? `?iteration=${iteration}` : '';
  return request<CitationMapItem[]>(`/runs/${runId}/report/citations${params}`);
}

export function getReportCitationBundle(runId: string, iteration?: number): Promise<CitationBundleCompetitor[]> {
  const params = iteration != null ? `?iteration=${iteration}` : '';
  return request<CitationBundleCompetitor[]>(`/runs/${runId}/report/citation-bundle${params}`);
}

export function getEvidence(runId: string): Promise<Evidence[]> {
  return request<Evidence[]>(`/runs/${runId}/evidence`);
}

export type KnowledgeSearchInput = {
  q?: string;
  productName?: string;
  dimension?: string;
  limit?: number;
};

export function getKnowledgeItems(input: KnowledgeSearchInput = {}): Promise<KnowledgeItem[]> {
  const params = new URLSearchParams();
  if (input.q?.trim()) params.set('q', input.q.trim());
  if (input.productName?.trim()) params.set('product_name', input.productName.trim());
  if (input.dimension?.trim()) params.set('dimension', input.dimension.trim());
  if (input.limit) params.set('limit', String(input.limit));
  const query = params.toString();
  return request<KnowledgeItem[]>(`/knowledge/items${query ? `?${query}` : ''}`);
}

export function rebuildKnowledgeFromRun(runId: string): Promise<KnowledgeRebuildResult> {
  return request<KnowledgeRebuildResult>(`/knowledge/rebuild-from-run/${runId}`, {
    method: 'POST',
  });
}

export function clearKnowledgeItems(): Promise<KnowledgeClearResult> {
  return request<KnowledgeClearResult>('/knowledge/items', { method: 'DELETE' });
}

export function getAnalyses(runId: string): Promise<Analysis[]> {
  return request<Analysis[]>(`/runs/${runId}/analyses`);
}

export function getQAResults(runId: string): Promise<QAResult[]> {
  return request<QAResult[]>(`/runs/${runId}/qa/results`);
}

export function sendChatMessage(runId: string, message: string): Promise<ChatResponse> {
  return request<ChatResponse>(`/runs/${runId}/chat`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

export function getChatMessages(runId: string, signal?: AbortSignal): Promise<ChatMessage[]> {
  return request<ChatMessage[]>(`/runs/${runId}/chat`, { signal });
}

export function getRevisions(runId: string, signal?: AbortSignal): Promise<Revision[]> {
  return request<Revision[]>(`/runs/${runId}/revisions`, { signal });
}

export function getRevisionTimeline(revisionId: string): Promise<RevisionTrace[]> {
  return request<RevisionTrace[]>(`/revisions/${revisionId}/timeline`);
}

export function getObservability(runId: string): Promise<ObservabilityData> {
  return request<ObservabilityData>(`/runs/${runId}/observability`);
}

export type SecretStatus = {
  configured: boolean;
  masked: string;
};

export type APISettings = {
  llm: {
    provider: 'mock' | 'ark' | 'openai';
    effective_provider: 'mock' | 'ark' | 'openai';
    ark_api_key: SecretStatus;
    ark_endpoint_id: string;
    ark_model: string;
    ark_base_url: string;
    openai_api_key: SecretStatus;
    openai_model: string;
    openai_base_url: string;
    openai_temperature: number | null;
  };
  search: {
    provider: 'mock' | 'tavily' | 'bocha';
    effective_provider: 'mock' | 'tavily' | 'bocha';
    tavily_api_key: SecretStatus;
    bocha_api_key: SecretStatus;
    enable_mock_search_fallback: boolean;
  };
  env_path: string;
};

export type APISettingsInput = {
  llm: {
    provider: string;
    ark_api_key: string;
    ark_endpoint_id: string;
    ark_model: string;
    ark_base_url: string;
    openai_api_key: string;
    openai_model: string;
    openai_base_url: string;
    openai_temperature: number | null;
  };
  search: {
    provider: string;
    tavily_api_key: string;
    bocha_api_key: string;
    enable_mock_search_fallback: boolean;
  };
};

export function getAPISettings(): Promise<APISettings> {
  return request<APISettings>('/settings/api');
}

export function saveAPISettings(input: APISettingsInput): Promise<APISettings> {
  return request<APISettings>('/settings/api', {
    method: 'PUT',
    body: JSON.stringify(input),
  });
}
