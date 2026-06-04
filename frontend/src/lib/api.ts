import type { Analysis, CitationBundleCompetitor, CitationMapItem, Competitor, CustomCompetitorInput, Evidence, QAResult, Report, Run, Source, Trace } from './types';

const API_BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function createRun(userRequirement: string): Promise<Run> {
  return request<Run>('/runs', {
    method: 'POST',
    body: JSON.stringify({ user_requirement: userRequirement }),
  });
}

export function listRuns(): Promise<Run[]> {
  return request<Run[]>('/runs');
}

export function getRun(runId: string): Promise<Run> {
  return request<Run>(`/runs/${runId}`);
}

export function deleteRun(runId: string): Promise<void> {
  return request<void>(`/runs/${runId}`, { method: 'DELETE' });
}

export function regenerateReport(runId: string): Promise<Run> {
  return request<Run>(`/runs/${runId}/regenerate`, { method: 'POST' });
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

export function getReportCitations(runId: string): Promise<CitationMapItem[]> {
  return request<CitationMapItem[]>(`/runs/${runId}/report/citations`);
}

export function getReportCitationBundle(runId: string): Promise<CitationBundleCompetitor[]> {
  return request<CitationBundleCompetitor[]>(`/runs/${runId}/report/citation-bundle`);
}

export function getEvidence(runId: string): Promise<Evidence[]> {
  return request<Evidence[]>(`/runs/${runId}/evidence`);
}

export function getAnalyses(runId: string): Promise<Analysis[]> {
  return request<Analysis[]>(`/runs/${runId}/analyses`);
}

export function getQAResults(runId: string): Promise<QAResult[]> {
  return request<QAResult[]>(`/runs/${runId}/qa/results`);
}
