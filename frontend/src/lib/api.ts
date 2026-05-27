import type { Analysis, CitationMapItem, Competitor, CustomCompetitorInput, Evidence, Report, Run, Source, Trace } from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api';

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

export function getReport(runId: string): Promise<Report> {
  return request<Report>(`/runs/${runId}/report`);
}

export function getReportCitations(runId: string): Promise<CitationMapItem[]> {
  return request<CitationMapItem[]>(`/runs/${runId}/report/citations`);
}

export function getEvidence(runId: string): Promise<Evidence[]> {
  return request<Evidence[]>(`/runs/${runId}/evidence`);
}

export function getAnalyses(runId: string): Promise<Analysis[]> {
  return request<Analysis[]>(`/runs/${runId}/analyses`);
}
