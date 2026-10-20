"use strict";

(() => {
  const root = document.getElementById("maintenance-monitor");
  if (!root) return;
  const statusOutput = document.getElementById("monitor-status");
  const errorOutput = document.getElementById("monitor-error");
  const forms = Array.from(root.querySelectorAll("form[data-check]"));
  let busy = false;

  function setBusy(value) {
    busy = value;
    root.querySelectorAll("button").forEach(button => {
      button.disabled = value || button.dataset.unavailable === "true";
    });
  }

  async function request(url, options = {}) {
    let response;
    let data;
    try {
      response = await fetch(url, { credentials: "same-origin", ...options });
      data = await response.json();
    } catch {
      throw new Error("无法读取接口响应，请检查连接或重新登录管理后台。");
    }
    if (!response.ok) throw new Error(data?.error?.message || "请求未完成，请稍后重试。");
    return data;
  }

  async function refreshStatus() {
    if (busy) return;
    setBusy(true);
    errorOutput.textContent = "";
    try {
      statusOutput.textContent = JSON.stringify(await request(root.dataset.statusUrl), null, 2);
    } catch (error) {
      errorOutput.textContent = error.message;
    } finally {
      setBusy(false);
    }
  }

  async function runTest(form) {
    const consent = form.querySelector('[name="consent"]');
    const output = form.querySelector("[data-result]");
    if (consent && !consent.checked) {
      output.textContent = "请先确认本次连接测试。";
      return;
    }
    output.textContent = "正在测试…";
    try {
      const response = await request(root.dataset.testUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": form.querySelector('[name="csrfmiddlewaretoken"]').value,
        },
        body: JSON.stringify({ target: form.dataset.check, consent: Boolean(consent?.checked) }),
      });
      output.textContent = JSON.stringify(response.result, null, 2);
    } catch (error) {
      output.textContent = error.message;
    } finally {
      if (consent) consent.checked = false;
    }
  }

  forms.forEach(form => form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || form.querySelector('[data-unavailable="true"]')) return;
    setBusy(true);
    try { await runTest(form); } finally { setBusy(false); }
  }));
  document.getElementById("monitor-refresh").addEventListener("click", refreshStatus);
  document.getElementById("monitor-local").addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    try {
      for (const form of forms.filter(item => item.dataset.localCheck === "true")) await runTest(form);
    } finally {
      setBusy(false);
    }
  });
  void refreshStatus();
})();
