/* Lifescroll — single-page app */
const API = "";
const store = {
  get token() { return localStorage.getItem("ls_token") || ""; },
  set token(v) { v ? localStorage.setItem("ls_token", v) : localStorage.removeItem("ls_token"); },
  get user() { try { return JSON.parse(localStorage.getItem("ls_user") || "null"); } catch { return null; } },
  set user(v) { v ? localStorage.setItem("ls_user", JSON.stringify(v)) : localStorage.removeItem("ls_user"); },
  get draft() { try { return JSON.parse(localStorage.getItem("ls_draft") || "null"); } catch { return null; } },
  set draft(v) { v ? localStorage.setItem("ls_draft", JSON.stringify(v)) : localStorage.removeItem("ls_draft"); },
};

const state = {
  config: {}, questions: [], answers: [], index: 0,
  startedAt: null, timerId: null, pollId: null, currentBook: null, mode: "login",
};

const $ = (id) => document.getElementById(id);
const el = (tag, cls, html) => { const n = document.createElement(tag);
  if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };

function toast(msg, ms = 3200) {
  const t = $("toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(t._t); t._t = setTimeout(() => (t.hidden = true), ms);
}

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && store.token) headers.Authorization = `Bearer ${store.token}`;
  const res = await fetch(API + path, { method, headers,
    body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || `Request failed (${res.status})`),
    { status: res.status });
  return data;
}

/* ------------------------------------------------------------------ routing */
const VIEWS = ["landing", "auth", "interview", "generating", "book", "library"];
function show(view) {
  VIEWS.forEach((v) => { const n = $("view-" + v); if (n) n.hidden = v !== view; });
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (view !== "generating" && state.pollId) { clearInterval(state.pollId); state.pollId = null; }
  history.replaceState(null, "", "#" + view);
}

function syncNav() {
  const signedIn = !!store.token;
  $("navSignIn").hidden = signedIn;
  $("navSignOut").hidden = !signedIn;
  $("navLibrary").hidden = !signedIn;
}

document.addEventListener("click", (e) => {
  const target = e.target.closest("[data-nav]");
  if (!target) return;
  e.preventDefault();
  const view = target.dataset.nav;
  if (view === "auth" && store.token) return startOrResumeInterview();
  if (view === "library") return openLibrary();
  show(view);
});

/* --------------------------------------------------------------------- auth */
function setAuthMode(mode) {
  state.mode = mode;
  const signup = mode === "signup";
  $("authTitle").textContent = signup ? "Start your biography" : "Welcome back";
  $("authSub").textContent = signup
    ? "One account keeps every book you write."
    : "Sign in to keep writing your book.";
  $("nameField").hidden = !signup;
  $("authSubmit").textContent = signup ? "Create account" : "Sign in";
  $("switchText").textContent = signup ? "Already have an account?" : "New here?";
  $("authSwitch").textContent = signup ? "Sign in" : "Create an account";
  $("authPassword").autocomplete = signup ? "new-password" : "current-password";
  $("authError").hidden = true;
}

$("authSwitch").onclick = () => setAuthMode(state.mode === "signup" ? "login" : "signup");

$("authForm").onsubmit = async (e) => {
  e.preventDefault();
  const btn = $("authSubmit"), err = $("authError");
  err.hidden = true; btn.disabled = true;
  const original = btn.textContent; btn.textContent = "One moment…";
  try {
    const path = state.mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    const data = await api(path, { method: "POST", auth: false, body: {
      email: $("authEmail").value.trim(), password: $("authPassword").value,
      name: $("authName").value.trim() } });
    store.token = data.token; store.user = data.user;
    syncNav(); toast(`Signed in as ${data.user.email}`);
    startOrResumeInterview();
  } catch (ex) {
    err.textContent = ex.message; err.hidden = false;
  } finally { btn.disabled = false; btn.textContent = original; }
};

$("googleBtn").onclick = () => {
  const { supabase_url } = state.config;
  if (!supabase_url) return toast("Google sign-in needs Supabase configured.");
  const redirect = encodeURIComponent(location.origin + "/#auth");
  location.href = `${supabase_url}/auth/v1/authorize?provider=google&redirect_to=${redirect}`;
};

$("navSignOut").onclick = () => {
  store.token = null; store.user = null; state.currentBook = null;
  syncNav(); show("landing"); toast("Signed out.");
};

