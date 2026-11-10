import { test } from "node:test";
import assert from "node:assert/strict";
import {
  canControl,
  canReviewReports,
  canRunAnalysis,
  canWriteReports,
  reviewStep,
} from "../src/components/auth/permissions.ts";

const user = (role, is_admin = false) => ({ role, is_admin });

test("직책별 권한은 백엔드 규칙과 같다", () => {
  const inspector = user("현장 점검자");
  const lead = user("보전 팀장");
  const control = user("관제 담당자");
  const site = user("현장 책임자");
  assert.deepEqual(
    [inspector, lead, control, site].map((u) => [
      canWriteReports(u),
      canReviewReports(u),
      canControl(u),
      canRunAnalysis(u),
    ]),
    [
      [true, false, false, true],
      [true, true, false, true],
      [false, true, true, true],
      [false, false, false, false],
    ],
  );
  assert.equal(reviewStep(lead, "SUBMITTED"), "review");
  assert.equal(reviewStep(lead, "REVIEWED"), null);
  assert.equal(reviewStep(control, "REVIEWED"), "approve");
  assert.equal(reviewStep(control, "SUBMITTED"), null);
  assert.equal(canWriteReports(null), false);
});

test("D-36: 계정 관리자는 직책과 관계없이 모든 권한을 가진다", () => {
  const admin = user("현장 책임자", true);
  assert.ok(canWriteReports(admin));
  assert.ok(canReviewReports(admin));
  assert.ok(canControl(admin));
  assert.ok(canRunAnalysis(admin));
  assert.equal(reviewStep(admin, "SUBMITTED"), "review");
  assert.equal(reviewStep(admin, "REVIEWED"), "approve");
  assert.equal(reviewStep(admin, "APPROVED"), null);
});
