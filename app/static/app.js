const metricsEl = document.getElementById("metrics");
const hotspotsEl = document.getElementById("hotspots");
const needsEl = document.getElementById("needsList");
const tasksEl = document.getElementById("tasksList");
const volunteersEl = document.getElementById("volunteersList");
const insightsEl = document.getElementById("insightsList");
const roleCardsEl = document.getElementById("roleCards");
const rolePrioritiesEl = document.getElementById("rolePriorities");
const forecastListEl = document.getElementById("forecastList");
const forecastInsightsEl = document.getElementById("forecastInsights");
const alertsListEl = document.getElementById("alertsList");
const assignmentsListEl = document.getElementById("assignmentsList");
const completedAssignmentsListEl = document.getElementById("completedAssignmentsList");
const completedTasksListEl = document.getElementById("completedTasksList");
const activityListEl = document.getElementById("activityList");
const allocationOutput = document.getElementById("allocationOutput");
const geminiBadge = document.getElementById("geminiBadge");
const mapStatusEl = document.getElementById("mapStatus");
const lastRefreshEl = document.getElementById("lastRefresh");
const systemHealthEl = document.getElementById("systemHealth");
const toast = document.getElementById("toast");
const categoryFilter = document.getElementById("filterCategory");
const locationFilter = document.getElementById("filterLocation");
const urgencyFilter = document.getElementById("filterUrgency");
const urgencyValue = document.getElementById("urgencyValue");
const reportText = document.getElementById("reportText");
const roleSelect = document.getElementById("roleSelect");
const locationScopeWrap = document.getElementById("locationScopeWrap");
const alertAudience = document.getElementById("alertAudience");
const globalSearchEl = document.getElementById("globalSearch");
const assignmentSearchEl = document.getElementById("assignmentSearch");
const undoDockEl = document.getElementById("undoDock");
const undoLabelEl = document.getElementById("undoLabel");
const undoTimerEl = document.getElementById("undoTimer");
const undoLastBtn = document.getElementById("undoLastBtn");

let autoRefreshTimer = null;
let map = null;
let mapLayer = null;
let pendingActions = [];
let undoTicker = null;

const appState = {
  dashboard: null,
  needs: [],
  tasks: [],
  volunteers: [],
  alerts: [],
  assignments: [],
  completedAssignments: [],
  completedTasks: [],
  activity: [],
  globalSearch: "",
};

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2200);
}

function refreshUndoDock() {
  const active = pendingActions.filter((action) => !action.committed && !action.canceled);
  if (!active.length) {
    undoDockEl.classList.add("hidden");
    if (undoTicker) {
      clearInterval(undoTicker);
      undoTicker = null;
    }
    return;
  }

  const last = active[active.length - 1];
  const seconds = Math.max(0, Math.ceil((last.expiresAt - Date.now()) / 1000));
  undoLabelEl.textContent = last.label;
  undoTimerEl.textContent = `Finalizing in ${seconds}s`;
  undoDockEl.classList.remove("hidden");

  if (!undoTicker) {
    undoTicker = setInterval(() => {
      refreshUndoDock();
    }, 250);
  }
}

function schedulePendingAction(label, commitFn) {
  const action = {
    id: Date.now() + Math.random(),
    label,
    commitFn,
    createdAt: Date.now(),
    expiresAt: Date.now() + 10000,
    committed: false,
    canceled: false,
    timer: null,
  };

  action.timer = setTimeout(async () => {
    if (action.canceled) {
      return;
    }
    action.committed = true;
    try {
      await commitFn();
    } catch (error) {
      showToast(error.message || "Action failed");
    } finally {
      pendingActions = pendingActions.filter((a) => a.id !== action.id);
      refreshUndoDock();
    }
  }, 10000);

  pendingActions.push(action);
  showToast(`${label} queued. You can undo for 10s.`);
  refreshUndoDock();
}

function undoLastPendingAction() {
  const active = pendingActions.filter((action) => !action.committed && !action.canceled);
  if (!active.length) {
    showToast("No pending action to undo");
    return;
  }
  const last = active[active.length - 1];
  last.canceled = true;
  clearTimeout(last.timer);
  pendingActions = pendingActions.filter((a) => a.id !== last.id);
  showToast("Last action canceled");
  refreshUndoDock();
}

