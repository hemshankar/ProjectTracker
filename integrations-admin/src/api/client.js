// The only module that calls fetch. Holds the CSRF token in memory (never in storage).
export class ApiError extends Error {
  constructor(status, message, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function createClient({ base = "/api", fetchImpl = (...a) => fetch(...a), onUnauthorized = () => {} } = {}) {
  let csrf = "";

  async function request(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (method !== "GET") headers["X-Admin-CSRF"] = csrf;
    let res;
    try {
      res = await fetchImpl(base + path, {
        method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "Cannot reach the gateway");
    }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== "/login") onUnauthorized();
    if (!res.ok) {
      const err = data.error || {};
      throw new ApiError(res.status, err.message || `Request failed (${res.status})`, err.detail);
    }
    return data;
  }

  return {
    get: (p) => request("GET", p),
    post: (p, b = {}) => request("POST", p, b),
    patch: (p, b) => request("PATCH", p, b),
    put: (p, b) => request("PUT", p, b),
    del: (p) => request("DELETE", p),
    setCsrf: (t) => { csrf = t; },
  };
}
