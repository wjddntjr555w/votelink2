// votelink/web/viewmodel.py 의 Pydantic 모델을 그대로 반영한다(.model_dump(mode="json")).
// 필드명은 전부 snake_case 그대로 — 계층 사이에 새 이름을 만들지 않는다.

export interface Verdict {
  status: "cleared" | "unreviewed" | "blocked";
  reasons: string[];
  notes: string[];
  reviewed_by: string;
  reviewed_at: string;
  // `shows_content` 은 백엔드 Verdict 의 @property 라 JSON에 없다 — 프런트에서
  // status !== "blocked" 로 같은 규칙을 다시 계산한다 (ComplianceGate.tsx).
}

export interface GapCell {
  value: number | null;
  text: string;
  known: boolean;
  css_class: string;
  title: string;
}

export interface Sparkline {
  labels: string[];
  values: (number | null)[];
  y_min: number;
  y_max: number;
  breaks: number;
}

export interface BarSlice {
  camp: "conservative" | "progressive" | "centrist" | "other";
  label: string;
  pct: number;
  offset: number;
  css_class: string;
  ours: boolean;
}

export interface AgeBar {
  band: string;
  pct: number;
  height_pct: number;
}

export interface LensRead {
  ours: number;
  theirs: number;
  lead: number;
  in_territory: boolean;
  ahead: boolean;
  lead_text: string;
}

export interface Lens {
  camp_id: string;
  cycle_id: string;
  candidate_name: string;
  lineage: string;
  party: string | null;
  label: string;
}

export interface GapSummary {
  mean: number | null;
  known: number;
  total: number;
  text: string;
}

export interface EmdCard {
  geo_code: string;
  geo_name: string;
  latest_election_id: string;
  latest_election_date: string;
  election_count: number;
  camp_bar: BarSlice[];
  turnout: number;
  swing: number;
  trend: "conservative_shift" | "stable" | "progressive_shift";
  trend_label: string;
  gaps: Record<string, GapCell>;
  gap_coverage: Record<string, GapSummary>;
  gap_summary: GapSummary;
  gap_summary_label: string;
  recent_change: GapCell;
  conservative_spark: Sparkline;
  gap_spark: Sparkline;
  age_bars: AgeBar[];
  sex_ratio: number;
  sex_ratio_text: string;
  population_total: number;
  confidence: number;
  missing_gaps: number;
  evidence_count: number;
  evidence_ids: string[];
  verdict: Verdict;
  lens_read: LensRead | null;
}

export interface AggregateCard {
  label: string;
  member_count: number;
  camp_bar: BarSlice[];
  lens_read: LensRead | null;
  turnout: number;
  turnout_known: number;
  turnout_total: number;
  swing: number;
  trend_mix: Record<string, number>;
  // trend_mix_text 는 백엔드 @property 라 JSON에 없다 — 프런트에서 TREND_LABELS 로 다시 조립한다
  // (components/nation/NationSummaryCard.tsx).
  age_bars: AgeBar[];
  sex_ratio: number;
  sex_ratio_text: string;
  population_total: number;
  gaps: Record<string, { mean: number | null; known: number; total: number; text: string }>;
  recent_change: GapCell;
  conservative_spark: Sparkline;
  progressive_spark: Sparkline;
  centrist_spark: Sparkline;
  turnout_spark: Sparkline;
  gap_spark: Sparkline;
  camp_recent_change: Record<string, GapCell>;
  approx: boolean;
  approx_reason: string;
  verdict: Verdict | null;
}

export interface Situation {
  leading_label: string;
  leading_lead_text: string;
  leading_css_class: string;
  leading_pct_text: string;
  turnout_text: string;
  recent_change: GapCell;
  avg_confidence_text: string;
  watch_count: number;
}

export interface Insight {
  tone: "warn" | "note";
  icon: string;
  title: string;
  detail: string;
}

export interface RegionStatus {
  label: string;
  css_class: string;
}

export interface LoadDiagnostics {
  read: number;
  loaded: number;
  expected: number;
  outside_district: number;
  other_election_type: number;
  superseded: number;
  rejected: number;
  missing_codes: string[];
  is_complete: boolean;
}