async function captureOAuthRedirect() {
  const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
  const token = hash.get("access_token");
  if (!token) return false;
  store.token = token;
  try {
    const me = await api("/api/auth/me");
    store.user = me.user; syncNav();
    history.replaceState(null, "", location.pathname);
    toast(`Welcome, ${me.user.email}`);
    startOrResumeInterview();
    return true;
  } catch { store.token = null; return false; }
}

/* ---------------------------------------------------------------- interview */
async function loadQuestions() {
  if (state.questions.length) return;
  const data = await api("/api/interview/spine", { auth: false });
  state.questions = data.questions.map((q) => ({ ...q, answer: "", followups: [] }));
}

async function startOrResumeInterview() {
  await loadQuestions();
  const draft = store.draft;
  if (draft?.questions?.length) {
    state.questions = draft.questions; state.index = draft.index || 0;
    state.startedAt = draft.startedAt || Date.now();
  } else {
    state.index = 0; state.startedAt = Date.now();
  }
  startTimer(); renderQuestion(); show("interview");
}

function saveDraft() {
  store.draft = { questions: state.questions, index: state.index, startedAt: state.startedAt };
}

function startTimer() {
  clearInterval(state.timerId);
  state.timerId = setInterval(() => {
    const secs = Math.floor((Date.now() - state.startedAt) / 1000);
    const mm = String(Math.floor(secs / 60)).padStart(2, "0");
    const ss = String(secs % 60).padStart(2, "0");
    $("timer").textContent = `${mm}:${ss}`;
    const pct = Math.min(100, (secs / 900) * 100);
    $("timeBar").style.width = pct + "%";
    if (secs >= 900) $("timeHint").textContent = "Fifteen minutes — finish whenever you like.";
  }, 1000);
}

function renderQuestion() {
  const q = state.questions[state.index];
  if (!q) return;
  $("qCounter").textContent = `Question ${state.index + 1} of ${state.questions.length}`;
  $("questionText").textContent = q.activeFollowup || q.question;
  $("followupNote").hidden = !q.activeFollowup;
  if (q.activeFollowup) $("followupNote").textContent = `Following up on: “${q.question}”`;
  $("answerBox").value = q.answer || "";
  updateCounts();
  $("prevBtn").disabled = state.index === 0;

  const list = $("qlist"); list.innerHTML = "";
  state.questions.forEach((item, i) => {
    const li = el("li", i === state.index ? "current" : (item.answer ? "done" : ""),
      `<b>${String(i + 1).padStart(2, "0")}</b><span>${item.question.slice(0, 62)}${item.question.length > 62 ? "…" : ""}</span>`);
    li.onclick = () => { commitAnswer(); state.index = i; renderQuestion(); };
    list.appendChild(li);
  });
}

function commitAnswer() {
  const q = state.questions[state.index];
  if (!q) return;
  const text = $("answerBox").value.trim();
  if (q.activeFollowup && text && text !== q.answer) {
    q.answer = text;
  } else { q.answer = text; }
  saveDraft();
}

function updateCounts() {
  const words = ($("answerBox").value.trim().match(/\S+/g) || []).length;
  $("wordCount").textContent = `${words} word${words === 1 ? "" : "s"}`;
  const answered = state.questions.filter((q) => q.answer?.trim()).length;
  const total = state.questions.reduce(
    (n, q) => n + ((q.answer || "").match(/\S+/g) || []).length, 0);
  $("answeredCount").textContent = answered;
  $("totalWords").textContent = total.toLocaleString();
}

$("answerBox").addEventListener("input", updateCounts);

$("nextBtn").onclick = async () => {
  commitAnswer();
  const q = state.questions[state.index];
  const words = ((q.answer || "").match(/\S+/g) || []).length;

  if (words >= 12 && !q.followupDone) {
    $("nextBtn").disabled = true; $("nextBtn").textContent = "Thinking…";
    try {
      const data = await api("/api/interview/followup", { method: "POST", body: {
        question: q.question, answer: q.answer,
        asked: state.questions.flatMap((x) => x.followups || []) } });
      q.followupDone = true; q.activeFollowup = data.question;
      q.followups = [...(q.followups || []), data.question];
      $("answerBox").value = q.answer + "\n\n";
      renderQuestion();
      $("answerBox").focus();
      $("answerBox").selectionStart = $("answerBox").value.length;
      saveDraft();
      return;
    } catch { /* fall through to next question */ }
    finally { $("nextBtn").disabled = false; $("nextBtn").textContent = "Save & continue"; }
  }
  advance();
};

