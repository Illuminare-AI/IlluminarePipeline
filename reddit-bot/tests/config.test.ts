import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseAppConfig } from "@devvit/shared-types/schemas/config-file.v1.js";

test("Devvit config passes SDK schema and keeps live external calls disabled", () => {
  const config = parseAppConfig(readFileSync("devvit.json", "utf8"), false);
  assert.equal(config.permissions.http.enable, false);
  assert.equal(config.triggers?.onCommentCreate, "/internal/comment-created");
  assert.equal(config.settings?.global?.CONTEXT_API_KEY.type, "string");
});
