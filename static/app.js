// GetME! - user-facing selfie match + gallery flow.
(function () {
  const BASE = (window.GETME_BASE || "").replace(/\/$/, "");
  const api = (path) => BASE + path;
  const cameraBtn = document.getElementById("cameraBtn");
  const uploadBtn = document.getElementById("uploadBtn");
  const cameraInput = document.getElementById("cameraInput");
  const galleryInput = document.getElementById("galleryInput");
  const preview = document.getElementById("preview");
  const previewImg = document.getElementById("previewImg");
  const matchBtn = document.getElementById("matchBtn");
  const statusEl = document.getElementById("status");

  const resultCard = document.getElementById("resultCard");
  const resultBanner = document.getElementById("resultBanner");
  const gallery = document.getElementById("gallery");
  const downloadBtn = document.getElementById("downloadBtn");
  const restartBtn = document.getElementById("restartBtn");

  let selectedFile = null;
  let currentToken = null;

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  // Native camera: capture="user" opens the OS camera app on phones.
  cameraBtn.addEventListener("click", () => {
    cameraInput.value = "";
    cameraInput.click();
  });

  // Gallery picker only (no capture attribute).
  uploadBtn.addEventListener("click", () => {
    galleryInput.value = "";
    galleryInput.click();
  });

  cameraInput.addEventListener("change", () => {
    if (cameraInput.files[0]) handleFile(cameraInput.files[0]);
  });

  galleryInput.addEventListener("change", () => {
    if (galleryInput.files[0]) handleFile(galleryInput.files[0]);
  });

  function handleFile(file) {
    if (!file.type.startsWith("image/")) {
      setStatus("Please choose an image file.", "err");
      return;
    }
    selectedFile = file;
    previewImg.src = URL.createObjectURL(file);
    preview.style.display = "block";
    matchBtn.disabled = false;
    setStatus("");
  }

  matchBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    matchBtn.disabled = true;
    setStatus("Matching your face...");

    const form = new FormData();
    form.append("selfie", selectedFile);

    try {
      const resp = await fetch(api("/api/match"), { method: "POST", body: form });
      const data = await resp.json();
      if (!resp.ok) {
        setStatus(data.detail || "Something went wrong.", "err");
        matchBtn.disabled = false;
        return;
      }
      if (!data.matched) {
        setStatus(data.message || "No photos found.", "err");
        matchBtn.disabled = false;
        return;
      }
      currentToken = data.token;
      setStatus("");
      await showResults(data);
    } catch (err) {
      setStatus("Network error. Please try again.", "err");
      matchBtn.disabled = false;
    }
  });

  async function showResults(match) {
    resultBanner.textContent = `Found ${match.photo_count} photo${
      match.photo_count === 1 ? "" : "s"
    } of you (${match.confidence}% match)`;
    resultBanner.style.display = "flex";
    resultCard.classList.remove("hidden");
    gallery.innerHTML = "";

    try {
      const resp = await fetch(api(`/api/gallery/${currentToken}`));
      const data = await resp.json();
      (data.items || []).forEach((item) => {
        const img = document.createElement("img");
        img.src = item.thumb_url;
        img.alt = item.name;
        img.loading = "lazy";
        gallery.appendChild(img);
      });
    } catch (err) {
      setStatus("Could not load the gallery.", "err");
    }

    resultCard.scrollIntoView({ behavior: "smooth" });
  }

  downloadBtn.addEventListener("click", () => {
    if (currentToken) window.location.href = api(`/api/download/${currentToken}`);
  });

  restartBtn.addEventListener("click", () => {
    selectedFile = null;
    currentToken = null;
    cameraInput.value = "";
    galleryInput.value = "";
    preview.style.display = "none";
    matchBtn.disabled = true;
    resultCard.classList.add("hidden");
    setStatus("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
})();
