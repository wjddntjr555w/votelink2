import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ComplianceGate } from "./ComplianceGate";
import type { Verdict } from "../../api/types";

const SECRET = "절대나가면안되는수치 12345";

function verdict(overrides: Partial<Verdict>): Verdict {
  return {
    status: "unreviewed",
    reasons: [],
    notes: [],
    reviewed_by: "",
    reviewed_at: "",
    ...overrides,
  };
}

describe("ComplianceGate — 절대 규칙 5", () => {
  it("blocked 면 children 을 그리지 않는다", () => {
    render(
      <ComplianceGate verdict={verdict({ status: "blocked", reasons: ["선거일 전 6일 공표 금지"] })}>
        <span>{SECRET}</span>
      </ComplianceGate>,
    );
    expect(screen.getByText("표시가 차단된 산출물이다")).toBeInTheDocument();
    expect(screen.getByText("선거일 전 6일 공표 금지")).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("판정이 없으면(null) blocked 와 똑같이 다룬다 — 모름은 안전이 아니다", () => {
    render(
      <ComplianceGate verdict={null}>
        <span>{SECRET}</span>
      </ComplianceGate>,
    );
    expect(screen.getByText("검증 판정이 없어 표시하지 않는다")).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("undefined 도 null 과 같게 다룬다", () => {
    render(
      <ComplianceGate verdict={undefined}>
        <span>{SECRET}</span>
      </ComplianceGate>,
    );
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });

  it("unreviewed 면 경고 배너가 콘텐츠와 함께 뜬다 (배너가 위)", () => {
    render(
      <ComplianceGate verdict={verdict({ status: "unreviewed", reasons: ["정책표에 없다"] })}>
        <span data-testid="content">{SECRET}</span>
      </ComplianceGate>,
    );
    const gate = screen.getByTestId("compliance-gate");
    const banner = screen.getByText("선거법 검토를 받지 않은 산출물이다");
    const content = screen.getByTestId("content");
    expect(gate).toContainElement(banner);
    expect(gate).toContainElement(content);
    // 배너가 콘텐츠보다 DOM 순서상 먼저 온다.
    expect(
      banner.compareDocumentPosition(content) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText(SECRET)).toBeInTheDocument();
  });

  it("cleared 면 조용한 배지 + 검토자·검토일만, 경고 없음", () => {
    render(
      <ComplianceGate
        verdict={verdict({ status: "cleared", reviewed_by: "법률검토자", reviewed_at: "2026-09-10" })}
      >
        <span>{SECRET}</span>
      </ComplianceGate>,
    );
    expect(screen.getByText(/검토 완료/)).toBeInTheDocument();
    expect(screen.getByText(/법률검토자/)).toBeInTheDocument();
    expect(screen.getByText(/2026-09-10/)).toBeInTheDocument();
    expect(screen.queryByText("선거법 검토를 받지 않은 산출물이다")).not.toBeInTheDocument();
    expect(screen.getByText(SECRET)).toBeInTheDocument();
  });

  it("notes 는 상태와 무관하게 항상 보인다 — cleared 라도", () => {
    render(
      <ComplianceGate verdict={verdict({ status: "cleared", notes: ["신뢰도 0.7"] })}>
        <span>{SECRET}</span>
      </ComplianceGate>,
    );
    expect(screen.getByText("신뢰도 0.7")).toBeInTheDocument();
  });

  it("notes 는 blocked 여도 보인다(콘텐츠만 숨는다)", () => {
    render(
      <ComplianceGate verdict={verdict({ status: "blocked", notes: ["근거 없음"] })}>
        <span>{SECRET}</span>
      </ComplianceGate>,
    );
    expect(screen.getByText("근거 없음")).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
  });
});
