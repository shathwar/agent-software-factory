import fs from "node:fs";
import path from "node:path";

export function validateChangeId(value: string): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value) || value.includes("..")) {
    throw new Error("Change ID must be a simple identifier without path separators or traversal");
  }
  return value;
}

export function repositoryPath(repoRoot: string, relative: string): string {
  if (!relative || path.isAbsolute(relative) || relative.includes("\\") || relative.split("/").some(p => p === "" || p === "." || p === "..")) {
    throw new Error(`Unsafe repository-relative path: ${JSON.stringify(relative)}`);
  }
  const root = path.resolve(repoRoot);
  const target = path.resolve(root, relative);
  if (!target.startsWith(root + path.sep) && target !== root) {
    throw new Error(`Unsafe repository path traversal: ${relative}`);
  }
  return path.join(repoRoot, relative);
}

export function agentflowPath(repoRoot: string, relative: string = ""): string {
  const rel = relative ? path.join(".agentflow", relative) : ".agentflow";
  return repositoryPath(repoRoot, rel);
}

export function getStateFile(repoRoot: string): string {
  return agentflowPath(repoRoot, "state.json");
}

export function getLockFile(repoRoot: string): string {
  return agentflowPath(repoRoot, "state.lock");
}
