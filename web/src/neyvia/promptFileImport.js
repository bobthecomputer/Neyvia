export const MAX_PROMPT_CHARACTERS = 100_000;
export const MAX_PROMPT_FILE_BYTES = 1_000_000;

export async function readPromptImport(file) {
  if (!file || typeof file.name !== "string") throw new TypeError("Choose a .txt or .md file to import.");
  const extension = file.name.toLowerCase().split(".").pop();
  if (!["txt", "md"].includes(extension)) throw new TypeError("Choose a .txt or .md file to import.");
  if (Number(file.size) > MAX_PROMPT_FILE_BYTES) throw new RangeError("This file is too large to import. Choose a text or Markdown file under 1 MB.");
  const text = String(await file.text()).replace(/^\uFEFF/, "");
  if (text.length > MAX_PROMPT_CHARACTERS) throw new RangeError(`This file exceeds the ${MAX_PROMPT_CHARACTERS.toLocaleString()} character prompt limit.`);
  return { fileName: file.name, text };
}
