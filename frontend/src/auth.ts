let cachedToken: string | null = null;

export async function getLocalToken(apiUrl: string): Promise<string | null> {
  if (cachedToken) {
    return cachedToken;
  }
  try {
    const res = await fetch(`${apiUrl}/api/auth/local-token`);
    if (res.ok) {
      const data = (await res.json()) as { token?: string };
      if (data.token) {
        cachedToken = data.token;
        return cachedToken;
      }
    }
  } catch (e) {
    console.warn("Failed to fetch local token:", e);
  }
  return null;
}

export async function getAuthHeaders(apiUrl: string): Promise<Record<string, string>> {
  const token = await getLocalToken(apiUrl);
  if (token) {
    return {
      "X-KELA-Token": token,
    };
  }
  return {};
}
