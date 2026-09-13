import type {
  CompareApiResponse,
  CycleFormApiResponse,
  CycleFormValues,
  CyclePreviewApiResponse,
  CyclesApiResponse,
  DashboardResponse,
  DistrictsApiResponse,
  MapApiResponse,
  MeApiResponse,
  NationApiResponse,
  NewsApiResponse,
  OpsAuditApiResponse,
  OpsCampApiResponse,
  OpsConsoleApiResponse,
  OpsNewsPartiesApiResponse,
  NewsCollectJobsApiResponse,
  PendingApiResponse,
  RosterApiResponse,
} from "./types";

// 같은 오리진에서 서빙된다(SPA가 FastAPI 정적 서빙, API도 FastAPI) — CORS가 필요 없고
// 세션 쿠키가 그대로 통한다. 개발 중엔 vite.config.ts 의 프록시가 /api 를 FastAPI로 넘긴다.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) {
    throw new ApiError(res.status, `${path} 요청 실패 (${res.status})`);
  }
  return (await res.json()) as T;
}

export function fetchDistricts(): Promise<DistrictsApiResponse> {
  return getJson<DistrictsApiResponse>("/api/districts");
}

export function fetchDashboard(
  districtId: string,
  params: { sort?: string; electionType?: string } = {},
): Promise<DashboardResponse> {
  const qs = new URLSearchParams();
  if (params.sort) qs.set("sort", params.sort);
  if (params.electionType) qs.set("election_type", params.electionType);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJson<DashboardResponse>(`/api/d/${encodeURIComponent(districtId)}${suffix}`);
}

export function fetchMap(
  districtId: string,
  params: { metric?: string; electionType?: string } = {},
): Promise<MapApiResponse> {
  const qs = new URLSearchParams();
  if (params.metric) qs.set("metric", params.metric);
  if (params.electionType) qs.set("election_type", params.electionType);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJson<MapApiResponse>(`/api/d/${encodeURIComponent(districtId)}/map${suffix}`);
}

export function fetchNews(
  districtId: string,
  params: { sort?: string; scope?: string; q?: string } = {},
): Promise<NewsApiResponse> {
  const qs = new URLSearchParams();
  if (params.sort) qs.set("sort", params.sort);
  if (params.scope) qs.set("scope", params.scope);
  if (params.q) qs.set("q", params.q);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJson<NewsApiResponse>(`/api/d/${encodeURIComponent(districtId)}/news${suffix}`);
}

export function fetchCompare(
  params: { sort?: string; electionType?: string } = {},
): Promise<CompareApiResponse> {
  const qs = new URLSearchParams();
  if (params.sort) qs.set("sort", params.sort);
  if (params.electionType) qs.set("election_type", params.electionType);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJson<CompareApiResponse>(`/api/compare${suffix}`);
}

export function fetchNation(
  params: { sort?: string; electionType?: string } = {},
): Promise<NationApiResponse> {
  const qs = new URLSearchParams();
  if (params.sort) qs.set("sort", params.sort);
  if (params.electionType) qs.set("election_type", params.electionType);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJson<NationApiResponse>(`/api/nation${suffix}`);
}

async function methodJson(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body: unknown = {},
): Promise<{ ok: true; message?: string } | { error: string }> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json()) as { ok?: true; message?: string; error?: string };
  if (!res.ok) return { error: data.error ?? `요청 실패 (${res.status})` };
  return { ok: true, message: data.message };
}

async function postJson(
  path: string,
  body: unknown,
): Promise<{ ok: true; message?: string } | { error: string }> {
  return methodJson("POST", path, body);
}

export function login(email: string, password: string) {
  return postJson("/api/login", { email, password });
}

export function signup(fields: {
  email: string;
  password: string;
  candidate_name: string;
  contact: string;
  wanted_election?: string;
}) {
  return postJson("/api/signup", fields);
}

export async function logout(): Promise<void> {
  await fetch("/logout", { method: "POST", credentials: "same-origin" });
}

export function fetchPending(): Promise<PendingApiResponse> {
  return getJson<PendingApiResponse>("/api/pending");
}

export function fetchMe(): Promise<MeApiResponse> {
  return getJson<MeApiResponse>("/api/me");
}

export function changePassword(current: string, newPassword: string, confirm: string) {
  return postJson("/api/me", { current, new: newPassword, confirm });
}

export function fetchCycles(): Promise<CyclesApiResponse> {
  return getJson<CyclesApiResponse>("/api/cycles");
}

export function fetchRoster(cycleId: string): Promise<RosterApiResponse> {
  return getJson<RosterApiResponse>(`/api/cycles/${encodeURIComponent(cycleId)}/roster`);
}

export function fetchOnboardingForm(): Promise<CycleFormApiResponse> {
  return getJson<CycleFormApiResponse>("/api/onboarding");
}

export function fetchNewCycleForm(): Promise<CycleFormApiResponse> {
  return getJson<CycleFormApiResponse>("/api/cycles/new");
}

