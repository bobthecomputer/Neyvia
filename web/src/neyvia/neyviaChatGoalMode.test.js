import test from "node:test";
import assert from "node:assert/strict";
import { nativeGoalModeSupported, normalizeChatGoalMode, preserveLocalChatGoalMode, goalModeRequestFields } from "./neyviaChatGoalMode.js";

test("resume preserves durable goal when local preference is absent and honors explicit off", () => {
  const saved = {goalMode: true};
  assert.equal({...saved, ...goalModeRequestFields("neyvia-agent", {goalMode:false, goalModePreferenceSet:false})}.goalMode, true);
  assert.equal({...saved, ...goalModeRequestFields("neyvia-agent", {goalMode:false, goalModePreferenceSet:true})}.goalMode, false);
  assert.deepEqual(goalModeRequestFields("codex", {goalMode:true, goalModePreferenceSet:true}), {});
  assert.deepEqual(goalModeRequestFields("neyvia-agent", null, true, false), {goalMode:true});
});

test("existing chats without a goal-mode value remain off", () => {
  assert.deepEqual(normalizeChatGoalMode({}), {goalMode: false, goalModePreferenceSet: false});
  assert.deepEqual(normalizeChatGoalMode({metadata: {}}), {goalMode: false, goalModePreferenceSet: false});
});

test("per-chat selections survive remote hydration and metadata restores durable values", () => {
  const selected = {goalMode: true, goalModePreferenceSet: true};
  assert.deepEqual(normalizeChatGoalMode(preserveLocalChatGoalMode({conversationId: "c1"}, selected)), selected);
  assert.deepEqual(normalizeChatGoalMode({metadata: {goalMode: true}}), {goalMode: true, goalModePreferenceSet: true});
  assert.deepEqual(normalizeChatGoalMode({metadata: {goalMode: false}}), {goalMode: false, goalModePreferenceSet: true});
  assert.deepEqual(
    normalizeChatGoalMode(preserveLocalChatGoalMode({metadata: {goalMode: false}}, selected)),
    {goalMode: false, goalModePreferenceSet: true},
  );
});

test("goal continuation UI is native Neyvia only", () => {
  assert.equal(nativeGoalModeSupported("neyvia-agent"), true);
  assert.equal(nativeGoalModeSupported("own"), true);
  assert.equal(nativeGoalModeSupported("claude-code"), false);
  assert.equal(nativeGoalModeSupported("hermes"), false);
});
