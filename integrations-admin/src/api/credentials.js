export const credentialsApi = (api) => ({
  list: () => api.get("/credentials"),
  set: (name, value) => api.put(`/credentials/${name}`, { value }),
  clear: (name) => api.del(`/credentials/${name}`),
});
