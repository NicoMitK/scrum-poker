"use strict";

const STORAGE_PREFIX = "scrum-poker-session:";
const MAX_ROOM_CODE_LENGTH = 16;

const CARD_LABELS = {
  "coffee": "\u2615",
};

const ROLE_ICONS = {
  product_owner: "\u{1F451}",
  technical_operations: "\u{1F6E0}\uFE0F",
};

const ROLE_NAMES = {
  product_owner: "Product Owner",
  technical_operations: "Technical Operations",
};

const el = (id) => document.getElementById(id);

const dom = {
  joinScreen: el("join-screen"),
  joinForm: el("join-form"),
  joinRoom: el("join-room"),
  joinName: el("join-name"),
  joinSubmit: el("join-submit"),
  joinError: el("join-error"),
  app: el("app"),
  roomLabel: el("room-label"),
  shareBtn: el("share-btn"),
  roundLabel: el("round-label"),
  meLabel: el("me-label"),
  connLabel: el("conn-label"),
  leaveBtn: el("leave-btn"),
  seats: {
    top: el("seats-top"),
    right: el("seats-right"),
    bottom: el("seats-bottom"),
    left: el("seats-left"),
  },
  tableStatus: el("table-status"),
  tableActions: el("table-actions"),
  results: el("results"),
  handTitle: el("hand-title"),
  hand: el("hand"),
  confirmModal: el("confirm-modal"),
  confirmText: el("confirm-text"),
  confirmOk: el("confirm-ok"),
  confirmCancel: el("confirm-cancel"),
};

let token = "";
let roomCode = "";
let selectedRole = "";
let state = null;
let eventSource = null;

/* ----------------------------------------------------------------- room */
function normalizeRoomCode(raw) {
  return (raw || "")
    .toUpperCase()
    .replace(/[^A-Z0-9\-_]/g, "")
    .slice(0, MAX_ROOM_CODE_LENGTH);
}

function roomFromUrl() {
  const match = window.location.pathname.match(/^\/table\/([^/]*)/);
  return match ? normalizeRoomCode(decodeURIComponent(match[1])) : "";
}

function tableUrl(code) {
  return `${window.location.origin}/table/${code}`;
}

function storageKey(code) {
  return STORAGE_PREFIX + code;
}

/* ------------------------------------------------------------------ api */
async function api(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Poker-Token": token,
    },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, data };
}

/* ----------------------------------------------------------------- join */
document.querySelectorAll(".role-btn").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".role-btn").forEach((other) => other.classList.remove("selected"));
    button.classList.add("selected");
    selectedRole = button.dataset.role;
    updateJoinButton();
  });
});

dom.joinName.addEventListener("input", updateJoinButton);
dom.joinRoom.addEventListener("input", () => {
  const caretAtEnd = dom.joinRoom.selectionStart === dom.joinRoom.value.length;
  dom.joinRoom.value = normalizeRoomCode(dom.joinRoom.value);
  if (caretAtEnd) dom.joinRoom.setSelectionRange(dom.joinRoom.value.length, dom.joinRoom.value.length);
  updateJoinButton();
});

function updateJoinButton() {
  dom.joinSubmit.disabled = !(selectedRole && dom.joinName.value.trim() && dom.joinRoom.value.trim());
}

dom.joinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  dom.joinSubmit.disabled = true;
  dom.joinError.hidden = true;
  const code = normalizeRoomCode(dom.joinRoom.value);
  try {
    if (!code) throw new Error("Please enter a team ID.");
    const { ok, data } = await api("/api/join", {
      room: code,
      name: dom.joinName.value.trim(),
      role: selectedRole,
    });
    if (!ok || !data.token) {
      throw new Error(data.error || "Could not join the table.");
    }
    token = data.token;
    roomCode = data.state.room;
    localStorage.setItem(storageKey(roomCode), token);
    history.replaceState(null, "", tableUrl(roomCode));
    render(data.state);
    showApp();
    connect();
  } catch (error) {
    dom.joinError.textContent = error.message || "Something went wrong.";
    dom.joinError.hidden = false;
    dom.joinSubmit.disabled = false;
  }
});

function showApp() {
  dom.joinScreen.hidden = true;
  dom.app.hidden = false;
}

function showJoin() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (roomCode) localStorage.removeItem(storageKey(roomCode));
  token = "";
  state = null;
  dom.app.hidden = true;
  dom.joinScreen.hidden = false;
  dom.joinSubmit.disabled = false;
  if (roomCode) dom.joinRoom.value = roomCode;
  updateJoinButton();
}

dom.leaveBtn.addEventListener("click", async () => {
  await api("/api/leave");
  showJoin();
});