export interface DistrictView {
  district_name: string;
  cards: EmdCard[];
  diagnostics: LoadDiagnostics;
  sort: string;
  sorts: Record<string, string>;
  gap_labels: Record<string, string>;
  trend_note: string;
  election_type: string;
  election_type_label: string;
  election_types: [string, string][];
  summary_card: AggregateCard | null;
  situation: Situation | null;
  watchlist: EmdCard[];
  region_status: Record<string, RegionStatus>;
  region_category: Record<string, string>;
  insights: Insight[];
  avg_confidence: number;
  lens: Lens | null;
  last_updated: string;
  population_total: number;
  population_months: string[];
  as_of_months: string[];
  latest_election_id: string;
  latest_election_date: string;
  source_names: string[];
  source_licenses: string[];
  missing_gaps: number;
  verdict: Verdict | null;
  is_empty: boolean;
  coverage_text: string;
  population_month_text: string;
}

export interface PulseBar {
  week_start: string;
  count: number;
  district_specific: number;
  height_pct: number;
  spike: boolean;
  title: string;
}

export interface PulseCard {
  as_of: string;
  window_weeks: number;
  total_articles: number;
  bars: PulseBar[];
  latest_count: number;
  latest_district_specific: number;
  latest_spike: boolean;
  latest_z_text: string;
  latest_week: string;
  spike_weeks: number;
  backfill_distorted: boolean;
  top_publishers: [string, number][];
  top_places: [string, number][];
  top_persons: [string, number][];
  verdict: Verdict | null;
}

export interface IssueBar {
  category: string;
  label: string;
  article_count: number;
  share: number;
  recency_score: number;
  trend: "rising" | "flat" | "falling";
  trend_label: string;
  width_pct: number;
  headlines: string[];
  places: [string, number][];
  title: string;
}

export interface IssueBoardCard {
  as_of: string;
  window_weeks: number;
  total_articles: number;
  unclassified_count: number;
  unclassified_pct: number;
  lexicon_version: string;
  backfill_distorted: boolean;
  bars: IssueBar[];
  verdict: Verdict | null;
}

export interface CandidateComparison {
  ours_name: string;
  ours_party: string | null;
  theirs_name: string;
  support_ours: number;
  support_theirs: number;
  recent_change_ours: GapCell;
  recent_change_theirs: GapCell;
  strong_regions_ours: number;
  strong_regions_theirs: number;
}

export interface DashboardResponse {
  view: DistrictView;
  pulse: PulseCard | null;
  issue_board: IssueBoardCard | null;
  candidate_comparison: CandidateComparison | null;
  district_id: string;
  districts: [string, string][];
  election_types: [string, string][];
  auth_on: boolean;
  account: { email: string; is_operator: boolean } | null;
}

export interface Metric {
  key: string;
  label: string;
  scale: "divergent" | "sequential";
  unit: string;
  signed: boolean;
}

export interface MapCell {
  geo_code: string;
  geo_name: string;
  svg_path: string;
  label_x: number;
  label_y: number;
  value: number | null;
  text: string;
  fill: string;
  css_class: string;
  title: string;
}

export interface MapLegendStop {
  label: string;
  fill: string;
}

export interface MapViewData {
  metric: Metric;
  metrics: Record<string, Metric>;
  cells: MapCell[];
  view_box: string;
  is_real_boundary: boolean;
  v_min: number | null;
  v_max: number | null;
  known: number;
  total: number;
  legend: MapLegendStop[];
  verdict: Verdict | null;
}

export interface MapApiResponse {
  view: DistrictView;
  map: MapViewData;
  district_id: string;
  districts: [string, string][];
  election_types: [string, string][];
  auth_on: boolean;
  account: { email: string; is_operator: boolean } | null;
}

export interface NewsDiagnostics {
  read: number;
  outside_district: number;
  rejected: number;
  duplicate: number;
  shown: number;
}

