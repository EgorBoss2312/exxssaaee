/** Убирает Markdown-разметку из ответа LLM для отображения обычным текстом. */
export function formatChatAnswer(text: string): string {
  let s = text;
  s = s.replace(/\*\*(.+?)\*\*/g, "$1");
  s = s.replace(/__(.+?)__/g, "$1");
  s = s.replace(/^\s*#{1,6}\s+/gm, "");
  s = s.replace(/^\s*[*-]\s+/gm, "• ");
  s = s.replace(/`([^`]+)`/g, "$1");
  return s;
}
