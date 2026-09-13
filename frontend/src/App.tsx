import { Route, Routes } from "react-router-dom";
import { DistrictsPage } from "./pages/DistrictsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { MapPage } from "./pages/MapPage";
import { NewsPage } from "./pages/NewsPage";
import { ComparePage } from "./pages/ComparePage";
import { NationPage } from "./pages/NationPage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";
import { PendingPage } from "./pages/PendingPage";
import { MePage } from "./pages/MePage";
import { CyclesPage } from "./pages/CyclesPage";
import { RosterPage } from "./pages/RosterPage";
import { CycleFormPage } from "./pages/CycleFormPage";
import { CycleEditPage } from "./pages/CycleEditPage";
import { OpsConsolePage } from "./pages/OpsConsolePage";
import { OpsCampPage } from "./pages/OpsCampPage";
import { OpsCycleEditPage } from "./pages/OpsCycleEditPage";
import { OpsAuditPage } from "./pages/OpsAuditPage";
import { OpsNewsPartiesPage } from "./pages/OpsNewsPartiesPage";

// 10단계 — 24개 화면 전부 React다. `/onboarding` 과 `/cycles/new` 는 같은
// `CycleFormPage` 를 쓴다 — 페이지 안에서 경로로 첫 설정/주기 추가를 가른다
// (같은 CycleForm 을 두 라우트가 공유하는 것과 같은 결). 운영자 대리 수정
// (`OpsCycleEditPage`)은 캠프 쪽 `CycleEditPage` 와 같은 컴포넌트
// (`CycleFormFields`)를 쓰지만 흐름이 달라(사유 필수, 저장 뒤 행선지가
// `/ops/camps/{id}`) 별도 페이지다.
export function App() {
  return (
    <Routes>
      <Route path="/" element={<DistrictsPage />} />
      <Route path="/d/:districtId/" element={<DashboardPage />} />
      <Route path="/d/:districtId/map" element={<MapPage />} />
      <Route path="/d/:districtId/news" element={<NewsPage />} />
      <Route path="/compare" element={<ComparePage />} />
      <Route path="/nation" element={<NationPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/pending" element={<PendingPage />} />
      <Route path="/me" element={<MePage />} />
      <Route path="/onboarding" element={<CycleFormPage />} />
      <Route path="/cycles" element={<CyclesPage />} />
      <Route path="/cycles/new" element={<CycleFormPage />} />
      <Route path="/cycles/:cycleId/edit" element={<CycleEditPage />} />
      <Route path="/cycles/:cycleId/roster" element={<RosterPage />} />
      <Route path="/ops/" element={<OpsConsolePage />} />
      <Route path="/ops/audit" element={<OpsAuditPage />} />
      <Route path="/ops/news-parties" element={<OpsNewsPartiesPage />} />
      <Route path="/ops/camps/:campId" element={<OpsCampPage />} />
      <Route path="/ops/camps/:campId/cycles/:cycleId/edit" element={<OpsCycleEditPage />} />
    </Routes>
  );
}