function setSystemHealth(ok, message) {
  systemHealthEl.textContent = `System: ${message}`;
  systemHealthEl.style.borderColor = ok ? "#a6e3ce" : "#f2c1c1";
  systemHealthEl.style.background = ok ? "#ecfbf4" : "#fff2f2";
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Request failed");
  }
  return response.json();
}

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderMetrics(metrics) {
  const entries = [
    ["Open Needs", metrics.open_needs],
    ["Open Tasks", metrics.open_tasks],
    ["Active Volunteers", metrics.active_volunteers],
    ["Total Assignments", metrics.total_assignments],
  ];
  metricsEl.innerHTML = entries
    .map(
      ([label, value]) => `
      <article class="metric-card">
        <div class="metric-label">${escapeHtml(label)}</div>
        <div class="metric-value">${escapeHtml(value)}</div>
      </article>`
    )
    .join("");
}

function renderHotspots(needs) {
  const grouped = needs.reduce((acc, need) => {
    const key = need.location || "Unknown";
    if (!acc[key]) {
      acc[key] = { count: 0, urgency: 0 };
    }
    acc[key].count += 1;
    acc[key].urgency += Number(need.urgency_score || 0);
    return acc;
  }, {});

  const hotspots = Object.entries(grouped)
    .map(([location, data]) => ({
      location,
      count: data.count,
      avgUrgency: Math.round(data.urgency / data.count),
    }))
    .sort((a, b) => b.avgUrgency - a.avgUrgency)
    .slice(0, 4);

  hotspotsEl.innerHTML = hotspots.length
    ? hotspots
        .map(
          (spot) => `
      <article class="hotspot">
        <div class="hotspot-title">${escapeHtml(spot.location)}</div>
        <div class="muted">${spot.count} needs | Avg urgency ${spot.avgUrgency}</div>
        <div class="hotspot-bar">
          <div class="hotspot-fill" style="width:${Math.min(100, spot.avgUrgency)}%"></div>
        </div>
      </article>`
        )
        .join("")
    : "<p class='muted'>No hotspot data yet.</p>";
}

function renderNeeds(needs) {
  const search = appState.globalSearch;
  const minUrgency = Number(urgencyFilter.value || 0);
  const locationValue = String(locationFilter.value || "").trim().toLowerCase();
  const categoryValue = String(categoryFilter.value || "").trim().toLowerCase();

  const filtered = needs.filter((need) => {
    const urgencyOk = Number(need.urgency_score || 0) >= minUrgency;
    const locationOk =
      !locationValue || String(need.location || "").toLowerCase().includes(locationValue);
    const categoryOk = !categoryValue || String(need.category || "").toLowerCase() === categoryValue;
    const searchOk =
      !search ||
      `${need.title} ${need.description} ${need.location} ${need.category}`
        .toLowerCase()
        .includes(search);
    return urgencyOk && locationOk && categoryOk && searchOk;
  });

  needsEl.innerHTML = filtered.length
    ? filtered
        .sort((a, b) => b.urgency_score - a.urgency_score)
        .map(
          (n) => `
      <article class="item">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(n.title)}</h3>
          <span class="tag">Urgency ${Math.round(n.urgency_score)}</span>
        </div>
        <p class="muted">${escapeHtml(n.category)} | ${escapeHtml(n.location)}</p>
        <p>${escapeHtml(n.description)}</p>
        <p class="muted">Skills: ${escapeHtml((n.skills || []).join(", ") || "community_outreach")}</p>
      </article>`
        )
        .join("")
    : "<p class='muted'>No needs match current filters.</p>";
}

