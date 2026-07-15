const state = {
  userId: localStorage.getItem("agent-memory-user") || makeId("user"),
  sessionId: localStorage.getItem("agent-memory-session") || makeId("session"),
};

const elements = {
  userId: document.querySelector("#user-id"),
  sessionId: document.querySelector("#session-id"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chat-form"),
  chatInput: document.querySelector("#chat-input"),
  rememberForm: document.querySelector("#remember-form"),
  memoryInput: document.querySelector("#memory-input"),
  recallForm: document.querySelector("#recall-form"),
  recallInput: document.querySelector("#recall-input"),
  recallResults: document.querySelector("#recall-results"),
  memoryList: document.querySelector("#memory-list"),
  modeBadge: document.querySelector("#mode-badge"),
  toast: document.querySelector("#toast"),
};

persistIdentity();
renderIdentity();
loadHealth();
refreshMemories();

document.querySelector("#new-session").addEventListener("click", () => {
  state.sessionId = makeId("session");
  localStorage.setItem("agent-memory-session", state.sessionId);
  renderIdentity();
  elements.messages.innerHTML = "";
  addMessage("assistant", "New conversation started. Your durable user memories remain available.");
  showToast("New conversation, same demo user");
});

document.querySelector("#new-user").addEventListener("click", () => {
  state.userId = makeId("user");
  state.sessionId = makeId("session");
  persistIdentity();
  renderIdentity();
  elements.messages.innerHTML = "";
  elements.recallResults.innerHTML = "";
  addMessage("assistant", "New demo user created with an empty memory partition.");
  refreshMemories();
  showToast("New isolated demo user");
});

document.querySelector("#refresh-memories").addEventListener("click", refreshMemories);

elements.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = elements.chatInput.value.trim();
  if (!message) return;
  addMessage("user", message);
  elements.chatInput.value = "";
  setFormBusy(elements.chatForm, true);
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        user_id: state.userId,
        session_id: state.sessionId,
        message,
      }),
    });
    addMessage("assistant", result.response, result.recalled_memories);
    if (result.remembered_memories.length) {
      showToast(`Stored ${result.remembered_memories.length} durable memory`);
      await refreshMemories();
    }
  } catch (error) {
    addMessage("assistant", error.message);
  } finally {
    setFormBusy(elements.chatForm, false);
    elements.chatInput.focus();
  }
});

elements.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    elements.chatForm.requestSubmit();
  }
});

elements.rememberForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = elements.memoryInput.value.trim();
  if (!text) return;
  setFormBusy(elements.rememberForm, true);
  try {
    const result = await api("/api/memories/remember", {
      method: "POST",
      body: JSON.stringify({ user_id: state.userId, text, category: "explicit" }),
    });
    elements.memoryInput.value = "";
    showToast(result.created ? "Durable memory stored" : "Existing memory refreshed");
    await refreshMemories();
  } catch (error) {
    showToast(error.message);
  } finally {
    setFormBusy(elements.rememberForm, false);
  }
});

elements.recallForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = elements.recallInput.value.trim();
  if (!query) return;
  setFormBusy(elements.recallForm, true);
  try {
    const result = await api("/api/memories/recall", {
      method: "POST",
      body: JSON.stringify({ user_id: state.userId, query, limit: 5 }),
    });
    renderMemoryCards(elements.recallResults, result.memories, false);
  } catch (error) {
    showToast(error.message);
  } finally {
    setFormBusy(elements.recallForm, false);
  }
});

async function loadHealth() {
  try {
    const health = await api("/health");
    elements.modeBadge.textContent = `${health.mode} mode`;
  } catch {
    elements.modeBadge.textContent = "offline";
  }
}

async function refreshMemories() {
  try {
    const result = await api(`/api/users/${encodeURIComponent(state.userId)}/memories?limit=50`);
    renderMemoryCards(elements.memoryList, result.memories, true);
  } catch (error) {
    showToast(error.message);
  }
}

function renderMemoryCards(container, memories, allowDelete) {
  container.innerHTML = "";
  if (!memories.length) {
    container.innerHTML = '<p class="empty">No matching durable memories.</p>';
    return;
  }
  for (const memory of memories) {
    const card = document.createElement("article");
    card.className = "memory-card";
    const score = memory.distance === undefined ? memory.category : `distance ${memory.distance.toFixed(3)}`;
    const label = document.createElement("small");
    label.textContent = score;
    const text = document.createElement("p");
    text.textContent = memory.text;
    card.append(label, text);
    if (allowDelete) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Forget";
      button.addEventListener("click", async () => {
        await api(
          `/api/users/${encodeURIComponent(state.userId)}/memories/${encodeURIComponent(memory.id)}`,
          { method: "DELETE" },
        );
        showToast("Memory forgotten");
        await refreshMemories();
      });
      card.append(button);
    }
    container.append(card);
  }
}

function addMessage(role, text, memories = []) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "Y" : "A";
  const content = document.createElement("div");
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  content.append(paragraph);
  if (memories.length) {
    const attribution = document.createElement("div");
    attribution.className = "attribution";
    for (const memory of memories) {
      const tag = document.createElement("span");
      tag.textContent = `recalled · ${memory.category}`;
      attribution.append(tag);
    }
    content.append(attribution);
  }
  article.append(avatar, content);
  elements.messages.append(article);
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function setFormBusy(form, busy) {
  for (const control of form.querySelectorAll("button, input, textarea")) {
    control.disabled = busy;
  }
}

function makeId(prefix) {
  return `${prefix}-${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`;
}

function persistIdentity() {
  localStorage.setItem("agent-memory-user", state.userId);
  localStorage.setItem("agent-memory-session", state.sessionId);
}

function renderIdentity() {
  elements.userId.textContent = state.userId;
  elements.sessionId.textContent = state.sessionId;
}

let toastTimer;
function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 2600);
}
