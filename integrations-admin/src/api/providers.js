export const providersApi = (api) => ({
  list: () => api.get("/providers"),
  update: (toolType, patch) => api.patch(`/providers/${toolType}`, patch),
  testConnect: (toolType) => api.post(`/providers/${toolType}/test-connect`, { callbackUrl: window.location.origin }),
  testAction: (toolType) => api.post(`/providers/${toolType}/test-action`),
});