function advance() {
  const q = state.questions[state.index];
  if (q) q.activeFollowup = null;
  if (state.index < state.questions.length - 1) { state.index++; renderQuestion(); }
  else { toast("That's the whole interview — ready when you are."); updateCounts(); }
  saveDraft();
}

$("skipBtn").onclick = () => { commitAnswer(); advance(); };
$("prevBtn").onclick = () => { commitAnswer(); if (state.index > 0) { state.index--; renderQuestion(); } };

/* ------------------------------------------------- Web Speech API dictation */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null, listening = false, baseText = "";

if (!SR) {
  $("micStatus").textContent = "Voice input needs Chrome, Edge or Safari — typing works everywhere.";
  $("micBtn").disabled = true;
}

function toggleMic() {
  if (!SR) return;
  if (listening) { recognition.stop(); return; }

  recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = navigator.language || "en-US";
  baseText = $("answerBox").value;

  recognition.onstart = () => {
    listening = true;
    $("micBtn").classList.add("live");
    $("micLabel").textContent = "Listening — tap to stop";
    $("micStatus").textContent = "Recording. Speak naturally; pauses are fine.";
  };
  recognition.onresult = (event) => {
    let finalText = "", interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const chunk = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalText += chunk + " "; else interim += chunk;
    }
    if (finalText) baseText = (baseText + " " + finalText).replace(/\s+/g, " ").trim();
    $("answerBox").value = (baseText + (interim ? " " + interim : "")).trim();
    updateCounts();
  };
  recognition.onerror = (e) => {
    if (e.error === "not-allowed") toast("Microphone blocked — allow access in your browser.");
    else if (e.error !== "no-speech") toast("Speech error: " + e.error);
  };
  recognition.onend = () => {
    listening = false;
    $("micBtn").classList.remove("live");
    $("micLabel").textContent = "Start talking";
    $("micStatus").textContent = "Saved. Tap to keep talking.";
    commitAnswer();
  };
  recognition.start();
}
$("micBtn").onclick = toggleMic;

/* --------------------------------------------------------------- generation */
$("finishBtn").onclick = async () => {
  commitAnswer();
  if (listening) recognition.stop();
  const answers = state.questions
    .filter((q) => q.answer?.trim())
    .map((q) => ({ question: q.question, answer: q.answer }));
  const words = answers.reduce((n, a) => n + (a.answer.match(/\S+/g) || []).length, 0);
  if (words < 40) return toast("Tell us a little more first — at least a few sentences.");

  $("finishBtn").disabled = true;
  try {
    const { id } = await api("/api/biographies", { method: "POST", body: {
      answers, title: (store.user?.name ? `${store.user.name}: A Life` : "A Life") } });
    store.draft = null;
    clearInterval(state.timerId);
    show("generating");
    $("genLog").innerHTML = "";
    pollBook(id);
  } catch (ex) { toast(ex.message); }
  finally { $("finishBtn").disabled = false; }
};

function pollBook(id) {
  clearInterval(state.pollId);
  const seen = new Set();
  const tick = async () => {
    try {
      const data = await api(`/api/biographies/${id}?full=0`);
      const pct = Math.round((data.progress || 0) * 100);
      $("genBar").style.width = pct + "%";
      $("genPct").textContent = pct + "%";
      $("genStage").textContent = data.stage || "Working…";
      if (data.title && data.title !== "Untitled Life") $("genTitle").textContent = `“${data.title}”`;
      (data.book?.chapters || []).forEach((ch) => {
        if (ch.status === "done" && !seen.has(ch.number)) {
          seen.add(ch.number);
          $("genLog").prepend(el("li", "", `Chapter ${ch.number}: ${ch.title}`));
        }
      });
      if (data.status === "complete") { clearInterval(state.pollId); openBook(id); }
      if (data.status === "failed") {
        clearInterval(state.pollId);
        toast("Generation failed: " + (data.error || "unknown error"), 6000);
        $("genStage").textContent = "Something went wrong. " + (data.error || "");
      }
    } catch (ex) { clearInterval(state.pollId); toast(ex.message); }
  };
  tick();
  state.pollId = setInterval(tick, 2500);
}

