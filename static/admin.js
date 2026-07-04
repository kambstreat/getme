// GetME! - organizer console: Drive connection + start processing + poll status.
(function () {
  const adminToken = document.getElementById("adminToken");
  const driveLink = document.getElementById("driveLink");
  const startBtn = document.getElementById("startBtn");
  const progress = document.getElementById("progress");
  const progressBar = document.getElementById("progressBar");
  const statusEl = document.getElementById("status");
  const connectBtn = document.getElementById("connectBtn");
  const disconnectBtn = document.getElementById("disconnectBtn");
  const connStatusEl = document.getElementById("connStatus");

  let pollTimer = null;

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  function setConnStatus(msg, kind) {
    connStatusEl.textContent = msg || "";
    connStatusEl.className = "status" + (kind ? " " + kind : "");
  }

  async function refreshConnection(keepStatusMessage) {
    try {
      const resp = await fetch("/api/auth/google/status");
      const data = await resp.json();
      if (data.connected) {
        connectBtn.textContent = "Reconnect";
        disconnectBtn.classList.remove("hidden");
        if (!keepStatusMessage) setConnStatus("Google Drive connected.", "ok");
      } else {
        connectBtn.textContent = "Connect Google Drive";
        disconnectBtn.classList.add("hidden");
        if (!keepStatusMessage) {
          setConnStatus("Not connected. Guests can't be matched until photos are processed.");
        }
      }
    } catch (err) {
      if (!keepStatusMessage) setConnStatus("Could not check connection status.", "err");
    }
  }

  connectBtn.addEventListener("click", async () => {
    const token = adminToken.value.trim();
    if (!token) return setConnStatus("Enter your admin token below first.", "err");
    try {
      const resp = await fetch("/api/auth/google/start", {
        headers: { "X-Admin-Token": token },
      });
      const data = await resp.json();
      if (!resp.ok) return setConnStatus(data.detail || "Failed to start sign-in.", "err");
      window.location.href = data.auth_url;
    } catch (err) {
      setConnStatus("Network error.", "err");
    }
  });

  disconnectBtn.addEventListener("click", async () => {
    const token = adminToken.value.trim();
    if (!token) return setConnStatus("Enter your admin token below first.", "err");
    try {
      const resp = await fetch("/api/auth/google/disconnect", {
        method: "POST",
        headers: { "X-Admin-Token": token },
      });
      const data = await resp.json();
      if (!resp.ok) return setConnStatus(data.detail || "Failed to disconnect.", "err");
      refreshConnection();
    } catch (err) {
      setConnStatus("Network error.", "err");
    }
  });

  // Show the result of an OAuth redirect (?drive_connected=1 / ?drive_error=...).
  const params = new URLSearchParams(window.location.search);
  const fromRedirect = params.has("drive_connected") || params.has("drive_error");
  if (params.get("drive_connected")) {
    setConnStatus("Google Drive connected.", "ok");
  } else if (params.get("drive_error")) {
    setConnStatus("Google sign-in failed: " + params.get("drive_error"), "err");
  }
  if (fromRedirect) {
    window.history.replaceState({}, "", "/admin");
  }

  // Don't let the generic status text overwrite a redirect result message.
  refreshConnection(fromRedirect);

  startBtn.addEventListener("click", async () => {
    const token = adminToken.value.trim();
    const link = driveLink.value.trim();
    if (!token) return setStatus("Enter your admin token.", "err");
    if (!link) return setStatus("Paste a Google Drive folder link.", "err");

    startBtn.disabled = true;
    setStatus("Starting...");
    progress.style.display = "block";
    progressBar.style.width = "0%";

    try {
      const resp = await fetch("/api/drive/process", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Token": token },
        body: JSON.stringify({ drive_link: link }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setStatus(data.detail || "Failed to start.", "err");
        startBtn.disabled = false;
        return;
      }
      poll(data.job_id);
    } catch (err) {
      setStatus("Network error.", "err");
      startBtn.disabled = false;
    }
  });

  function poll(jobId) {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const resp = await fetch(`/api/drive/status/${jobId}`);
        const job = await resp.json();
        if (!resp.ok) {
          setStatus(job.detail || "Status error.", "err");
          clearInterval(pollTimer);
          startBtn.disabled = false;
          return;
        }
        render(job);
        if (job.status === "done" || job.status === "error") {
          clearInterval(pollTimer);
          startBtn.disabled = false;
        }
      } catch (err) {
        setStatus("Lost connection while polling.", "err");
      }
    }, 1500);
  }

  function render(job) {
    const pct = job.total_files
      ? Math.round((100 * job.processed_files) / job.total_files)
      : 0;
    progressBar.style.width = pct + "%";

    if (job.status === "listing") {
      setStatus("Listing photos in the folder...");
    } else if (job.status === "processing") {
      setStatus(
        `Processing ${job.processed_files}/${job.total_files} photos - ${job.faces_found} faces found`
      );
    } else if (job.status === "clustering") {
      setStatus("Grouping faces into people...");
    } else if (job.status === "done") {
      progressBar.style.width = "100%";
      setStatus(
        `Done! ${job.faces_found} faces across ${job.total_files} photos, grouped into ${job.clusters} people. Guests can now scan.`,
        "ok"
      );
    } else if (job.status === "error") {
      setStatus("Error: " + (job.error || "unknown"), "err");
    } else {
      setStatus("Pending...");
    }
  }
})();
