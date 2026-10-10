import { spawnSync } from "node:child_process";
import path from "node:path";

export interface PythonExecutionResult {
  code: number;
  stdout: string;
  stderr: string;
  data?: any;
}

/**
 * Executes a specialist Python script using standard I/O and zero dependencies.
 */
export function runPythonSpecialist(
  scriptPath: string,
  args: string[] = [],
  inputPayload?: any,
  timeoutMs: number = 30000
): PythonExecutionResult {
  const cmdArgs = scriptPath.startsWith("-") ? [scriptPath, ...args] : [path.resolve(scriptPath), ...args];
  const inputStr = inputPayload !== undefined ? JSON.stringify(inputPayload) : undefined;

  const result = spawnSync("python3", cmdArgs, {
    input: inputStr,
    encoding: "utf8",
    timeout: timeoutMs,
  });

  let data: any = null;
  if (result.stdout) {
    try {
      data = JSON.parse(result.stdout.trim());
    } catch {
      // Plain text output
    }
  }

  return {
    code: result.status ?? (result.error ? 1 : 0),
    stdout: result.stdout || "",
    stderr: result.stderr || (result.error ? String(result.error) : ""),
    data,
  };
}
