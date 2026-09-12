export const BASE = import.meta.env.MODE === 'production' ? '/quant' : '';

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith('http') ? path : `${BASE}${path}`;
  const res = await fetch(url, { credentials: "same-origin", ...init });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    return {
      success: false,
      status: res.status,
      message: payload?.message || payload?.detail || res.statusText,
      ...payload,
    } as T;
  }
  return payload;
}
