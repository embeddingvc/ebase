const chat = document.getElementById("chat");
const form = document.getElementById("form");
const promptEl = document.getElementById("prompt");
const permEl = document.getElementById("perm");
const sendBtn = document.getElementById("send");
const clearBtn = document.getElementById("clear");
const btnLabel = sendBtn.querySelector(".btn-label");
const btnSpinner = sendBtn.querySelector(".btn-spinner");

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function addMessage(role, text, { error = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = `bubble${error ? " err" : ""}`;
  const label = document.createElement("div");
  label.className = "role";
  label.textContent = role === "user" ? "You" : "Claude";
  bubble.appendChild(label);
  const body = document.createElement("div");
  body.innerHTML = escapeHtml(text).replace(/\n/g, "<br/>");
  bubble.appendChild(body);
  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const prompt = promptEl.value.trim();
  if (!prompt) return;

  addMessage("user", prompt);
  promptEl.value = "";

  sendBtn.disabled = true;
  btnSpinner.hidden = false;
  btnLabel.textContent = "Running…";

  try {
    const body = {
      prompt,
      permissionMode: permEl.value || "dontAsk",
    };
    const r = await fetch("/api/claude", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!data.ok) {
      const err = data.error || `HTTP ${r.status}`;
      const detail = [data.stderr, data.stdout].filter(Boolean).join("\n---\n");
      addMessage("assistant", `${err}\n\n${detail}`.trim(), { error: true });
      return;
    }
    const out = [data.stdout, data.stderr && `(stderr)\n${data.stderr}`]
      .filter(Boolean)
      .join("\n");
    addMessage("assistant", out || "(empty output)");
  } catch (err) {
    addMessage("assistant", String(err), { error: true });
  } finally {
    sendBtn.disabled = false;
    btnSpinner.hidden = true;
    btnLabel.textContent = "Send to Claude";
  }
});

clearBtn.addEventListener("click", () => {
  chat.innerHTML = "";
});
