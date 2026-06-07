const SCOPE = location.pathname === "/mock" ? "mock" : "live";
const IS_MOCK = SCOPE === "mock";

function withScope(url) {
  if (!IS_MOCK) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}scope=mock`;
}

const API = {
  health: "/api/dashboard/health",
  connections: "/api/dashboard/connections",
  routines: "/api/dashboard/routines",
  execution: "/api/dashboard/execution-history",
  meetings: "/api/dashboard/meetings",
  mockConversation: "/api/mock/conversation",
  regressionCases: "/api/mock/regression/cases",
  regressionStatus: "/api/mock/regression/status",
  regressionRun: "/api/mock/regression/run",
  regressionStop: "/api/mock/regression/stop",
};

let currentTab = "connections";

const HEALTH_POLL_MS = 15000;
const CONVERSATION_POLL_MS = 1500;
const REGRESSION_POLL_MS = 1000;

let mockConvSessions = [];
let mockConvCases = [];
let mockConvSelectedCaseId = null;
let mockConvLastHistoryLen = 0;
let mockConvPollTimer = null;
let regressionPollTimer = null;
let regressionRunning = false;
let regressionLogCleared = false;
let regressionCases = [];
let regressionStatusCache = null;

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
  const modeLabel = data.mcp_mode === "mock" ? "Mock" : "Live";
  el("system-tip").textContent = `${modeLabel} · ${data.data_root || "—"}`;
  el("mode-badge").textContent = modeLabel;
}

async function refreshHealth() {
  try {
    renderHealth(await fetchJson(withScope(API.health)));
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
    const data = await fetchJson(withScope(API.routines));
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

// ── Mock conversation (Conversation tab) ─────────────────────────────────────

function selectedMockSession() {
  if (!mockConvSessions.length) return null;
  if (mockConvSelectedCaseId) {
    const hit = mockConvSessions.find((s) => s.test_case_id === mockConvSelectedCaseId);
    if (hit) return hit;
  }
  return mockConvSessions[0];
}

function mockCaseLabel(c) {
  return `${c.case_id}${c.prospect_name ? ` — ${c.prospect_name}` : ""}`;
}

function syncMockCaseSelects(caseId) {
  if (!caseId) return;
  mockConvSelectedCaseId = caseId;
  const convSelect = el("mock-conv-case-select");
  const regSelect = el("regression-case-select");
  if (convSelect && convSelect.value !== caseId) convSelect.value = caseId;
  if (regSelect && regSelect.value !== caseId) regSelect.value = caseId;
  updateRegressionCaseDetail();
}

function renderMockCaseSelects() {
  const cases = mockConvCases.length ? mockConvCases : regressionCases;
  const options = cases.length
    ? cases
    : [{ case_id: "happy_path", prospect_name: "Alex Chen" }];

  if (!mockConvSelectedCaseId && options.length) {
    mockConvSelectedCaseId = options[0].case_id;
  }

  const convSelect = el("mock-conv-case-select");
  if (convSelect) {
    convSelect.innerHTML = options
      .map((c) => {
        const selected = c.case_id === mockConvSelectedCaseId ? " selected" : "";
        return `<option value="${escapeHtml(c.case_id)}"${selected}>${escapeHtml(mockCaseLabel(c))}</option>`;
      })
      .join("");
  }

  const regSelect = el("regression-case-select");
  if (regSelect) {
    regSelect.innerHTML = options
      .map((c) => {
        const selected = c.case_id === mockConvSelectedCaseId ? " selected" : "";
        return `<option value="${escapeHtml(c.case_id)}"${selected}>${escapeHtml(mockCaseLabel(c))}</option>`;
      })
      .join("");
  }
  updateRegressionCaseDetail();
}

function renderChatBubble(msg, isNew, scripted) {
  const sender = msg.sender === "operator" ? "operator" : "prospect";
  const label = scripted
    ? `Scripted slot ${msg.scripted_slot ?? msg.index ?? "—"}`
    : sender === "operator"
      ? "You"
      : "Prospect";
  const step = !scripted && msg.sequence_step != null ? ` · step ${msg.sequence_step}` : "";
  const attachments = (msg.attachments || [])
    .map((a) => {
      const name = typeof a === "string" ? a : a.filename || a.type || "attachment";
      return `<span class="chat-attachment"><span class="material-symbols-outlined text-[14px]">attach_file</span>${escapeHtml(name)}</span>`;
    })
    .join("");
  const newClass = isNew ? " chat-message--new" : "";
  const scriptedClass = scripted ? " chat-message--scripted" : "";
  return [
    `<div class="chat-message chat-message--${sender}${newClass}${scriptedClass}" data-index="${msg.index}">`,
    '<div class="flex flex-col max-w-[78%]">',
    `<div class="chat-meta">${escapeHtml(label)}${escapeHtml(step)}</div>`,
    `<div class="chat-bubble">${escapeHtml(msg.text || "")}${attachments}</div>`,
    "</div></div>",
  ].join("");
}

function renderMockConversationThread(session, prevLen) {
  const thread = el("mock-conv-thread");
  const history = session?.history || [];
  const scripted = session?.scripted_replies || [];
  const isLive = Boolean(session?.live);

  if (history.length) {
    const startNewAt = prevLen > 0 && history.length > prevLen ? prevLen : history.length;
    thread.innerHTML = history
      .map((msg, idx) => renderChatBubble(msg, idx >= startNewAt, false))
      .join("");
    mockConvLastHistoryLen = history.length;
    thread.scrollTop = thread.scrollHeight;
    return;
  }

  if (!isLive && scripted.length) {
    thread.innerHTML = [
      '<p class="text-[11px] text-on-surface-variant mb-3">Scripted prospect replies for this case — run regression to see the live thread.</p>',
      scripted.map((msg) => renderChatBubble(msg, false, true)).join(""),
    ].join("");
    mockConvLastHistoryLen = 0;
    return;
  }

  thread.innerHTML = '<p class="text-sm text-on-surface-variant">No messages in this session yet — run regression to start.</p>';
  mockConvLastHistoryLen = 0;
}

function renderMockConversationMeta(session) {
  if (!session) {
    el("mock-conv-session-badge").textContent = "no session";
    el("mock-conv-meta").textContent = "—";
    el("mock-conv-stage").textContent = "—";
    el("mock-conv-next-action").textContent = "—";
    el("mock-conv-email").textContent = "—";
    el("mock-conv-meeting").textContent = "—";
    el("mock-conv-case-id").textContent = "—";
    el("mock-conv-case-desc").textContent = "—";
    el("mock-conv-stat-op").textContent = "—";
    el("mock-conv-stat-prospect").textContent = "—";
    el("mock-conv-stat-slots").textContent = "—";
    el("mock-conv-stat-ended").textContent = "—";
    el("mock-conv-stage-history").innerHTML = "";
    return;
  }

  const prospect = session.prospect || {};
  const conv = session.conversation || {};
  const tc = session.test_case || {};
  const name = prospect.name || session.prospect_id || "session";
  const badge = session.live
    ? session.ended
      ? "ended"
      : session.connection_accepted
        ? "connected"
        : "live"
    : "fixture";
  el("mock-conv-session-badge").textContent = badge;
  el("mock-conv-meta").textContent = [
    name,
    session.test_case_id ? `case ${session.test_case_id}` : null,
    session.live ? `${session.history_length ?? 0} msgs` : `${(session.scripted_replies || []).length} scripted replies`,
  ]
    .filter(Boolean)
    .join(" · ");

  el("mock-conv-stage").textContent = conv.outreach_stage || prospect.outreach_stage || "—";
  el("mock-conv-next-action").textContent = conv.next_action || "—";
  el("mock-conv-email").textContent = conv.email || "—";
  el("mock-conv-meeting").textContent = conv.meeting_link || "—";

  el("mock-conv-case-id").textContent = session.test_case_id || "—";
  el("mock-conv-case-desc").textContent = tc.description || "—";

  const opTurns = (session.history || []).filter((m) => m.sender === "operator").length;
  const prospectTurns = (session.history || []).filter((m) => m.sender === "prospect").length;
  el("mock-conv-stat-op").textContent = String(opTurns);
  el("mock-conv-stat-prospect").textContent = String(prospectTurns);
  el("mock-conv-stat-slots").textContent =
    tc.total_reply_slots != null
      ? `${prospectTurns}/${tc.non_null_replies ?? tc.total_reply_slots}`
      : String(prospectTurns);
  el("mock-conv-stat-ended").textContent = session.ended
    ? session.ended_reason || "yes"
    : session.live
      ? "no"
      : "—";

  const stages = conv.stage_history || [];
  const histEl = el("mock-conv-stage-history");
  if (!stages.length) {
    histEl.innerHTML = '<li class="text-on-surface-variant">—</li>';
  } else {
    histEl.innerHTML = stages
      .map(
        (s) =>
          `<li><span class="font-bold text-on-surface">${escapeHtml(s.stage || "—")}</span> · ${escapeHtml(s.entered_at || s.at || "")}</li>`
      )
      .join("");
  }

  renderMockCaseSelects();
}

function renderMockConversation(data) {
  mockConvSessions = data.sessions || [];
  mockConvCases = data.cases || mockConvCases;
  if (data.cases?.length) {
    regressionCases = data.cases;
  }
  if (!mockConvSelectedCaseId) {
    if (regressionStatusCache?.case_id) {
      mockConvSelectedCaseId = regressionStatusCache.case_id;
    } else if (mockConvCases.length) {
      mockConvSelectedCaseId = mockConvCases[0].case_id;
    } else if (mockConvSessions.length) {
      mockConvSelectedCaseId = mockConvSessions[0].test_case_id;
    }
  }
  renderMockCaseSelects();
  const session = selectedMockSession();
  const prevLen = mockConvLastHistoryLen;
  renderMockConversationMeta(session);
  if (session) {
    renderMockConversationThread(session, prevLen);
  } else {
    el("mock-conv-thread").innerHTML =
      '<p class="text-sm text-on-surface-variant">No test cases found under outreach/mock/fixtures/.</p>';
    mockConvLastHistoryLen = 0;
  }
}

async function refreshMockConversation() {
  const errEl = el("error-conversation");
  if (errEl) errEl.hidden = true;
  try {
    renderMockConversation(await fetchJson(API.mockConversation));
  } catch (err) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = `Failed to load mock conversation: ${err.message}`;
    }
  }
}

function shouldPollConversation() {
  return IS_MOCK && (currentTab === "conversation" || regressionRunning);
}

function updateConversationPolling() {
  if (shouldPollConversation()) {
    if (!mockConvPollTimer) {
      mockConvPollTimer = setInterval(() => {
        refreshMockConversation();
      }, CONVERSATION_POLL_MS);
    }
  } else if (mockConvPollTimer) {
    clearInterval(mockConvPollTimer);
    mockConvPollTimer = null;
  }
}

// ── Regression runner (Regression tab) ───────────────────────────────────────

function regressionIsActive(status) {
  return status === "starting" || status === "running";
}

function formatIsoLocal(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function renderRegressionStatus(data) {
  regressionStatusCache = data;
  const status = data.status || "idle";
  regressionRunning = regressionIsActive(status);

  if (data.case_id) {
    syncMockCaseSelects(data.case_id);
  }

  const badge = el("regression-status-badge");
  badge.textContent = status;
  badge.className = `text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded regression-status-badge--${status}`;

  el("regression-started").textContent = formatIsoLocal(data.started_at);
  el("regression-finished").textContent = formatIsoLocal(data.finished_at);
  el("regression-pid").textContent = data.pid != null ? String(data.pid) : "—";
  el("regression-exit-code").textContent = data.exit_code != null ? String(data.exit_code) : "—";

  const errBox = el("regression-error");
  if (data.error) {
    errBox.hidden = false;
    errBox.textContent = data.error;
  } else {
    errBox.hidden = true;
    errBox.textContent = "";
  }

  el("regression-log-path").textContent = data.log_path ? `Log: ${data.log_path}` : "";

  const runBtn = el("btn-regression-run");
  const stopBtn = el("btn-regression-stop");
  const spinner = el("regression-run-spinner");
  const active = regressionRunning;
  runBtn.disabled = active;
  stopBtn.disabled = !active;
  spinner.classList.toggle("hidden", !active);

  if (!regressionLogCleared || regressionRunning) {
    const logEl = el("regression-log");
    const lines = data.log_tail || [];
    logEl.textContent = lines.length
      ? lines.join("\n")
      : 'No regression run yet — press "Run regression" to start.';
    logEl.scrollTop = logEl.scrollHeight;
    if (regressionRunning) regressionLogCleared = false;
  }

  updateConversationPolling();
  updateRegressionPolling();
}

async function refreshRegressionStatus() {
  const errEl = el("error-regression");
  if (errEl) errEl.hidden = true;
  try {
    renderRegressionStatus(await fetchJson(API.regressionStatus));
  } catch (err) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = `Failed to load regression status: ${err.message}`;
    }
  }
}

function shouldPollRegression() {
  return IS_MOCK && (currentTab === "regression" || regressionRunning);
}

function updateRegressionPolling() {
  if (shouldPollRegression()) {
    if (!regressionPollTimer) {
      regressionPollTimer = setInterval(() => {
        refreshRegressionStatus();
      }, REGRESSION_POLL_MS);
    }
  } else if (regressionPollTimer) {
    clearInterval(regressionPollTimer);
    regressionPollTimer = null;
  }
}

function renderRegressionCasePicker() {
  renderMockCaseSelects();
}

function updateRegressionCaseDetail() {
  const select = el("regression-case-select");
  const detail = el("regression-case-detail");
  const caseId = select?.value;
  const hit = regressionCases.find((c) => c.case_id === caseId);
  if (!hit) {
    detail.textContent = "";
    return;
  }
  const parts = [
    hit.description,
    hit.end_condition ? `End: ${hit.end_condition}` : null,
    hit.total_reply_slots != null ? `${hit.non_null_replies}/${hit.total_reply_slots} reply slots` : null,
  ].filter(Boolean);
  detail.textContent = parts.join(" · ");
}

async function loadRegressionCases() {
  try {
    const data = await fetchJson(API.regressionCases);
    regressionCases = data.cases || [];
    mockConvCases = regressionCases;
    renderMockCaseSelects();
  } catch (err) {
    console.warn("loadRegressionCases failed", err);
    if (!regressionCases.length) {
      regressionCases = [];
      renderMockCaseSelects();
    }
  }
}

async function startRegressionRun() {
  const caseId = el("regression-case-select")?.value || mockConvSelectedCaseId || "happy_path";
  syncMockCaseSelects(caseId);
  const errEl = el("error-regression");
  if (errEl) errEl.hidden = true;
  regressionLogCleared = false;
  mockConvLastHistoryLen = 0;
  try {
    renderRegressionStatus(
      await fetchJson(API.regressionRun, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_id: caseId }),
      })
    );
    updateConversationPolling();
    updateRegressionPolling();
    refreshMockConversation();
  } catch (err) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = err.message;
    }
  }
}

async function stopRegressionRun() {
  const errEl = el("error-regression");
  if (errEl) errEl.hidden = true;
  try {
    renderRegressionStatus(
      await fetchJson(API.regressionStop, { method: "POST" })
    );
  } catch (err) {
    if (errEl) {
      errEl.hidden = false;
      errEl.textContent = err.message;
    }
  }
}

function initRegressionControls() {
  el("btn-regression-run")?.addEventListener("click", startRegressionRun);
  el("btn-regression-stop")?.addEventListener("click", stopRegressionRun);
  el("regression-case-select")?.addEventListener("change", (e) => {
    syncMockCaseSelects(e.target.value);
    mockConvLastHistoryLen = 0;
    refreshMockConversation();
  });
  el("btn-regression-clear")?.addEventListener("click", () => {
    regressionLogCleared = true;
    el("regression-log").textContent = "(log view cleared — polling will resume on next update)";
  });
}

function initMockConversationControls() {
  el("mock-conv-case-select")?.addEventListener("change", (e) => {
    syncMockCaseSelects(e.target.value);
    mockConvLastHistoryLen = 0;
    refreshMockConversation();
  });
}

// ── Scope UI (Live vs Mock) ──────────────────────────────────────────────────

function initScopeUI() {
  const liveLink = el("scope-link-live");
  const mockLink = el("scope-link-mock");
  const hash = location.hash || "#connections";

  if (liveLink) {
    liveLink.href = `/${hash}`;
    liveLink.classList.toggle("scope-link--active", !IS_MOCK);
  }
  if (mockLink) {
    mockLink.href = `/mock${hash}`;
    mockLink.classList.toggle("scope-link--active", IS_MOCK);
  }

  document.querySelectorAll(".nav-item--mock").forEach((node) => {
    node.hidden = !IS_MOCK;
  });
}

function stampLastSynced() {
  const syncEl = document.getElementById("last-synced");
  if (!syncEl) return;
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  syncEl.textContent = `Last synced at ${hh}:${mm}:${ss}`;
  syncEl.classList.remove("hidden");
}

function refreshCurrentTab() {
  refreshHealth();
  loadTab(currentTab).then(stampLastSynced);
}

const TAB_TITLES = {
  connections: ["Prospect Performance", "Active connections and outreach stages."],
  routines: ["Routine Run History", "Recent runs of the per-prospect scheduler sweeps."],
  meetings: ["Scheduled Meetings", "Prospects who showed meeting interest."],
  conversation: ["Mock conversation", "Live DM thread synced from mock_linkedin_sessions.json."],
  regression: ["Regression test", "Run pytest against the mock outreach workflow."],
};

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
  const [title, sub] = TAB_TITLES[tabId] || TAB_TITLES.connections;
  el("page-title").textContent = title;
  el("page-subtitle").textContent = sub;
  updateConversationPolling();
  updateRegressionPolling();
}

async function loadTab(tabId) {
  const errEl = el(`error-${tabId}`);
  if (errEl) errEl.hidden = true;
  try {
    if (tabId === "connections") {
      renderConnections(await fetchJson(withScope(API.connections)));
    } else if (tabId === "routines") {
      renderExecution(await fetchJson(`${withScope(API.execution)}?limit=50&offset=0`));
    } else if (tabId === "meetings") {
      renderMeetings(await fetchJson(withScope(API.meetings)));
    } else if (tabId === "conversation") {
      await loadRegressionCases();
      await refreshMockConversation();
    } else if (tabId === "regression") {
      await loadRegressionCases();
      await refreshRegressionStatus();
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

function validTabs() {
  const tabs = new Set(["connections", "routines", "meetings"]);
  if (IS_MOCK) {
    tabs.add("conversation");
    tabs.add("regression");
  }
  return tabs;
}

document.addEventListener("DOMContentLoaded", () => {
  initScopeUI();

  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      setTab(btn.dataset.tab);
      loadTab(btn.dataset.tab);
    });
  });
  initModals();

  if (IS_MOCK) {
    initRegressionControls();
    initMockConversationControls();
    loadRegressionCases();
    refreshRegressionStatus();
  }

  const tabs = validTabs();
  const hashTab = location.hash.slice(1);
  const initialTab = tabs.has(hashTab) ? hashTab : "connections";
  setTab(initialTab);
  Promise.all([refreshHealth(), refreshCampaignGoal(), loadTab(initialTab)]).then(stampLastSynced);
  setInterval(refreshHealth, HEALTH_POLL_MS);
  setInterval(refreshCurrentTab, 60_000);
});
