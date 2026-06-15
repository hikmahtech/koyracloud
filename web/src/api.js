import axios from "axios";

export const api = axios.create({ baseURL: "/api" });

export const getConfig = () => api.get("/config").then((r) => r.data);
export const getMe = () => api.get("/me").then((r) => r.data);
export const logout = () => api.post("/auth/logout");

export const listAllowedUsers = () => api.get("/allowed-users").then((r) => r.data);
export const addAllowedUser = (login) => api.post("/allowed-users", { login }).then((r) => r.data);
export const removeAllowedUser = (login) => api.delete(`/allowed-users/${login}`);
export const listApps = () => api.get("/apps").then((r) => r.data);
export const getAppsStatus = () => api.get("/apps/status").then((r) => r.data);
export const getApp = (id) => api.get(`/apps/${id}`).then((r) => r.data);
export const createApp = (body) => api.post("/apps", body).then((r) => r.data);
export const updateApp = (id, body) => api.patch(`/apps/${id}`, body).then((r) => r.data);
export const getNotify = (id) => api.get(`/apps/${id}/notify`).then((r) => r.data);
export const setNotify = (id, notify_email) => api.put(`/apps/${id}/notify`, { notify_email });
export const deleteApp = (id) => api.delete(`/apps/${id}`);

export const listDomains = (id) => api.get(`/apps/${id}/domains`).then((r) => r.data);
export const addDomain = (id, host) => api.post(`/apps/${id}/domains`, { host }).then((r) => r.data);
export const setPrimaryDomain = (id, domainId) =>
  api.post(`/apps/${id}/domains/${domainId}/primary`).then((r) => r.data);
export const deleteDomain = (id, domainId) => api.delete(`/apps/${id}/domains/${domainId}`);
export const verifyDomain = (id, domainId) =>
  api.post(`/apps/${id}/domains/${domainId}/verify`).then((r) => r.data);

export const getEnv = (id) => api.get(`/apps/${id}/env`).then((r) => r.data);
export const putEnv = (id, vars) => api.put(`/apps/${id}/env`, vars).then((r) => r.data);

export const listSecretKeys = (id) =>
  api.get(`/apps/${id}/secrets`).then((r) => r.data);
export const putSecret = (id, key, value) =>
  api.put(`/apps/${id}/secrets`, { key, value });
export const deleteSecret = (id, key) => api.delete(`/apps/${id}/secrets/${key}`);

export const getStatus = (id) => api.get(`/apps/${id}/status`).then((r) => r.data);
export const getUptime = (id) => api.get(`/apps/${id}/uptime`).then((r) => r.data);
export const getAnalytics = (id, days = 7) =>
  api.get(`/apps/${id}/analytics`, { params: { days } }).then((r) => r.data);
export const setAnalytics = (id, enabled) =>
  api.put(`/apps/${id}/analytics`, { enabled });
export const getRuntimeLogs = (id, tail = 300) =>
  api.get(`/apps/${id}/runtime-logs`, { params: { tail } }).then((r) => r.data);

export const getBackground = (id) =>
  api.get(`/apps/${id}/background`).then((r) => r.data);
export const getWorkerLogs = (id, worker, tail = 300) =>
  api.get(`/apps/${id}/workers/${worker}/logs`, { params: { tail } }).then((r) => r.data);
export const getCronRuns = (id, jobId, limit = 20) =>
  api.get(`/apps/${id}/cron/${jobId}/runs`, { params: { limit } }).then((r) => r.data);
export const getCronRunLog = (id, jobId, runId) =>
  api.get(`/apps/${id}/cron/${jobId}/runs/${runId}/log`).then((r) => r.data);
export const runCronNow = (id, jobId) =>
  api.post(`/apps/${id}/cron/${jobId}/run`).then((r) => r.data);

export const listDeploys = (id) =>
  api.get(`/apps/${id}/deploys`).then((r) => r.data);
export const triggerDeploy = (id, ref) =>
  api.post(`/apps/${id}/deploys`, { ref: ref || null }).then((r) => r.data);
export const rollback = (id, deployId) =>
  api.post(`/apps/${id}/rollback`, { deploy_id: deployId }).then((r) => r.data);
