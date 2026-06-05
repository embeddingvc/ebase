const API = {
  health: "/api/dashboard/health",
  connections: "/api/dashboard/connections",
  routines: "/api/dashboard/routines",
  execution: "/api/dashboard/execution-history",
  meetings: "/api/dashboard/meetings",
};

let currentTab = "connections";

const HEALTH_POLL_MS = 15000;

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.detail || data.error || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function el(id) {
  return document.getElementById(id);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function statusBadge(stageLabel) {
  return `<span class="inline-flex items-center px-2 py-1 rounded-full bg-[#d3e4fe] text-[#0b1c30] text-[11px] font-medium">${escapeHtml(stageLabel || "Unknown")}</span>`;
}

function healthStatusClass(status) {
  if (status === "online" || status === "running" || status === "assumed") return "online";
  if (status === "mock") return "mock";
  if (status === "stale") return "warn";
  return "offline";
}

function healthLabel(status) {
  if (status === "online" || status === "running") return "Online";
  if (status === "assumed") return "Ready";
  if (status === "mock") return "Mock";
  if (status === "stale") return "Stale";
  return "Offline";
}

function healthColorClass(cls) {
  if (cls === "online" || cls === "mock") return "text-emerald-600";
  if (cls === "warn") return "text-amber-600";
  return "text-[#ba1a1a]";
}

function renderHealth(data) {
  const items = [
    { icon: "terminal", title: "Claude CLI", status: data.claude_cli?.status, detail: data.claude_cli?.detail || data.claude_cli?.path || "—" },
    { icon: "open_in_browser", title: "CDP Browser", status: data.cdp_browser?.status, detail: data.cdp_browser?.detail || data.cdp_browser?.url || "—" },
    { icon: "key", title: "LinkedIn Session", status: data.linkedin_session?.status, detail: data.linkedin_session?.detail || "—" },
  ];

  el("health-list").innerHTML = items
    .map((item) => {
      const cls = healthStatusClass(item.status);
      return [
        '<div class="flex items-center justify-between p-3 rounded-lg bg-[#f2f4f6] border border-[#bfc7d1]">',
        '<div class="flex items-center gap-3">',
        `<span class="material-symbols-outlined text-[#005d8f] text-[20px]">${item.icon}</span>`,
        "<div>",
        `<div class="text-[12px] font-bold">${escapeHtml(item.title)}</div>`,
        `<div class="text-[10px] text-[#404850]">${escapeHtml(item.detail)}</div>`,
        "</div></div>",
        '<div class="flex items-center gap-1">',
        `<div class="health-dot health-dot--${cls}"></div>`,
        `<span class="text-[10px] font-bold ${healthColorClass(cls)}">${healthLabel(item.status)}</span>`,
        "</div></div>",
      ].join("");
    })
    .join("");

  const q = data.queue || {};
  el("queue-load").textContent = `${q.load_pct ?? 0}%`;
  el("queue-bar").style.width = `${q.load_pct ?? 0}%`;
  el("queue-detail").textContent = `${q.pending ?? 0} pending · ${q.completed ?? 0} done · ${q.failed ?? 0} failed`;
  el("system-tip").textContent = `${data.mcp_mode === "mock" ? "Mock" : "Live"} · ${data.data_root || "—"}`;
  el("mode-badge").textContent = data.mcp_mode === "mock" ? "Mock" : "Live";
}

async function refreshHealth() {
  try {
    renderHealth(await fetchJson(API.health));
  } catch (err) {
    el("health-list").innerHTML = `<p class="text-[#ba1a1a] text-sm">${escapeHtml(err.message)}</p>`;
  }
}

function renderConnectionSchedule(schedule) {
  if (!schedule || !schedule.routine) {
    return '<span class="text-[11px] text-[#404850]">—</span>';
  }
  const routine = escapeHtml(schedule.routine_label || schedule.routine);
  const lastLine = schedule.last_run_relative
    ? `Last ${escapeHtml(schedule.last_run_relative)}`
    : "Last —";
  const nextRel = schedule.next_run_relative;
  const nextDue = nextRel === "due now";
  const nextLine = nextRel
    ? `Next ${escapeHtml(nextRel)}`
    : "Next —";
  const nextClass = nextDue ? "text-emerald-700 font-bold" : "text-[#404850]";
  return [
    '<div class="flex flex-col">',
    `<span class="text-[11px] text-[#005d8f] font-semibold">${routine}</span>`,
    `<span class="text-[11px] text-[#404850]">${lastLine}</span>`,
    `<span class="text-[11px] ${nextClass}">${nextLine}</span>`,
    "</div>",
  ].join("");
}

function renderConnections(data) {
  const rows = data.connections || [];
  el("connections-count").textContent = `${rows.length} Active`;
  const tbody = el("connections-tbody");
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="py-8 text-center text-[#404850]">No connections yet.</td></tr>';
    return;
  }
  tbody.innerHTML = rows
    .map((row) => {
      const last = row.last_action_relative
        ? `${row.last_action_summary || row.last_action || "—"} (${row.last_action_relative})`
        : row.last_action_summary || row.last_action || "—";
      const profile = row.profile_url
        ? `<a href="${escapeHtml(row.profile_url)}" target="_blank" rel="noopener" class="text-[#005d8f] text-xs font-semibold hover:underline">Profile</a>`
        : "";
      return [
        '<tr class="table-row transition-colors">',
        '<td class="py-3 px-4"><div class="flex items-center gap-3">',
        `<div class="w-8 h-8 rounded-full bg-[#cde5ff] text-[#005d8f] flex items-center justify-center font-bold text-xs">${escapeHtml(row.initials)}</div>`,
        `<span class="text-sm font-bold">${escapeHtml(row.name)}</span>`,
        "</div></td>",
        '<td class="py-3 px-4"><div class="flex flex-col">',
        `<span class="text-sm">${escapeHtml(row.title || "—")}</span>`,
        `<span class="text-[11px] text-[#404850]">${escapeHtml(row.prospect_id)}</span>`,
        "</div></td>",
        `<td class="py-3 px-4">${statusBadge(row.stage_label)}</td>`,
        `<td class="py-3 px-4 text-sm text-[#404850]">${escapeHtml(last)}</td>`,
        `<td class="py-3 px-4">${renderConnectionSchedule(row.routine_schedule)}</td>`,
        `<td class="py-3 px-4 text-right">${profile}</td>`,
        "</tr>",
      ].join("");
    })
    .join("");
}