/* --------------------------------------------------------------- book reader */
async function openBook(id) {
  const data = await api(`/api/biographies/${id}`);
  state.currentBook = data;
  const book = data.book || {};
  $("bookTitle").textContent = book.title || data.title || "Untitled";
  $("bookSubtitle").textContent = book.subtitle || "";
  $("bookMeta").textContent = [
    "A Lifescroll biography",
    book.word_count ? `${book.word_count.toLocaleString()} words` : null,
    book.estimated_pages ? `≈${book.estimated_pages} pages` : null,
    book.model,
  ].filter(Boolean).join(" · ");
  $("demoNote").hidden = !book.demo;
  $("pdfBtn").disabled = false;

  const toc = $("toc"), pages = $("pages");
  toc.innerHTML = "<h4>Contents</h4>"; pages.innerHTML = "";

  if (book.dedication) {
    pages.appendChild(el("p", "chapter-era", `“${book.dedication}”`));
  }

  (book.chapters || []).forEach((ch) => {
    const link = el("a", "", `<b>${ch.number}.</b> ${ch.title}`);
    link.href = `#ch-${ch.number}`;
    link.onclick = (e) => { e.preventDefault();
      document.getElementById(`ch-${ch.number}`)?.scrollIntoView({ behavior: "smooth" }); };
    toc.appendChild(link);

    const section = el("section", "chapter");
    section.id = `ch-${ch.number}`;
    section.appendChild(el("div", "chapter-head",
      `<p class="chapter-num">CHAPTER ${ch.number}</p><h2>${escapeHtml(ch.title)}</h2>` +
      (ch.era ? `<p class="chapter-era">${escapeHtml(ch.era)}</p>` : "")));

    const body = el("div", "chapter-body");
    const paras = (ch.text || "").split("\n").map((p) => p.trim()).filter(Boolean);
    if (!paras.length) body.appendChild(el("p", "pending", "This chapter is still being written…"));

    const pics = ch.images || [];
    const gap = pics.length ? Math.max(1, Math.floor(paras.length / (pics.length + 1))) : 0;
    let picIndex = 0;
    paras.forEach((text, i) => {
      body.appendChild(el("p", "", escapeHtml(text)));
      while (picIndex < pics.length && gap && i + 1 === (picIndex + 1) * gap) {
        body.appendChild(figureFor(pics[picIndex])); picIndex++;
      }
    });
    while (picIndex < pics.length) { body.appendChild(figureFor(pics[picIndex])); picIndex++; }

    section.appendChild(body);
    section.appendChild(el("div", "chapter-rule"));
    pages.appendChild(section);
  });

  show("book");
  observeChapters();
}

function figureFor(pic) {
  const fig = el("figure");
  const img = document.createElement("img");
  img.loading = "lazy"; img.className = "loading"; img.alt = pic.caption || pic.prompt || "";
  img.src = pic.url;
  img.onload = () => img.classList.remove("loading");
  img.onerror = () => { img.classList.remove("loading"); fig.remove(); };
  fig.appendChild(img);
  if (pic.caption) fig.appendChild(el("figcaption", "", escapeHtml(pic.caption)));
  return fig;
}

function observeChapters() {
  const links = [...document.querySelectorAll(".toc a")];
  const obs = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      links.forEach((a) => a.classList.toggle("active",
        a.getAttribute("href") === "#" + entry.target.id));
    });
  }, { rootMargin: "-20% 0px -70% 0px" });
  document.querySelectorAll(".chapter").forEach((c) => obs.observe(c));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

$("pdfBtn").onclick = () => {
  if (!state.currentBook) return;
  toast("Building your PDF — illustrations are downloaded first, this can take a minute.", 6000);
  window.open(`/api/biographies/${state.currentBook.id}/pdf?token=${encodeURIComponent(store.token)}`,
    "_blank");
};

