import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_NEYVIA_SHELL_PREFERENCES,
  applyNeyviaAdaptiveExperience,
} from "./neyviaShellPreferences.js";
import { domainExperienceById } from "./neyviaDomainExperiences.js";

const CASES = Object.freeze({
  student: ["researcher", "auto"],
  writing: ["minimal", "writing"],
  research: ["researcher", "research"],
  creative: ["creator", "creative"],
  software: ["engineer", "implementation"],
  social: ["minimal", "auto"],
  casual: ["minimal", "auto"],
  maker: ["engineer", "auto"],
  niche: ["engineer", "auto"],
});

test("domain experiences adapt existing shell and task-profile contracts", () => {
  for (const [domainId, [uiPreset, systemPromptProfile]] of Object.entries(CASES)) {
    const experience = domainExperienceById(domainId);
    assert.equal(experience.adaptive.uiPreset, uiPreset, domainId);
    assert.equal(experience.adaptive.systemPromptProfile, systemPromptProfile, domainId);
    const next = applyNeyviaAdaptiveExperience(DEFAULT_NEYVIA_SHELL_PREFERENCES, experience.adaptive);
    assert.equal(next.uiPreset, uiPreset, domainId);
    assert.equal(next.systemPromptProfile, systemPromptProfile, domainId);
  }
});

test("adaptive UI keeps the existing preset semantics instead of inventing a fourth shell", () => {
  const research = applyNeyviaAdaptiveExperience(
    DEFAULT_NEYVIA_SHELL_PREFERENCES,
    domainExperienceById("research").adaptive,
  );
  assert.deepEqual(research.toolbar, ["attach", "pdf", "search", "data", "citations"]);
  assert.equal(research.detailLevel, "expanded");

  const software = applyNeyviaAdaptiveExperience(
    DEFAULT_NEYVIA_SHELL_PREFERENCES,
    domainExperienceById("software").adaptive,
  );
  assert.deepEqual(software.toolbar, ["attach", "terminal", "search", "diff", "canvas"]);
  assert.equal(software.compactMode, true);
});

test("unknown adaptive metadata preserves current preferences", () => {
  const current = applyNeyviaAdaptiveExperience(DEFAULT_NEYVIA_SHELL_PREFERENCES, {
    uiPreset: "creator",
    systemPromptProfile: "creative",
  });
  const next = applyNeyviaAdaptiveExperience(current, {
    uiPreset: "future-preset",
    systemPromptProfile: "future-profile",
  });
  assert.equal(next.uiPreset, "creator");
  assert.equal(next.systemPromptProfile, "creative");
  assert.deepEqual(next.toolbar, current.toolbar);
});