dom.shareBtn.addEventListener("click", async () => {
  const link = tableUrl(roomCode);
  const copied = await copyToClipboard(link);
  const original = roomCode;
  dom.roomLabel.textContent = copied ? "Link copied!" : link;
  dom.shareBtn.title = link;
  window.setTimeout(() => {
    dom.roomLabel.textContent = original;
  }, copied ? 1500 : 6000);
});

async function copyToClipboard(text) {
  // navigator.clipboard only exists in a secure context (https or localhost),
  // so keep the old execCommand trick as a fallback for plain-http hosting.
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (error) {
    // fall through
  }
  try {
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.appendChild(helper);
    helper.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(helper);
    return ok;
  } catch (error) {
    return false;
  }
}

// No "leave" on unload on purpose: a page refresh must not kick you off the
// table. The server removes participants whose event stream stopped (~40s).

/* ------------------------------------------------------------ live feed */
function connect() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/events?token=${encodeURIComponent(token)}`);

  eventSource.onopen = () => setConnection(true);
  eventSource.onerror = () => {
    setConnection(false);
    // The table may be gone (server restart, or everybody left and it was
    // cleaned up). Check once instead of reconnecting forever.
    window.setTimeout(checkSessionStillValid, 2000);
  };
  eventSource.onmessage = (event) => {
    setConnection(true);
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    if (!payload.you) {
      // Session unknown to the server (restart or timeout) -> back to join.
      showJoin();
      return;
    }
    render(payload);
  };
}

function setConnection(online) {
  dom.connLabel.textContent = online ? "live" : "reconnecting…";
  dom.connLabel.classList.toggle("online", online);
  dom.connLabel.classList.toggle("offline", !online);
}

async function checkSessionStillValid() {
  if (!token || !eventSource) return;
  try {
    const response = await fetch("/api/state", { headers: { "X-Poker-Token": token } });
    const data = await response.json();
    if (!data.you) showJoin();
  } catch (error) {
    // Server unreachable - keep the EventSource retrying.
  }
}

/* --------------------------------------------------------------- render */
function cardLabel(value) {
  return CARD_LABELS[value] || value;
}

function requiredVoters(participants) {
  return participants.filter((p) => p.role === "technical_operations");
}

function render(next) {
  state = next;
  if (!state || !state.you) {
    showJoin();
    return;
  }
  showApp();

  roomCode = state.room || roomCode;
  dom.roomLabel.textContent = roomCode;
  dom.shareBtn.title = `Copy the link to table ${roomCode}`;
  dom.roundLabel.textContent = `Round ${state.round}`;
  dom.meLabel.textContent = `${ROLE_ICONS[state.you.role]} ${state.you.name}`;

  renderSeats();
  renderTable();
  renderHandArea();
}

function renderSeats() {
  const order = ["top", "bottom", "left", "right"];
  const iAmProductOwner = state.you.role === "product_owner";
  Object.values(dom.seats).forEach((container) => (container.innerHTML = ""));

  state.participants.forEach((participant, index) => {
    const seat = document.createElement("div");
    seat.className = "seat";
    const isMe = participant.id === state.you.id;
    if (isMe) seat.classList.add("is-me");

    const card = document.createElement("div");
    card.className = "seat-card";
    if (participant.role === "product_owner") {
      card.classList.add("spectator");
      card.textContent = ROLE_ICONS.product_owner;
      card.title = "The Product Owner does not estimate";
    } else if (state.revealed && participant.vote !== null) {
      card.classList.add("revealed");
      card.textContent = cardLabel(participant.vote);
    } else if (participant.hasVoted) {
      card.classList.add("hidden-vote");
      card.textContent = "\u2713";
    } else {
      card.classList.add("pending");
      card.textContent = "…";
    }

    const cardWrap = document.createElement("div");
    cardWrap.className = "seat-card-wrap";
    cardWrap.appendChild(card);

    if (iAmProductOwner && !isMe) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "seat-remove";
      remove.textContent = "\u00D7";
      remove.title = `Remove ${participant.name} from the table`;
      remove.setAttribute("aria-label", `Remove ${participant.name} from the table`);
      remove.addEventListener("click", async () => {
        await api("/api/remove", { id: participant.id });
      });
      cardWrap.appendChild(remove);
    }

    const name = document.createElement("div");
    name.className = "seat-name";
    name.textContent = participant.name;
    name.title = `${participant.name} — ${ROLE_NAMES[participant.role]}`;

    const role = document.createElement("div");
    role.className = "seat-role";
    role.textContent = ROLE_ICONS[participant.role];
    role.title = ROLE_NAMES[participant.role];

    seat.append(cardWrap, name, role);
    dom.seats[order[index % order.length]].appendChild(seat);
  });
}

function renderTable() {
  const voters = requiredVoters(state.participants);
  const voted = voters.filter((p) => p.hasVoted).length;

  dom.tableActions.innerHTML = "";
  dom.results.hidden = true;
  dom.results.innerHTML = "";

  if (state.revealed) {
    dom.tableStatus.textContent = "Cards are on the table!";
    if (state.stats) {
      dom.results.hidden = false;
      addResult("Average", state.stats.average);
      addResult("Lowest", cardLabel(state.stats.min));
      addResult("Highest", cardLabel(state.stats.max));
      if (state.stats.consensus) {
        const consensus = document.createElement("div");
        consensus.className = "result-item consensus";
        consensus.textContent = "\u{1F389} Consensus!";
        dom.results.appendChild(consensus);
      }
    }
    return;
  }

  dom.tableStatus.textContent =
    voters.length === 0
      ? "Waiting for teammates to join…"
      : `${voted} of ${voters.length} have voted`;
}

function restartButton() {
  return makeButton("Restart voting", "ghost", () => {
    askConfirm(
      "This clears every card and starts again at round 1 for everybody. Restart the voting?",
      () => api("/api/restart")
    );
  });
}

function addResult(label, value) {
  const item = document.createElement("div");
  item.className = "result-item";
  const valueEl = document.createElement("span");
  valueEl.className = "result-value";
  valueEl.textContent = value;
  const labelEl = document.createElement("span");
  labelEl.className = "result-label";
  labelEl.textContent = label;
  item.append(valueEl, labelEl);
  dom.results.appendChild(item);
}

function makeButton(text, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = text;
  button.addEventListener("click", onClick);
  return button;
}

function renderHandArea() {
  const isProductOwner = state.you.role === "product_owner";
  dom.hand.innerHTML = "";
  dom.hand.classList.toggle("controls", isProductOwner);

  if (isProductOwner) {
    dom.handTitle.textContent = "Product Owner controls";
    renderProductOwnerControls();
    return;
  }

  dom.handTitle.textContent = "Your cards";
  state.deck.forEach((value) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "card";
    button.textContent = cardLabel(value);
    const meaning =
      value === "coffee"
        ? "Skip — no estimate from me"
        : value === "21+"
        ? "Vote 21 or more — too big, needs splitting"
        : `Vote ${value}`;
    button.title = state.you.vote === value ? "Click again to take the card back" : meaning;
    if (state.you.vote === value) button.classList.add("selected");
    button.disabled = state.revealed;
    button.addEventListener("click", async () => {
      await api("/api/vote", { card: value });
    });
    dom.hand.appendChild(button);
  });
}

function renderProductOwnerControls() {
  const voters = requiredVoters(state.participants);

  if (state.revealed) {
    dom.hand.appendChild(
      makeButton("New round", "primary", async () => {
        await api("/api/reset");
      })
    );
  } else {
    const reveal = makeButton("Reveal cards", "primary", () => {
      const missing = voters.filter((p) => !p.hasVoted);
      if (missing.length > 0) {
        openConfirm(missing);
      } else {
        api("/api/reveal");
      }
    });
    reveal.disabled = voters.length === 0;
    reveal.title = reveal.disabled
      ? "Nobody is estimating yet"
      : "Turn every card face up";
    dom.hand.appendChild(reveal);

    dom.hand.appendChild(
      makeButton("Reset votes", "ghost", async () => {
        await api("/api/reset");
      })
    );
  }

  dom.hand.appendChild(restartButton());
}

/* -------------------------------------------------------------- confirm */
let confirmHandler = null;

function openConfirm(missing) {
  const names = missing.map((p) => p.name).join(", ");
  askConfirm(
    `Not everyone has given their prediction yet. Still missing: ${names}. Reveal the cards anyway?`,
    () => api("/api/reveal")
  );
}

function askConfirm(text, onConfirm) {
  dom.confirmText.textContent = text;
  dom.confirmModal.hidden = false;
  confirmHandler = async () => {
    dom.confirmModal.hidden = true;
    await onConfirm();
  };
}

dom.confirmOk.addEventListener("click", () => {
  if (confirmHandler) confirmHandler();
  confirmHandler = null;
});

dom.confirmCancel.addEventListener("click", () => {
  dom.confirmModal.hidden = true;
  confirmHandler = null;
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !dom.confirmModal.hidden) {
    dom.confirmModal.hidden = true;
    confirmHandler = null;
  }
});

/* --------------------------------------------------------------- start */
async function boot() {
  roomCode = roomFromUrl();
  if (roomCode) {
    dom.joinRoom.value = roomCode;
    document.title = `Scrum Poker — ${roomCode}`;
  }
  updateJoinButton();

  token = roomCode ? localStorage.getItem(storageKey(roomCode)) || "" : "";
  if (!token) {
    (roomCode ? dom.joinName : dom.joinRoom).focus();
    return;
  }

  const response = await fetch("/api/state", { headers: { "X-Poker-Token": token } });
  const data = await response.json().catch(() => null);
  if (!data || !data.you) {
    showJoin();
    dom.joinName.focus();
    return;
  }
  render(data);
  connect();
}

boot();