export interface NewsRow {
  title: string;
  publisher: string;
  published_at: string;
  date_label: string;
  url: string;
  summary: string;
  places: string[];
  persons: string[];
  confidence: number;
  is_district_specific: boolean;
}

export interface NewsView {
  district_name: string;
  rows: NewsRow[];
  diagnostics: NewsDiagnostics;
  sort: string;
  sorts: Record<string, string>;
  scope: string;
  scopes: Record<string, string>;
  query: string;
  matched: number;
  limit: number;
  district_specific_count: number;
  sigungu_only_count: number;
  top_publishers: [string, number][];
  top_places: [string, number][];
  top_persons: [string, number][];
  date_from: string;
  date_to: string;
  verdict: Verdict | null;
  // is_empty/nothing_collected/truncated/shown_text/coverage_text/date_range_text 는
  // 백엔드 @property 라 JSON에 없다 — 프런트에서 같은 규칙으로 다시 계산한다
  // (pages/NewsPage.tsx).
}

export interface NewsApiResponse {
  view: NewsView;
  lens: Lens | null;
  district_id: string;
  districts: [string, string][];
  election_types: [string, string][];
  auth_on: boolean;
  account: { email: string; is_operator: boolean } | null;
}

export interface ComparisonRow {
  district_id: string;
  district_name: string;
  agg: AggregateCard;
  loaded: number;
  expected: number;
  // coverage_text 는 백엔드 @property 라 JSON에 없다 — `${loaded} / ${expected}` 로 다시 계산한다.
}

export interface SkippedDistrict {
  district_id: string;
  district_name: string;
  reason: string;
  fix: string;
}

export interface ComparisonView {
  rows: ComparisonRow[];
  skipped: SkippedDistrict[];
  sort: string;
  sorts: Record<string, string>;
  gap_labels: Record<string, string>;
  election_type: string;
  election_type_label: string;
  election_types: [string, string][];
  verdict: Verdict | null;
  // is_empty 는 백엔드 @property 라 JSON에 없다 — `rows.length === 0` 으로 다시 계산한다.
}

export interface CompareApiResponse {
  view: ComparisonView;
  lens: Lens | null;
  district_id: null;
  districts: [string, string][];
  election_types: [string, string][];
  auth_on: boolean;
  account: { email: string; is_operator: boolean } | null;
}

export interface NationView {
  cards: EmdCard[];
  summary_card: AggregateCard | null;
  diagnostics: LoadDiagnostics;
  sort: string;
  sorts: Record<string, string>;
  gap_labels: Record<string, string>;
  trend_note: string;
  election_type: string;
  election_type_label: string;
  election_types: [string, string][];
  population_total: number;
  as_of_months: string[];
  latest_election_id: string;
  latest_election_date: string;
  source_names: string[];
  source_licenses: string[];
  verdict: Verdict | null;
  // is_empty/shown_text 는 백엔드 @property 라 JSON에 없다 — 프런트에서 다시 계산한다
  // (pages/NationPage.tsx).
}

export interface NationApiResponse {
  view: NationView;
  lens: Lens | null;
  district_id: null;
  districts: [string, string][];
  election_types: [string, string][];
  auth_on: boolean;
  account: { email: string; is_operator: boolean } | null;
}

export interface DistrictsApiResponse {
  districts: [string, string][];
  lens: Lens | null;
  auth_on: boolean;
  account: { email: string; is_operator: boolean } | null;
}

export interface SignupRequestInfo {
  candidate_name: string;
  contact: string;
  wanted_election: string | null;
  requested_at: string;
}

export interface PendingApiResponse {
  request: SignupRequestInfo | null;
  auth_on: boolean;
  account: { email: string; is_operator: boolean } | null;
}

export interface MeAccount {
  email: string;
  is_operator: boolean;
  camp_id: string | null;
  created_at: string;
  last_login_at: string | null;
}

export interface MeApiResponse {
  account: MeAccount;
  sessions: number;
  bootstrap: boolean;
  auth_on: boolean;
}

export interface Election {
  type: string;
  office: string;
  date: string | null;
}

export interface Territory {
  preset: string | null;
  emd_codes: string[];
}