async function refreshCampaignGoal() {
  try {
    const data = await fetchJson(API.routines);
    if (data.campaign_goal) el("campaign-goal").textContent = data.campaign_goal;
  } catch {
    // The campaign-goal sidebar line is best-effort; failures are silent.
  }
}

function renderExecution(data) {
  const stats = data.stats || {};
  el("stat-success").textContent = stats.success_rate_pct != null ? `${stats.success_rate_pct}%` : "—";
  el("stat-events").textContent = String(stats.total_events ?? 0);
  el("stat-failures").textContent = String(stats.failures ?? 0);
  el("stat-pending").textContent = String(stats.pending ?? 0);

  const entries = data.entries || [];
  const tbody = el("execution-tbody");
  if (!entries.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="py-8 text-center text-[#404850]">No routine runs yet.</td></tr>';
    return;
  }
  const statusClass = {
    success: "bg-emerald-100 text-emerald-800",
    failed: "bg-[#ffdad6] text-[#93000a]",
  };
  tbody.innerHTML = entries
    .map((row) => {
      const st = row.status || "success";
      const badge = statusClass[st] || statusClass.success;
      const startedDate = row.started_at ? new Date(row.started_at).toLocaleDateString() : "—";
      const startedTime = row.started_at ? new Date(row.started_at).toLocaleTimeString() : "";
      const barColor = st === "failed" ? "bg-[#ba1a1a]" : "bg-[#005d8f]";
      return [
        '<tr class="table-row transition-colors">',
        '<td class="px-4 py-4 overflow-hidden">',
        '<div class="flex items-center gap-2 min-w-0">',
        `<div class="w-1.5 h-8 ${barColor} rounded-full flex-shrink-0"></div>`,
        '<div class="min-w-0">',
        `<p class="font-bold truncate text-sm">${escapeHtml(row.routine_name)}</p>`,
        `<p class="text-[11px] text-[#404850] truncate">${escapeHtml(row.skill || row.routine_id || "")}</p>`,
        "</div></div></td>",
        `<td class="px-4 py-4 text-sm"><div class="whitespace-nowrap">${escapeHtml(startedDate)}</div><div class="whitespace-nowrap text-[11px] text-[#404850]">${escapeHtml(startedTime)}</div></td>`,
        `<td class="px-3 py-4 text-sm whitespace-nowrap">${escapeHtml(row.duration_label || "—")}</td>`,
        `<td class="px-3 py-4"><span class="px-2 py-1 rounded-full text-[11px] font-bold ${badge}">${escapeHtml(st)}</span></td>`,
        '<td class="px-4 py-4 text-sm text-[#404850] overflow-hidden max-w-0">',
        `<div class="truncate" title="${escapeHtml(row.note || "")}">${escapeHtml(row.note || "")}</div>`,
        "</td>",
        "</tr>",
      ].join("");
    })
    .join("");
  el("execution-pagination").textContent = `Showing ${data.offset + 1}–${data.offset + entries.length} of ${data.total}`;
}

