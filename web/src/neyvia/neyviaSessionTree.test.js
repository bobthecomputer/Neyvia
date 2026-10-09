import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSessionForest,
  flattenSessionForest,
  sessionParentId,
} from "./neyviaSessionTree.js";

test("imported cycles, duplicate rows and orphans remain visible exactly once", () => {
  const rows = [
    {conversationId: "a", parentConversationId: "b"},
    {conversationId: "b", parentConversationId: "a"},
    {conversationId: "c", parentConversationId: "b"},
    {conversationId: "orphan", parentConversationId: "missing"},
    {conversationId: "orphan", parentConversationId: "missing", title: "Latest"},
  ];
  const flat = flattenSessionForest(buildSessionForest(rows));
  assert.deepEqual(flat.map(item => item.row.conversationId).sort(), ["a", "b", "c", "orphan"]);
  assert.equal(flat.find(item => item.row.conversationId === "orphan").row.title, "Latest");
});

test("session forest preserves durable parent/child lineage", () => {
  const rows = [
    { conversationId: "parent", title: "Parent", updatedAt: "2026-08-27T10:00:00Z" },
    {
      conversationId: "child",
      parentConversationId: "parent",
      title: "Child",
      updatedAt: "2026-08-27T11:00:00Z",
    },
    {
      conversationId: "grandchild",
      metadata: { parentConversationId: "child", branchKind: "spawn" },
      title: "Grandchild",
      updatedAt: "2026-08-27T12:00:00Z",
    },
  ];
  const forest = buildSessionForest(rows);
  assert.equal(forest.roots.length, 1);
  assert.equal(forest.roots[0].row.conversationId, "parent");
  assert.equal(forest.roots[0].children[0].row.conversationId, "child");
  assert.equal(forest.roots[0].children[0].children[0].row.conversationId, "grandchild");
  assert.deepEqual(
    flattenSessionForest(forest).map(item => [item.row.conversationId, item.depth]),
    [["parent", 0], ["child", 1], ["grandchild", 2]],
  );
});

test("metadata lineage remains readable during migration", () => {
  assert.equal(
    sessionParentId({ metadata: { inheritsContextFrom: "legacy-parent" } }),
    "legacy-parent",
  );
});
