import axios from "axios";

export const api = axios.create({ baseURL: "/api" });

export const getConfig = () => api.get("/config").then((r) => r.data);
export const getMe = () => api.get("/me").then((r) => r.data);
export const logout = () => api.post("/auth/logout");
export const listApps = () => api.get("/apps").then((r) => r.data);
export const getApp = (id) => api.get(`/apps/${id}`).then((r) => r.data);
export const createApp = (body) => api.post("/apps", body).then((r) => r.data);
export const updateApp = (id, body) => api.patch(`/apps/${id}`, body).then((r) => r.data);
export const deleteApp = (id) => api.delete(`/apps/${id}`);

export const listDomains = (id) => api.get(`/apps/${id}/domains`).then((r) => r.data);
export const addDomain = (id, host) => api.post(`/apps/${id}/domains`, { host }).then((r) => r.data);
export const setPrimaryDomain = (id, domainId) =>
  api.post(`/apps/${id}/domains/${domainId}/primary`).then((r) => r.data);
export const deleteDomain = (id, domainId) => api.delete(`/apps/${id}/domains/${domainId}`);

export const getEnv = (id) => api.get(`/apps/${id}/env`).then((r) => r.data);
export const putEnv = (id, vars) => api.put(`/apps/${id}/env`, vars).then((r) => r.data);

export const listSecretKeys = (id) =>
  api.get(`/apps/${id}/secrets`).then((r) => r.data);
export const putSecret = (id, key, value) =>
  api.put(`/apps/${id}/secrets`, { key, value });
export const deleteSecret = (id, key) => api.delete(`/apps/${id}/secrets/${key}`);

export const getStatus = (id) => api.get(`/apps/${id}/status`).then((r) => r.data);
export const getRuntimeLogs = (id, tail = 300) =>
  api.get(`/apps/${id}/runtime-logs`, { params: { tail } }).then((r) => r.data);

export const listDeploys = (id) =>
  api.get(`/apps/${id}/deploys`).then((r) => r.data);
export const triggerDeploy = (id, ref) =>
  api.post(`/apps/${id}/deploys`, { ref: ref || null }).then((r) => r.data);
export const rollback = (id, deployId) =>
  api.post(`/apps/${id}/rollback`, { deploy_id: deployId }).then((r) => r.data);