function renderMeetings(data) {
  const meetings = data.meetings || [];
  el("meetings-total").textContent = `${meetings.length} Meeting${meetings.length === 1 ? "" : "s"}`;
  el("meetings-with-link").textContent = String(data.with_meeting_link ?? 0);
  el("meetings-with-email").textContent = String(data.with_email ?? 0);
  const list = el("meetings-list");
  if (!meetings.length) {
    list.innerHTML = '<p class="text-[#404850] text-sm py-8 text-center">No meeting-interest prospects yet.</p>';
    return;
  }
  list.innerHTML = meetings
    .map((m) => {
      const when = m.scheduled_relative || m.scheduled_at || "Scheduled";
      const channel = m.channel || (m.meeting_link ? "Link" : "TBD");
      const join = m.meeting_link
        ? `<a href="${escapeHtml(m.meeting_link)}" target="_blank" rel="noopener" class="text-[12px] font-bold text-[#005d8f] border border-[#005d8f]/20 bg-[#005d8f]/5 px-3 py-2 rounded-lg hover:bg-[#005d8f]/10">Join</a>`
        : "";
      const profile = m.profile_url
        ? `<a href="${escapeHtml(m.profile_url)}" target="_blank" rel="noopener" class="text-[12px] font-bold text-[#545f73] px-3 py-2 rounded-lg border border-[#bfc7d1]">Profile</a>`
        : "";
      const emailLine = m.email ? `<div class="text-[11px] text-[#404850]">${escapeHtml(m.email)}</div>` : "";
      return [
        '<article class="bg-white rounded-xl border border-[#bfc7d1] overflow-hidden flex hover:bg-blue-50/30 transition-all">',
        '<div class="w-1 bg-[#005d8f] shrink-0"></div>',
        '<div class="p-6 flex-1 grid grid-cols-1 md:grid-cols-3 gap-4 items-center">',
        '<div class="flex items-center gap-4 min-w-0">',
        `<div class="w-12 h-12 rounded-full bg-[#cde5ff] text-[#005d8f] flex items-center justify-center font-bold shrink-0">${escapeHtml(m.initials)}`,
        '<div class="min-w-0">',
        `<h4 class="text-base font-bold truncate">${escapeHtml(m.name)}</h4>`,
        `<p class="text-[11px] text-[#545f73] truncate">${escapeHtml(m.title || m.prospect_id)}</p>`,
        "</div></div>",
        '<div class="space-y-1 text-sm">',
        `<div class="flex items-center gap-2"><span class="material-symbols-outlined text-sm text-[#545f73]">schedule</span>${escapeHtml(when)}</div>`,
        `<div class="flex items-center gap-2 text-[#545f73]"><span class="material-symbols-outlined text-sm">video_chat</span>${escapeHtml(channel)}</div>`,
        emailLine,
        "</div>",
        `<div class="flex justify-end gap-2 flex-wrap">${join}${profile}`,
        "</div></article>",
      ].join("");
    })
    .join("");
}