export interface Cycle {
  election: Election;
  lineage: string;
  territory: Territory;
  legal_reviewer: string | null;
}

export interface Candidate {
  name: string;
  party: string;
  lineage: string;
  incumbent: boolean;
  note: string | null;
}

export interface Roster {
  ours: Candidate;
  opponents: Candidate[];
}

export interface CycleRow {
  id: string;
  error: string | null;
  cycle: Cycle | null;
  roster: Roster | null;
  current: boolean;
}

export interface CyclesApiResponse {
  rows: CycleRow[];
  today: string;
  lens: Lens | null;
  districts: [string, string][];
  auth_on: boolean;
  account: { email: string; is_operator: boolean };
}

export interface RosterForm {
  ours_name: string;
  ours_party: string;
  ours_lineage: string;
  ours_incumbent: boolean;
  opponents: string;
}

export interface RosterApiResponse {
  cycle_id: string;
  form: RosterForm;
  lineage_options: [string, string][];
}

export interface CycleFormOptions {
  presets: [string, string][];
  sigungus: string[];
  emd_groups: [string, [string, string][]][];
  type_options: [string, string][];
  office_options: [string, string][];
  lineage_options: [string, string][];
}

export interface CycleFormValues {
  election_type: string;
  office: string;
  election_date: string;
  lineage: string;
  party: string;
  incumbent: string;
  preset: string;
  sigungu: string;
  emd_pick: string[];
  emd_codes: string;
  legal_reviewer: string;
}

export interface CycleFormApiResponse extends CycleFormOptions {
  form: Partial<CycleFormValues>;
  first: boolean;
  cycle_id?: string;
}

export interface EmdDiffItem {
  code: string;
  name: string;
  label: string;
}

export interface CycleChange {
  cycle_id_before: string;
  cycle_id_after: string;
  date_before: string | null;
  date_after: string | null;
  type_before: string | null;
  type_after: string | null;
  office_before: string | null;
  office_after: string | null;
  lineage_before: string | null;
  lineage_after: string | null;
  reviewer_before: string | null;
  reviewer_after: string | null;
  added: EmdDiffItem[];
  removed: EmdDiffItem[];
  kept: number;
  opened: [string, string][];
  closed: [string, string][];
  moved: boolean;
  lineage_flipped: boolean;
  territory_changed: boolean;
  is_empty: boolean;
}

export interface CyclePreviewApiResponse {
  change?: CycleChange;
  error?: string;
}

export interface OpsAccount {
  id: number;
  email: string;
  is_operator: boolean;
  camp_id: string | null;
  status: "active" | "pending" | "suspended";
  created_at: string;
  last_login_at: string | null;
}

export interface SignupQueueItem {
  id: number;
  candidate_name: string;
  email: string;
  contact: string;
  wanted_election: string | null;
  requested_at: string;
  suggested: string;
  taken: boolean;
}

export interface OpsAccountRow {
  account: OpsAccount;
  sessions: number;
  onboarded: boolean;
}

export interface OpsConsoleApiResponse {
  queue: SignupQueueItem[];
  rows: OpsAccountRow[];
  bootstrap: boolean;
  auth_on: boolean;
  account: { email: string; is_operator: boolean };
}

export interface OpsCampCycle {
  id: string;
  error: string | null;
  cycle: Cycle | null;
  roster: Roster | null;
}

export interface AuditEntry {
  id: number;
  at: string;
  account_id: number | null;
  camp_id: string | null;
  action: string;
  target: string | null;
  detail: Record<string, unknown>;
  ip: string | null;
}

export interface OpsCampApiResponse {
  camp_id: string;
  error: string | null;
  info: { camp_id: string; candidate_name: string; created_at: string } | null;
  cycles: OpsCampCycle[];
  account: OpsAccount | null;
  entries: AuditEntry[];
  auth_on: boolean;
  operator: { email: string; is_operator: boolean };
}

export interface OpsAuditApiResponse {
  entries: AuditEntry[];
  camps: string[];
  camp: string;
  limit: number;
  auth_on: boolean;
  operator: { email: string; is_operator: boolean };
}
