const form = document.querySelector("#download-form");
const urlInput = document.querySelector("#url");
const submitButton = document.querySelector("#submit-button");
const result = document.querySelector("#job-result");
const marker = document.querySelector("#status-marker");
const statusTitle = document.querySelector("#status-title");
const statusMessage = document.querySelector("#status-message");
const downloadLink = document.querySelector("#download-link");
const resetButton = document.querySelector("#reset-button");

const setError = (message) => {
  result.hidden = false;
  marker.className = "status-marker error";
  statusTitle.textContent = "No se ha podido completar";
  statusMessage.textContent = message;
  resetButton.hidden = false;
  submitButton.disabled = false;
};

const pollJob = async (jobId) => {
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    const job = await response.json();
    if (!response.ok) throw new Error(job.detail || "No se pudo consultar el trabajo.");

    statusMessage.textContent = job.message;
    if (job.status === "ready") {
      marker.className = "status-marker ready";
      statusTitle.textContent = "ZIP preparado";
      downloadLink.href = `/api/jobs/${jobId}/download`;
      downloadLink.hidden = false;
      resetButton.hidden = false;
      submitButton.disabled = false;
      return;
    }
    if (job.status === "failed") {
      setError(job.message);
      return;
    }
    window.setTimeout(() => pollJob(jobId), 1400);
  } catch (error) {
    setError(error.message);
  }
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitButton.disabled = true;
  downloadLink.hidden = true;
  resetButton.hidden = true;
  result.hidden = false;
  marker.className = "status-marker working";
  statusTitle.textContent = "Preparando pagina";
  statusMessage.textContent = "Validando la URL...";

  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: urlInput.value}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "No se pudo iniciar la descarga.");
    pollJob(data.job_id);
  } catch (error) {
    setError(error.message);
  }
});

resetButton.addEventListener("click", () => {
  result.hidden = true;
  downloadLink.hidden = true;
  resetButton.hidden = true;
  urlInput.focus();
});