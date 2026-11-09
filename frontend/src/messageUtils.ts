export function sanitizeMessagePayload(
  messages: Array<{ role: "user" | "assistant" | "system"; content?: string | null }>,
) {
  return messages
    .filter((message) => typeof message.content === "string" && message.content.trim().length > 0)
    .map(({ role, content }) => ({ role, content: content as string }));
}