function renderTasks(tasks) {
  const search = appState.globalSearch;
  tasksEl.innerHTML = tasks.length
    ? tasks
        .sort((a, b) => b.priority_score - a.priority_score)
        .filter((t) => {
          if (!search) {
            return true;
          }
          return `${t.title} ${t.description} ${t.location} ${t.status}`
            .toLowerCase()
            .includes(search);
        })
        .map((t) => {
          const coverage = t.required_people > 0 ? Math.round((t.assigned_count / t.required_people) * 100) : 0;
          return `
      <article class="item">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(t.title)}</h3>
          <span class="tag">Priority ${Math.round(t.priority_score)}</span>
        </div>
        <p class="muted">${escapeHtml(t.location)} | ${escapeHtml(t.status)}</p>
        <p>${escapeHtml(t.description)}</p>
        <p class="muted">Assigned ${t.assigned_count}/${t.required_people} | Coverage ${coverage}%</p>
        <div class="item-actions">
          <button class="btn-small complete-task-btn" data-task-id="${t.id}">Mark Task Complete</button>
        </div>
      </article>`;
        })
        .join("")
    : "<p class='muted'>No tasks found.</p>";
}

function renderVolunteers(volunteers) {
  const search = appState.globalSearch;
  volunteersEl.innerHTML = volunteers.length
    ? volunteers
        .filter((v) => {
          if (!search) {
            return true;
          }
          return `${v.name} ${v.email} ${v.location} ${(v.skills || []).join(" ")}`
            .toLowerCase()
            .includes(search);
        })
        .map(
          (v) => `
      <article class="item">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(v.name)}</h3>
          <span class="tag">${escapeHtml(v.location)}</span>
        </div>
        <p class="muted">${escapeHtml(v.email)} | ${v.availability_hours}h/day</p>
        <p class="muted">Skills: ${escapeHtml((v.skills || []).join(", ") || "none listed")}</p>
      </article>`
        )
        .join("")
    : "<p class='muted'>No volunteers registered.</p>";
}

