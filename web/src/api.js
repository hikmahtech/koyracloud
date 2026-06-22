// Tiny fetch wrapper. Replaces axios: prepends /api, sends/parses JSON, and
// throws on non-2xx with an axios-shaped `.response` ({status, data}) so
// callers can keep reading `err.response.data.detail`.
async function req(method, path, { body, params } = {}) {
  let url = "/api" + path;
  if (params) {
    const qs = new URLSearchParams(params).toString();
    if (qs) url += `?${qs}`;
  }
  const opts = { method, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.response = { status: res.status, data };
    throw err;
  }
  return data;
}

const get = (path, params) => req("GET", path, { params });
const post = (path, body) => req("POST", path, { body });
const put = (path, body) => req("PUT", path, { body });
const patch = (path, body) => req("PATCH", path, { body });
const del = (path) => req("DELETE", path);

export const getConfig = () => get("/config");
export const getMe = () => get("/me");
export const joinWaitlist = (email, site_count) => post("/waitlist", { email, site_count });
export const logout = () => post("/auth/logout");

export const listAllowedUsers = () => get("/allowed-users");
export const addAllowedUser = (login) => post("/allowed-users", { login });
export const removeAllowedUser = (login) => del(`/allowed-users/${login}`);
export const listApps = () => get("/apps");
export const getAppsStatus = () => get("/apps/status");
export const getApp = (id) => get(`/apps/${id}`);
export const createApp = (body) => post("/apps", body);
export const updateApp = (id, body) => patch(`/apps/${id}`, body);
export const getNotify = (id) => get(`/apps/${id}/notify`);
export const setNotify = (id, notify_email) => put(`/apps/${id}/notify`, { notify_email });
export const deleteApp = (id) => del(`/apps/${id}`);

export const listDomains = (id) => get(`/apps/${id}/domains`);
export const addDomain = (id, host) => post(`/apps/${id}/domains`, { host });
export const setPrimaryDomain = (id, domainId) =>
  post(`/apps/${id}/domains/${domainId}/primary`);
export const deleteDomain = (id, domainId) => del(`/apps/${id}/domains/${domainId}`);
export const verifyDomain = (id, domainId) =>
  post(`/apps/${id}/domains/${domainId}/verify`);

export const getEnv = (id) => get(`/apps/${id}/env`);
export const putEnv = (id, vars) => put(`/apps/${id}/env`, vars);

export const listSecretKeys = (id) => get(`/apps/${id}/secrets`);
export const putSecret = (id, key, value) => put(`/apps/${id}/secrets`, { key, value });
export const deleteSecret = (id, key) => del(`/apps/${id}/secrets/${key}`);

export const getStatus = (id) => get(`/apps/${id}/status`);
export const getUptime = (id) => get(`/apps/${id}/uptime`);
export const getAnalytics = (id, days = 7) => get(`/apps/${id}/analytics`, { days });
export const setAnalytics = (id, enabled) => put(`/apps/${id}/analytics`, { enabled });
export const getRuntimeLogs = (id, tail = 300) => get(`/apps/${id}/runtime-logs`, { tail });

export const getBackground = (id) => get(`/apps/${id}/background`);
export const getWorkerLogs = (id, worker, tail = 300) =>
  get(`/apps/${id}/workers/${worker}/logs`, { tail });
export const getCronRuns = (id, jobId, limit = 20) =>
  get(`/apps/${id}/cron/${jobId}/runs`, { limit });
export const getCronRunLog = (id, jobId, runId) =>
  get(`/apps/${id}/cron/${jobId}/runs/${runId}/log`);
export const runCronNow = (id, jobId) => post(`/apps/${id}/cron/${jobId}/run`);

export const listDeploys = (id) => get(`/apps/${id}/deploys`);
export const triggerDeploy = (id, ref) => post(`/apps/${id}/deploys`, { ref: ref || null });
export const rollback = (id, deployId) => post(`/apps/${id}/rollback`, { deploy_id: deployId });
