(function () {
  const parts = window.location.pathname.split("/");
  const sessionId = parts[parts.length - 1] || parts[parts.length - 2];
  const token = new URLSearchParams(window.location.search).get("token");
  if (!sessionId || !token) {
    document.body.innerHTML = "<p style='color:#fff;padding:40px'>Missing session. <a href='/'>Start over</a></p>";
    return;
  }

  const api = (path, opts = {}) =>
    fetch(`/api/sessions/${sessionId}${path}`, {
      ...opts,
      headers: {
        "Content-Type": "application/json",
        "X-Session-Token": token,
        ...(opts.headers || {}),
      },
    });

  const el = (id) => document.getElementById(id);
  const agentPill = el("agentPill");
  const drivePill = el("drivePill");
  const driveLink = el("driveLink");
  const jobStatus = el("jobStatus");
  const progress = el("progress");
  const progressBar = el("progressBar");
  const installCard = el("installCard");
  const toast = el("toast");

  let session = null;
  let toastTimer = null;

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.add("hidden"), 2800);
  }

  function setAgentPill(connected) {
    agentPill.textContent = connected
      ? "GetME: online"
      : "GetME: offline — paste install command in Terminal";
    agentPill.className = "pill " + (connected ? "ok" : "err");
    el("connectDriveBtn").disabled = !connected;
    el("saveLinkBtn").disabled = !connected;
    el("processBtn").disabled = !connected || !session?.drive_link;
    driveLink.disabled = !connected;

    if (connected) {
      installCard.classList.add("dimmed");
      el("installHint").classList.add("hidden");
      el("installDoneHint").classList.remove("hidden");
      el("installSteps").classList.add("hidden");
    } else {
      installCard.classList.remove("dimmed");
      el("installHint").classList.remove("hidden");
      el("installDoneHint").classList.add("hidden");
      el("installSteps").classList.remove("hidden");
    }
  }

  function setDrivePill(connected) {
    drivePill.textContent = connected ? "Drive: connected" : "Drive: not connected";
    drivePill.className = "pill " + (connected ? "ok" : "wait");
  }

  function renderJob() {
    if (!session) return;
    const st = session.job_status;
    if (st === "idle" || !st) {
      progress.classList.add("hidden");
      jobStatus.textContent = session.drive_link ? "Ready to process." : "Save a folder link first.";
      jobStatus.className = "status";
      return;
    }
    if (st === "done") {
      progress.classList.remove("hidden");
      progressBar.style.width = "100%";
      const p = session.job_progress || {};
      jobStatus.textContent = `Done! ${p.faces_found || 0} faces, ${p.clusters || 0} people.`;
      jobStatus.className = "status ok";
      return;
    }
    if (st === "error") {
      jobStatus.textContent = session.job_error || "Processing failed.";
      jobStatus.className = "status err";
      return;
    }
    progress.classList.remove("hidden");
    const p = session.job_progress || {};
    const total = p.total_files || 0;
    const done = p.processed_files || 0;
    const pct = total ? Math.round((100 * done) / total) : 0;
    progressBar.style.width = pct + "%";
    jobStatus.textContent = `${st}: ${done}/${total} photos, ${p.faces_found || 0} faces`;
    jobStatus.className = "status";
  }

  async function refresh() {
    try {
      const resp = await api("");
      session = await resp.json();
      if (!resp.ok) return;
      el("eventTitle").textContent = session.event_name;
      el("guestUrl").textContent = session.guest_url;
      driveLink.value = session.drive_link || "";
      setAgentPill(session.agent_connected);
      setDrivePill(session.drive_connected);
      renderJob();
    } catch (_) {}
  }

  async function loadInstall() {
    const resp = await api("/install");
    const data = await resp.json();
    el("installCmd").textContent = data.one_liner;
    if (!data.oauth_client_configured) {
      el("oauthMissingHint").classList.remove("hidden");
    }
  }

  el("copyInstall").addEventListener("click", async () => {
    const text = el("installCmd").textContent;
    try {
      await navigator.clipboard.writeText(text);
      showToast("Copied — paste in Terminal");
      el("copyInstall").textContent = "Copied!";
      setTimeout(() => {
        el("copyInstall").textContent = "Copy install command";
      }, 2000);
    } catch (_) {
      showToast("Select the command and copy manually (Cmd+C)");
    }
  });

  el("copyGuest").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(el("guestUrl").textContent);
      showToast("Guest link copied");
    } catch (_) {}
  });

  el("connectDriveBtn").addEventListener("click", async () => {
    const btn = el("connectDriveBtn");
    btn.disabled = true;
    jobStatus.textContent = "Opening Google sign-in…";
    jobStatus.className = "status";
    try {
      const resp = await api("/google/start", { method: "POST" });
      const data = await resp.json();
      if (!resp.ok) {
        jobStatus.textContent = data.detail || "Could not start Google sign-in.";
        jobStatus.className = "status err";
        btn.disabled = false;
        return;
      }
      window.location.href = data.auth_url;
    } catch (_) {
      jobStatus.textContent = "Network error.";
      jobStatus.className = "status err";
      btn.disabled = false;
    }
  });

  el("saveLinkBtn").addEventListener("click", async () => {
    const link = driveLink.value.trim();
    if (!link) return;
    jobStatus.textContent = "Saving…";
    const resp = await api("/config", {
      method: "PUT",
      body: JSON.stringify({ drive_link: link }),
    });
    session = await resp.json();
    if (!resp.ok) {
      jobStatus.textContent = session.detail || "Save failed.";
      jobStatus.className = "status err";
      return;
    }
    jobStatus.textContent = "Folder link saved and sent to your Mac.";
    jobStatus.className = "status ok";
    el("processBtn").disabled = !session.agent_connected;
    renderJob();
  });

  el("processBtn").addEventListener("click", async () => {
    el("processBtn").disabled = true;
    jobStatus.textContent = "Starting processing on your Mac…";
    const resp = await api("/process", { method: "POST" });
    session = await resp.json();
    if (!resp.ok) {
      jobStatus.textContent = session.detail || "Could not start.";
      jobStatus.className = "status err";
      el("processBtn").disabled = false;
      return;
    }
    renderJob();
    el("processBtn").disabled = false;
  });

  loadInstall();

  const returnParams = new URLSearchParams(window.location.search);
  if (returnParams.get("drive_connected")) {
    jobStatus.textContent = "Google Drive connected.";
    jobStatus.className = "status ok";
    returnParams.delete("drive_connected");
    const q = returnParams.toString();
    window.history.replaceState({}, "", window.location.pathname + (q ? "?" + q : ""));
  } else if (returnParams.get("drive_error")) {
    jobStatus.textContent = "Google sign-in failed: " + returnParams.get("drive_error");
    jobStatus.className = "status err";
    returnParams.delete("drive_error");
    const q = returnParams.toString();
    window.history.replaceState({}, "", window.location.pathname + (q ? "?" + q : ""));
  }

  refresh();
  setInterval(refresh, 2000);
})();