function renderCategoryFilter(needs) {
  const categories = Array.from(
    new Set(needs.map((n) => String(n.category || "").trim()).filter(Boolean))
  ).sort();
  const current = categoryFilter.value;
  categoryFilter.innerHTML =
    '<option value="">All categories</option>' +
    categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(category)}</option>`).join("");
  categoryFilter.value = current;
}

function renderInsights() {
  const metrics = appState.dashboard?.metrics || {};
  const topNeed = [...appState.needs].sort((a, b) => b.urgency_score - a.urgency_score)[0];
  const topTask = [...appState.tasks].sort((a, b) => b.priority_score - a.priority_score)[0];
  const lowAvailability = appState.volunteers.filter((v) => Number(v.availability_hours || 0) <= 2).length;

  const insights = [];
  if (topNeed) {
    insights.push(`Prioritize ${topNeed.location}: ${topNeed.title} has urgency ${Math.round(topNeed.urgency_score)}.`);
  }
  if (topTask && topTask.assigned_count < topTask.required_people) {
    insights.push(
      `Task gap detected: ${topTask.title} needs ${topTask.required_people - topTask.assigned_count} more volunteers.`
    );
  }
  if ((metrics.open_needs || 0) > (metrics.active_volunteers || 0)) {
    insights.push("Open needs exceed active volunteer capacity. Launch targeted volunteer onboarding in top hotspot zones.");
  }
  if (lowAvailability > 0) {
    insights.push(`${lowAvailability} volunteers have very low daily availability. Consider short shift assignments.`);
  }
  if (!insights.length) {
    insights.push("System is balanced. Keep monitoring hotspot urgency and refresh allocation after each new report.");
  }

  insightsEl.innerHTML = insights.map((tip) => `<li>${escapeHtml(tip)}</li>`).join("");
}

function pressureColor(pressure) {
  if (pressure >= 85) return "#ef4444";
  if (pressure >= 70) return "#f97316";
  if (pressure >= 50) return "#f59e0b";
  return "#22c55e";
}

function renderMap(mapHeat) {
  if (!window.L || !mapHeat?.center) {
    mapStatusEl.textContent = "Map not loaded. Other data is still working.";
    return;
  }
  if (!map) {
    map = L.map("map", { zoomControl: true }).setView([mapHeat.center.lat, mapHeat.center.lng], 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
  }

  if (mapLayer) {
    map.removeLayer(mapLayer);
  }

  mapLayer = L.layerGroup();
  (mapHeat.points || []).forEach((point) => {
    const marker = L.circleMarker([point.lat, point.lng], {
      radius: Math.min(24, 7 + point.need_count * 2),
      color: pressureColor(point.pressure),
      fillColor: pressureColor(point.pressure),
      fillOpacity: 0.5,
      weight: 2,
    });
    marker.bindPopup(`
      <div class="map-popup">
        <strong>${escapeHtml(point.location)}</strong><br />
        Pressure: ${point.pressure}<br />
        Needs: ${point.need_count}<br />
        Avg urgency: ${point.avg_urgency}<br />
        Volunteer gap: ${point.staff_gap}
      </div>
    `);
    marker.addTo(mapLayer);
  });

  mapLayer.addTo(map);
  mapStatusEl.textContent = `Map updated with ${mapHeat.points.length} areas.`;
}

function renderRoleDashboard(payload) {
  roleCardsEl.innerHTML = (payload.cards || [])
    .map(
      (card) => `
      <article class="role-card">
        <div class="label">${escapeHtml(card.label)}</div>
        <div class="value">${escapeHtml(card.value)}</div>
      </article>`
    )
    .join("");
  rolePrioritiesEl.innerHTML = (payload.priorities || [])
    .map((tip) => `<li>${escapeHtml(tip)}</li>`)
    .join("");
}

function renderForecast(payload) {
  const categories = payload.categories || [];
  const maxProjection = Math.max(1, ...categories.map((c) => c.projected_requests || 0));
  forecastListEl.innerHTML = categories.length
    ? categories
        .slice(0, 6)
        .map((item) => {
          const width = Math.round((item.projected_requests / maxProjection) * 100);
          return `
          <article class="forecast-item">
            <div class="forecast-title">${escapeHtml(item.category)}</div>
            <div class="muted">Projected ${item.projected_requests} | Avg urgency ${item.avg_urgency} | Confidence ${Math.round(item.confidence * 100)}%</div>
            <div class="forecast-bar"><div class="forecast-fill" style="width:${width}%"></div></div>
          </article>`;
        })
        .join("")
    : "<p class='muted'>Need more report history for forecasting.</p>";
  forecastInsightsEl.innerHTML = (payload.insights || []).map((tip) => `<li>${escapeHtml(tip)}</li>`).join("");
}

function renderAlerts(alerts) {
  const search = appState.globalSearch;
  alertsListEl.innerHTML = alerts.length
    ? alerts
        .filter((alert) => {
          if (!search) {
            return true;
          }
          return `${alert.channel} ${alert.audience} ${alert.content} ${alert.location_scope || ""}`
            .toLowerCase()
            .includes(search);
        })
        .map(
          (alert) => `
      <article class="item">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(alert.channel.toUpperCase())} alert</h3>
          <span class="tag">${escapeHtml(alert.status)}</span>
        </div>
        <p class="muted">Audience: ${escapeHtml(alert.audience)} ${alert.location_scope ? `| ${escapeHtml(alert.location_scope)}` : ""}</p>
        <p>${escapeHtml(alert.content)}</p>
        <p class="muted">Provider: ${escapeHtml(alert.provider_message || "pending")}</p>
      </article>`
        )
        .join("")
    : "<p class='muted'>No alerts queued yet.</p>";
}

function renderAssignments(assignments) {
  const search = appState.globalSearch;
  const localSearch = String(assignmentSearchEl.value || "").trim().toLowerCase();
  const filtered = assignments.filter((a) => {
    const text = `${a.task_title || ""} ${a.volunteer_name || ""} ${a.location || ""} ${a.status}`.toLowerCase();
    const globalOk = !search || text.includes(search);
    const localOk = !localSearch || text.includes(localSearch);
    return globalOk && localOk;
  });

  assignmentsListEl.innerHTML = filtered.length
    ? filtered
        .map(
          (a) => `
      <article class="item">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(a.task_title || `Task #${a.task_id}`)}</h3>
          <span class="tag">${escapeHtml(a.status)}</span>
        </div>
        <p class="muted">Volunteer: ${escapeHtml(a.volunteer_name || `#${a.volunteer_id}`)} | ${escapeHtml(a.location || "Unknown")}</p>
        <p class="muted">Match score: ${Math.round(a.match_score || 0)}%</p>
        <div class="item-actions">
          <button class="btn-small complete-assignment-btn" data-assignment-id="${a.id}">Mark Assignment Complete</button>
        </div>
      </article>`
        )
        .join("")
    : "<p class='muted'>No assignments found.</p>";
}

function renderCompletedHistory() {
  const completedAssignments = appState.completedAssignments;
  const completedTasks = appState.completedTasks;

  completedAssignmentsListEl.innerHTML = completedAssignments.length
    ? completedAssignments
        .slice(0, 20)
        .map(
          (a) => `
      <article class="item">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(a.task_title || `Task #${a.task_id}`)}</h3>
          <span class="tag">completed</span>
        </div>
        <p class="muted">${escapeHtml(a.volunteer_name || `Volunteer #${a.volunteer_id}`)} | ${escapeHtml(a.location || "Unknown")}</p>
        <div class="item-actions">
          <button class="btn-secondary undo-assignment-btn" data-assignment-id="${a.id}">Undo</button>
        </div>
      </article>`
        )
        .join("")
    : "<p class='muted'>No completed assignments yet.</p>";

  completedTasksListEl.innerHTML = completedTasks.length
    ? completedTasks
        .slice(0, 20)
        .map(
          (t) => `
      <article class="item">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(t.title)}</h3>
          <span class="tag">completed</span>
        </div>
        <p class="muted">${escapeHtml(t.location)} | Task #${t.id}</p>
        <div class="item-actions">
          <button class="btn-secondary undo-task-btn" data-task-id="${t.id}">Undo</button>
        </div>
      </article>`
        )
        .join("")
    : "<p class='muted'>No completed tasks yet.</p>";
}

function renderActivity(events) {
  const search = appState.globalSearch;
  const filtered = events.filter((event) => {
    if (!search) {
      return true;
    }
    return `${event.actor} ${event.action} ${event.entity_type} ${event.details || ""}`
      .toLowerCase()
      .includes(search);
  });

  activityListEl.innerHTML = filtered.length
    ? filtered
        .slice(0, 40)
        .map(
          (event) => `
      <article class="activity-item">
        <div class="activity-head">
          <strong>${escapeHtml(event.action.replaceAll("_", " "))}</strong>
          <span class="tag">${escapeHtml(event.actor)}</span>
        </div>
        <p class="muted">${escapeHtml(event.entity_type)} ${event.entity_id ? `#${event.entity_id}` : ""}</p>
        <p>${escapeHtml(event.details || "No details")}</p>
        <p class="muted">${escapeHtml(event.created_at || "")}</p>
      </article>`
        )
        .join("")
    : "<p class='muted'>No activity yet.</p>";
}

async function refreshDashboard() {
  const [dashboard, volunteers, needs, tasks, alerts, assignments, history, activity] = await Promise.all([
    request("/api/dashboard"),
    request("/api/volunteers"),
    request("/api/needs"),
    request("/api/tasks"),
    request("/api/alerts"),
    request("/api/assignments"),
    request("/api/history/completed"),
    request("/api/activity"),
  ]);

  appState.dashboard = dashboard;
  appState.volunteers = volunteers;
  appState.needs = needs;
  appState.tasks = tasks;
  appState.alerts = alerts;
  appState.assignments = assignments;
  appState.completedAssignments = history.assignments || [];
  appState.completedTasks = history.tasks || [];
  appState.activity = activity || [];

  renderMetrics(dashboard.metrics);
  renderHotspots(needs);
  renderCategoryFilter(needs);
  renderNeeds(needs);
  renderTasks(tasks);
  renderVolunteers(volunteers);
  renderAlerts(alerts);
  renderAssignments(assignments);
  renderCompletedHistory();
  renderActivity(appState.activity);
  renderInsights();

  await Promise.all([loadRoleDashboard(), loadForecast(), loadMapHeat()]);
  lastRefreshEl.textContent = `Last update: ${formatTime(new Date())}`;
  setSystemHealth(true, "working well");
}

async function loadMeta() {
  const meta = await request("/api/meta");
  geminiBadge.textContent = meta.gemini_enabled
    ? `Gemini live (${meta.model})`
    : "Gemini key missing, using local fallback intelligence";
  geminiBadge.style.borderColor = meta.gemini_enabled ? "#9ce5d4" : "#f3c3ba";
  geminiBadge.style.background = meta.gemini_enabled ? "#eafcf6" : "#fff1ec";
}

async function loadRoleDashboard() {
  const role = roleSelect.value;
  const payload = await request(`/api/dashboard/role?role=${encodeURIComponent(role)}`);
  renderRoleDashboard(payload);
}

async function loadForecast() {
  const payload = await request("/api/forecast");
  renderForecast(payload);
}

async function loadMapHeat() {
  const mapHeat = await request("/api/map/heat");
  renderMap(mapHeat);
}

function formatAllocationOutput(result) {
  const assignments = result.assignments || [];
  if (!assignments.length) {
    return "No new matches were created.\n\nTry adding more volunteers or new urgent reports.";
  }

  const lines = [
    `New matches created: ${result.created}`,
    "",
    "Latest matches:",
  ];

  assignments.slice(0, 8).forEach((item, index) => {
    lines.push(
      `${index + 1}. Task #${item.task_id} -> Volunteer #${item.volunteer_id} (match ${Math.round(item.match_score)}%)`
    );
  });

  if (assignments.length > 8) {
    lines.push(`...and ${assignments.length - 8} more matches.`);
  }
  return lines.join("\n");
}

