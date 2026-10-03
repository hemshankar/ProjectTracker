export const auditApi = (api) => ({ list: (limit = 100) => api.get(`/audit?limit=${limit}`) });