export function saveOnboarding(fields: CycleFormValues) {
  return postJson("/api/onboarding", fields);
}

export function saveNewCycle(fields: CycleFormValues) {
  return postJson("/api/cycles/new", fields);
}

export function fetchEditCycleForm(cycleId: string): Promise<CycleFormApiResponse> {
  return getJson<CycleFormApiResponse>(`/api/cycles/${encodeURIComponent(cycleId)}/edit`);
}

export async function previewCycle(
  cycleId: string,
  fields: CycleFormValues,
): Promise<CyclePreviewApiResponse> {
  const res = await fetch(`/api/cycles/${encodeURIComponent(cycleId)}/edit`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  return (await res.json()) as CyclePreviewApiResponse;
}

export function applyCycle(cycleId: string, fields: CycleFormValues) {
  return postJson(`/api/cycles/${encodeURIComponent(cycleId)}/apply`, fields);
}

export function saveRoster(
  cycleId: string,
  fields: {
    ours_name: string;
    ours_party: string;
    ours_lineage: string;
    ours_incumbent: boolean;
    opponents: string;
  },
) {
  return postJson(`/api/cycles/${encodeURIComponent(cycleId)}/roster`, fields);
}

// --- 운영자 콘솔 --------------------------------------------------------------------

export function fetchOpsConsole(): Promise<OpsConsoleApiResponse> {
  return getJson<OpsConsoleApiResponse>("/api/ops/console");
}

export function approveSignup(requestId: number, campId: string, note: string) {
  return postJson(`/api/ops/signups/${requestId}/approve`, { camp_id: campId, note });
}

export function rejectSignup(requestId: number, note: string) {
  return postJson(`/api/ops/signups/${requestId}/reject`, { note });
}

export function setAccountStatus(accountId: number, status: "active" | "suspended") {
  return postJson(`/api/ops/accounts/${accountId}/status`, { status });
}

export function forceLogout(accountId: number) {
  return postJson(`/api/ops/accounts/${accountId}/logout`, {});
}

export function setAccountPassword(accountId: number, password: string) {
  return postJson(`/api/ops/accounts/${accountId}/passwd`, { password });
}

export async function fetchOpsCamp(campId: string): Promise<OpsCampApiResponse> {
  const res = await fetch(`/api/ops/camps/${encodeURIComponent(campId)}`, {
    credentials: "same-origin",
  });
  return (await res.json()) as OpsCampApiResponse;
}

export function fetchOpsAudit(params: { camp?: string; limit?: number } = {}): Promise<OpsAuditApiResponse> {
  const qs = new URLSearchParams();
  if (params.camp) qs.set("camp", params.camp);
  if (params.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return getJson<OpsAuditApiResponse>(`/api/ops/audit${suffix}`);
}

export function fetchOpsNewsParties(): Promise<OpsNewsPartiesApiResponse> {
  return getJson<OpsNewsPartiesApiResponse>("/api/ops/news-parties");
}

export function addNewsParty(name: string) {
  return postJson("/api/ops/news-parties", { name });
}

export function renameNewsParty(partyId: string, name: string) {
  return methodJson("PATCH", `/api/ops/news-parties/${encodeURIComponent(partyId)}`, { name });
}

export function deleteNewsParty(partyId: string) {
  return methodJson("DELETE", `/api/ops/news-parties/${encodeURIComponent(partyId)}`);
}

export function fetchNewsCollectJobs(): Promise<NewsCollectJobsApiResponse> {
  return getJson<NewsCollectJobsApiResponse>("/api/ops/news-parties/jobs");
}

export function collectAllNews() {
  return postJson("/api/ops/news-parties/collect", {});
}

export function collectDistrictNews(districtId: string) {
  return postJson(`/api/ops/news-parties/collect/${encodeURIComponent(districtId)}`, {});
}

export function collectDistrictCandidatesNews(districtId: string) {
  return postJson(
    `/api/ops/news-parties/collect/${encodeURIComponent(districtId)}/candidates`,
    {},
  );
}

export function fetchOpsEditCycleForm(campId: string, cycleId: string): Promise<CycleFormApiResponse> {
  return getJson<CycleFormApiResponse>(
    `/api/ops/camps/${encodeURIComponent(campId)}/cycles/${encodeURIComponent(cycleId)}/edit`,
  );
}

export async function opsPreviewCycle(
  campId: string,
  cycleId: string,
  fields: CycleFormValues,
): Promise<CyclePreviewApiResponse> {
  const res = await fetch(
    `/api/ops/camps/${encodeURIComponent(campId)}/cycles/${encodeURIComponent(cycleId)}/edit`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    },
  );
  return (await res.json()) as CyclePreviewApiResponse;
}

export function opsApplyCycle(
  campId: string,
  cycleId: string,
  fields: CycleFormValues & { note: string },
) {
  return postJson(
    `/api/ops/camps/${encodeURIComponent(campId)}/cycles/${encodeURIComponent(cycleId)}/apply`,
    fields,
  );
}