async function runAllocation() {
  const result = await request("/api/allocate", { method: "POST" });
  allocationOutput.textContent = formatAllocationOutput(result);
  showToast(`Allocation complete: ${result.created} assignments created`);
  await refreshDashboard();
}

async function completeTaskNow(taskId) {
  await request(`/api/tasks/${taskId}/complete`, { method: "POST" });
  await refreshDashboard();
}

async function completeAssignmentNow(assignmentId) {
  await request(`/api/assignments/${assignmentId}/complete`, { method: "POST" });
  await refreshDashboard();
}

async function completeAllAssignmentsNow() {
  const result = await request("/api/assignments/complete-all", { method: "POST" });
  await refreshDashboard();
  showToast(`Completed ${result.count} assignments`);
}

async function undoAssignment(assignmentId) {
  await request(`/api/assignments/${assignmentId}/undo`, { method: "POST" });
  showToast("Assignment restored");
  await refreshDashboard();
}

async function undoTask(taskId) {
  await request(`/api/tasks/${taskId}/undo`, { method: "POST" });
  showToast("Task restored");
  await refreshDashboard();
}

document.getElementById("reportForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  try {
    await request("/api/reports", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(form.entries())),
    });
    e.target.reset();
    showToast("Report analyzed and task created");
    await refreshDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("volunteerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const payload = Object.fromEntries(form.entries());
  payload.availability_hours = Number(payload.availability_hours || 4);
  payload.skills = String(payload.skills || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

  try {
    await request("/api/volunteers", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    e.target.reset();
    showToast("Volunteer added successfully");
    await refreshDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("alertForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const payload = Object.fromEntries(form.entries());
  payload.task_id = payload.task_id ? Number(payload.task_id) : null;
  if (!payload.location_scope) {
    payload.location_scope = null;
  }
  try {
    await request("/api/alerts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast("Alert queued");
    e.target.reset();
    await refreshDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("dispatchAlertsBtn").addEventListener("click", async () => {
  try {
    const result = await request("/api/alerts/dispatch", { method: "POST" });
    showToast(`Dispatched ${result.processed} alerts`);
    await refreshDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("completeAllAssignmentsBtn").addEventListener("click", async () => {
  try {
    schedulePendingAction("Complete all pending assignments", async () => {
      await completeAllAssignmentsNow();
    });
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("allocateBtn").addEventListener("click", async () => {
  try {
    await runAllocation();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("allocateNowBtn").addEventListener("click", async () => {
  try {
    await runAllocation();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("seedBtn").addEventListener("click", async () => {
  try {
    await request("/api/demo/seed", { method: "POST" });
    showToast("Demo volunteers loaded");
    await refreshDashboard();
  } catch (error) {
    showToast(error.message);
  }
});

tasksEl.addEventListener("click", async (event) => {
  const button = event.target.closest(".complete-task-btn");
  if (!button) {
    return;
  }
  try {
    const taskId = Number(button.dataset.taskId);
    schedulePendingAction(`Complete task #${taskId}`, async () => {
      await completeTaskNow(taskId);
      showToast("Task marked complete");
    });
  } catch (error) {
    showToast(error.message);
  }
});

assignmentsListEl.addEventListener("click", async (event) => {
  const button = event.target.closest(".complete-assignment-btn");
  if (!button) {
    return;
  }
  try {
    const assignmentId = Number(button.dataset.assignmentId);
    schedulePendingAction(`Complete assignment #${assignmentId}`, async () => {
      await completeAssignmentNow(assignmentId);
      showToast("Assignment marked complete");
    });
  } catch (error) {
    showToast(error.message);
  }
});

completedAssignmentsListEl.addEventListener("click", async (event) => {
  const button = event.target.closest(".undo-assignment-btn");
  if (!button) {
    return;
  }
  try {
    await undoAssignment(button.dataset.assignmentId);
  } catch (error) {
    showToast(error.message);
  }
});

completedTasksListEl.addEventListener("click", async (event) => {
  const button = event.target.closest(".undo-task-btn");
  if (!button) {
    return;
  }
  try {
    await undoTask(button.dataset.taskId);
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("quickAllocate").addEventListener("click", async () => {
  try {
    await runAllocation();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("quickRefresh").addEventListener("click", async () => {
  await refreshDashboard();
  showToast("Dashboard refreshed");
});

document.getElementById("quickScrollIntake").addEventListener("click", () => {
  document.getElementById("intake").scrollIntoView({ behavior: "smooth", block: "start" });
});

document.getElementById("quickScrollVolunteers").addEventListener("click", () => {
  document.getElementById("volunteers").scrollIntoView({ behavior: "smooth", block: "start" });
});

document.querySelectorAll(".template-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    reportText.value = chip.dataset.template || "";
    showToast("Template inserted");
  });
});

alertAudience.addEventListener("change", () => {
  const showScope = alertAudience.value === "location";
  locationScopeWrap.classList.toggle("hidden", !showScope);
});

roleSelect.addEventListener("change", async () => {
  await loadRoleDashboard();
  showToast(`Switched to ${roleSelect.value} view`);
});

locationFilter.addEventListener("input", () => renderNeeds(appState.needs));
categoryFilter.addEventListener("change", () => renderNeeds(appState.needs));
urgencyFilter.addEventListener("input", () => {
  urgencyValue.textContent = `Min urgency: ${urgencyFilter.value}`;
  renderNeeds(appState.needs);
});

globalSearchEl.addEventListener("input", () => {
  appState.globalSearch = String(globalSearchEl.value || "").trim().toLowerCase();
  renderNeeds(appState.needs);
  renderTasks(appState.tasks);
  renderVolunteers(appState.volunteers);
  renderAlerts(appState.alerts);
  renderAssignments(appState.assignments);
  renderActivity(appState.activity);
});

assignmentSearchEl.addEventListener("input", () => {
  renderAssignments(appState.assignments);
});

document.getElementById("autoRefreshToggle").addEventListener("change", (event) => {
  if (event.target.checked) {
    autoRefreshTimer = setInterval(() => {
      refreshDashboard().catch(() => null);
    }, 30000);
    showToast("Auto-refresh enabled");
  } else {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
    showToast("Auto-refresh disabled");
  }
});

undoLastBtn.addEventListener("click", () => {
  undoLastPendingAction();
});

(async function init() {
  locationScopeWrap.classList.add("hidden");
  try {
    await loadMeta();
    await refreshDashboard();
  } catch (error) {
    setSystemHealth(false, "some issue found");
    mapStatusEl.textContent = "Could not load live data. Please refresh.";
    showToast(error.message || "Initialization failed");
  }
})();
