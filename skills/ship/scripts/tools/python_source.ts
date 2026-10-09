/** Lexical Python source view for comment and indentation-based audit rules.
 * Strings (including multiline and prefixed literals) retain offsets but cannot
 * masquerade as comments, definitions, assertions, or forwarding statements.
 */
export interface PythonComment { text: string; line: number }
export interface PythonBlock { name: string; line: number; indent: number; body: string; header: string }
export function pythonSource(source: string): { code: string; comments: PythonComment[] } {
  const out = source.split("");
  const comments: PythonComment[] = [];
  let line = 1;
  for (let i = 0; i < source.length;) {
    if (source[i] === "\n") { line++; i++; continue; }
    if (source[i] === "#") {
      const start = i, at = line;
      while (i < source.length && source[i] !== "\n") out[i++] = " ";
      comments.push({text: source.slice(start, i), line: at}); continue;
    }
    if (source[i] === '"' || source[i] === "'") {
      const quote = source[i], triple = source.slice(i, i + 3) === quote.repeat(3);
      const delimiter = triple ? quote.repeat(3) : quote;
      for (let j = 0; j < delimiter.length; j++) out[i++] = " ";
      while (i < source.length) {
        if (source.slice(i, i + delimiter.length) === delimiter) {
          for (let j = 0; j < delimiter.length; j++) out[i++] = " ";
          break;
        }
        if (source[i] === "\\") {
          out[i++] = " ";
          if (i < source.length) { if (source[i] === "\n") line++; else out[i] = " "; i++; }
        } else { if (source[i] === "\n") line++; else out[i] = " "; i++; }
      }
      continue;
    }
    i++;
  }
  return { code: out.join(""), comments };
}
export function pythonBlocks(code: string, kind: "def" | "class"): PythonBlock[] {
  const lines = code.split(/\r?\n/), blocks: PythonBlock[] = [];
  const pattern = new RegExp(`^(\\s*)(?:async\\s+)?${kind}\\s+(\\w+)\\b`);
  for (let i = 0; i < lines.length; i++) {
    const match = pattern.exec(lines[i]);
    if (!match) continue;
    const indent = match[1].replaceAll("\t", "        ").length;
    let end = i + 1;
    while (end < lines.length && (!lines[end].trim() || (lines[end].match(/^\s*/)?.[0].replaceAll("\t", "        ").length ?? 0) > indent)) end++;
    const colon = lines[i].lastIndexOf(":");
    blocks.push({name: match[2], line: i + 1, indent, header: lines[i], body: lines[i].slice(colon + 1) + "\n" + lines.slice(i + 1, end).join("\n")});
  }
  return blocks;
}
