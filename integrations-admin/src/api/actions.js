export const actionsApi = (api) => ({
  list: () => api.get("/actions"),
  update: (action, patch) => api.patch(`/actions/${action}`, patch),
});