function stampLastSynced() {
  const el = document.getElementById("last-synced");
  if (!el) return;
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  el.textContent = `Last synced at ${hh}:${mm}:${ss}`;
  el.classList.remove("hidden");
}

function refreshCurrentTab() {
  refreshHealth();
  loadTab(currentTab).then(stampLastSynced);
}

function setTab(tabId) {
  currentTab = tabId;
  location.hash = tabId;
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.hidden = panel.dataset.tab !== tabId;
  });
  document.querySelectorAll(".nav-item").forEach((btn) => {
    const active = btn.dataset.tab === tabId;
    btn.classList.toggle("nav-item--active", active);
    btn.classList.toggle("text-[#404850]", !active);
    btn.classList.toggle("font-bold", active);
  });
  const titles = {
    connections: ["Prospect Performance", "Active connections and outreach stages."],
    routines: ["Routine Run History", "Recent runs of the per-prospect scheduler sweeps."],
    meetings: ["Scheduled Meetings", "Prospects who showed meeting interest."],
  };
  const [title, sub] = titles[tabId] || titles.connections;
  el("page-title").textContent = title;
  el("page-subtitle").textContent = sub;
}

async function loadTab(tabId) {
  const errEl = el(`error-${tabId}`);
  if (errEl) errEl.hidden = true;
  try {
    if (tabId === "connections") {
      renderConnections(await fetchJson(API.connections));
    } else if (tabId === "routines") {
      renderExecution(await fetchJson(`${API.execution}?limit=50&offset=0`));
    } else if (tabId === "meetings") {
      renderMeetings(await fetchJson(API.meetings));
    }
  } catch (err) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = `Failed to load: ${err.message}`;
    }
  }
}

function showModal(panelId) {
  el("modal-overlay").hidden = false;
  el("connection-modal").hidden = panelId !== "connection-modal";
}

function hideModals() {
  el("modal-overlay").hidden = true;
  el("connection-modal").hidden = true;
}

async function submitConnection() {
  const url = el("connection-url-input").value.trim();
  const errEl = el("connection-modal-error");
  const spinner = el("connection-modal-spinner");
  const submitBtn = el("connection-modal-submit");
  errEl.hidden = true;
  if (!url) {
    errEl.textContent = "Enter a LinkedIn profile URL.";
    errEl.hidden = false;
    return;
  }
  submitBtn.disabled = true;
  spinner.classList.remove("hidden");
  try {
    await fetchJson(API.connections, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_url: url }),
    });
    hideModals();
    el("connection-url-input").value = "";
    await loadTab("connections");
  } catch (err) {
    errEl.textContent = err.message;
    errEl.hidden = false;
  } finally {
    submitBtn.disabled = false;
    spinner.classList.add("hidden");
  }
}

function initModals() {
  el("btn-add-connection").addEventListener("click", () => {
    el("connection-modal-error").hidden = true;
    showModal("connection-modal");
    el("connection-url-input").focus();
  });
  el("connection-modal-cancel").addEventListener("click", hideModals);
  el("connection-modal-submit").addEventListener("click", submitConnection);
  el("modal-overlay").addEventListener("click", (e) => {
    if (e.target === el("modal-overlay")) hideModals();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      setTab(btn.dataset.tab);
      loadTab(btn.dataset.tab);
    });
  });
  initModals();
  const validTabs = new Set(["connections", "routines", "meetings"]);
  const initialTab = validTabs.has(location.hash.slice(1)) ? location.hash.slice(1) : "connections";
  setTab(initialTab);
  Promise.all([refreshHealth(), refreshCampaignGoal(), loadTab(initialTab)]).then(stampLastSynced);
  setInterval(refreshHealth, HEALTH_POLL_MS);
  setInterval(refreshCurrentTab, 60_000);
});
