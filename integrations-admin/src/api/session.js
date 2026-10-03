export const sessionApi = (api) => ({
  async me() { const r = await api.get("/me"); api.setCsrf(r.csrf); return r; },
  async login(password) { const r = await api.post("/login", { password }); api.setCsrf(r.csrf); return r; },
  logout: () => api.post("/logout"),
});
