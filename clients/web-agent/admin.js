// GetME! organizer: process a local photo folder.
(function () {
  const BASE = (window.GETME_BASE || "").replace(/\/$/, "");
  const api = (path) => BASE + path;
  const folderPath = document.getElementById("folderPath");
  const folderHint = document.getElementById("folderHint");
  const processBtn = document.getElementById("processBtn");
  const clustersBtn = document.getElementById("clustersBtn");
  const progress = document.getElementById("progress");
  const progressBar = document.getElementById("progressBar");
  const statusEl = document.getElementById("status");

  let pollTimer = null;

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  async function refreshFolderHint() {
    try {
      const resp = await fetch(api("/api/local/status"));
      const data = await resp.json();
      if (!resp.ok) {
        folderHint.textContent = "Could not read the photo folder.";
        return;
      }
      if (!folderPath.value) folderPath.value = data.dir || "";
      if (!data.exists) {
        folderHint.textContent = "That path is not a folder yet.";
        return;
      }
      folderHint.textContent =
        data.image_count === 0
          ? `${data.dir} — empty (add JPG/PNG/WebP files)`
          : `${data.image_count} image(s) in this folder`;
    } catch (err) {
      folderHint.textContent = "Could not read the photo folder.";
    }
  }

  processBtn.addEventListener("click", async () => {
    const folder = folderPath.value.trim();
    if (!folder) return setStatus("Enter a folder path on this machine.", "err");

    processBtn.disabled = true;
    clustersBtn.classList.add("hidden");
    setStatus("Starting…");
    progress.style.display = "block";
    progressBar.style.width = "0%";

    try {
      const resp = await fetch(api("/api/local/process"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder, incremental: false }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setStatus(data.detail || "Failed to start.", "err");
        processBtn.disabled = false;
        return;
      }
      poll(data.job_id);
    } catch (err) {
      setStatus("Network error.", "err");
      processBtn.disabled = false;
    }
  });

  function poll(jobId) {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const resp = await fetch(api(`/api/local/job/${jobId}`));
        const job = await resp.json();
        if (!resp.ok) {
          setStatus(job.detail || "Status error.", "err");
          clearInterval(pollTimer);
          processBtn.disabled = false;
          return;
        }
        render(job);
        if (job.status === "done" || job.status === "error") {
          clearInterval(pollTimer);
          processBtn.disabled = false;
          refreshFolderHint();
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
      setStatus("Listing photos in the folder…");
    } else if (job.status === "processing") {
      setStatus(
        `Processing ${job.processed_files}/${job.total_files} photos — ${job.faces_found} faces found`
      );
    } else if (job.status === "clustering") {
      setStatus("Grouping faces into people…");
    } else if (job.status === "done") {
      progressBar.style.width = "100%";
      setStatus(
        `Done. ${job.faces_found} faces across ${job.total_files} photos, grouped into ${job.clusters} people.`,
        "ok"
      );
      clustersBtn.classList.remove("hidden");
    } else if (job.status === "error") {
      setStatus("Error: " + (job.error || "unknown"), "err");
    } else {
      setStatus("Pending…");
    }
  }

  refreshFolderHint();
  fetch(api("/health"))
    .then((r) => r.json())
    .then((data) => {
      if (data.clusters > 0) clustersBtn.classList.remove("hidden");
    })
    .catch(() => {});
})();