/* ------------------------------------------------------------------ library */
async function openLibrary() {
  show("library");
  const grid = $("libGrid"); grid.innerHTML = "";
  try {
    const { biographies } = await api("/api/biographies");
    $("libEmpty").hidden = biographies.length > 0;
    biographies.forEach((b) => {
      const card = el("div", "lib-card",
        `<span class="status ${b.status}">${b.status}</span>
         <h3>${escapeHtml(b.title || "Untitled")}</h3>
         <p class="muted small">${escapeHtml(b.subtitle || b.stage || "")}</p>
         <p class="muted small">${new Date(b.created_at * 1000).toLocaleString()}</p>`);
      const row = el("div", "row");
      const open = el("button", "primary sm", b.status === "complete" ? "Read" : "View progress");
      open.onclick = (e) => { e.stopPropagation();
        if (b.status === "complete") openBook(b.id);
        else { show("generating"); $("genLog").innerHTML = ""; pollBook(b.id); } };
      const del = el("button", "ghost sm", "Delete");
      del.onclick = async (e) => { e.stopPropagation();
        if (!confirm("Delete this biography?")) return;
        await api(`/api/biographies/${b.id}`, { method: "DELETE" });
        openLibrary(); };
      row.append(open, del); card.appendChild(row);
      card.onclick = () => open.click();
      grid.appendChild(card);
    });
  } catch (ex) { toast(ex.message); }
}

$("newBookBtn").onclick = () => { store.draft = null; state.questions = []; startOrResumeInterview(); };

/* ---------------------------------------------------------------- sample */
$("demoBtn").onclick = () => {
  state.currentBook = null;
  const sample = {
    title: "The Long Way Home", subtitle: "A sample chapter",
    chapters: [{ number: 1, title: "Kitchen Table Gospels", era: "Childhood, 1970s",
      text: `The kettle went on at six, and that was the first sound of every day I can remember.\nMy mother stood at the window with her back to the room, and the light came in the way it does in that part of the world — thin, silver, apologetic. She would say the same three words to nobody in particular: right then, come on. It was a summons and a blessing at once.\nThis is a sample chapter. Sign in, talk for fifteen minutes, and Lifescroll will write eleven more like it — about your kitchen, your mother, your six o'clock.`,
      images: [{ prompt: "1970s kitchen at dawn, kettle steaming, woman at window",
                 caption: "The kettle went on at six.",
                 url: "https://image.pollinations.ai/prompt/1970s%20kitchen%20at%20dawn%2C%20kettle%20steaming%2C%20a%20woman%20standing%20at%20the%20window%2C%20thin%20silver%20morning%20light%2C%20cinematic%20nostalgic%20film%20grain%2C%20painterly?width=1024&height=576&nologo=true&seed=7" }] }],
  };
  state.currentBook = null;
  $("bookTitle").textContent = sample.title;
  $("bookSubtitle").textContent = sample.subtitle;
  $("bookMeta").textContent = "Sample · not your book yet";
  $("demoNote").hidden = true;
  const toc = $("toc"), pages = $("pages");
  toc.innerHTML = "<h4>Contents</h4><a href='#ch-1'><b>1.</b> Kitchen Table Gospels</a>";
  pages.innerHTML = "";
  const ch = sample.chapters[0];
  const section = el("section", "chapter"); section.id = "ch-1";
  section.appendChild(el("div", "chapter-head",
    `<p class="chapter-num">CHAPTER 1</p><h2>${ch.title}</h2><p class="chapter-era">${ch.era}</p>`));
  const body = el("div", "chapter-body");
  ch.text.split("\n").forEach((p, i) => { body.appendChild(el("p", "", escapeHtml(p)));
    if (i === 1) body.appendChild(figureFor(ch.images[0])); });
  section.appendChild(body); pages.appendChild(section);
  $("pdfBtn").disabled = true;
  show("book");
};

/* --------------------------------------------------------------- bootstrap */
(async function init() {
  syncNav();
  setAuthMode("login");
  try {
    state.config = await api("/api/config", { auth: false });
    $("modelPill").hidden = false;
    $("modelPill").textContent = state.config.ai_live
      ? `⚡ ${state.config.model}` : "demo mode · no GROQ_API_KEY";
    $("oauthWrap").hidden = !state.config.google_oauth;
    $("footStatus").textContent =
      `auth: ${state.config.auth_provider} · ai: ${state.config.ai_live ? "live" : "demo"}`;
  } catch { /* API unreachable; landing page still renders */ }

  if (await captureOAuthRedirect()) return;

  if (store.token) {
    try {
      const me = await api("/api/auth/me");
      store.user = me.user; syncNav();
      const { biographies } = await api("/api/biographies");
      if (biographies.length) return openLibrary();
      return startOrResumeInterview();
    } catch { store.token = null; store.user = null; syncNav(); }
  }
  show("landing");
})();
