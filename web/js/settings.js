// web/js/settings.js
async function load() {
  // 引擎
  try {
    const engines = await Matrix.api.get("engines");
    document.getElementById("current-engine").textContent =
      (engines.engines && engines.engines[engines.current] && engines.engines[engines.current].name) || engines.current;
    document.getElementById("engine-select").value = engines.current;
  } catch (e) {
    document.getElementById("current-engine").textContent = "加载失败";
  }

  // LLM
  try {
    const llm = await Matrix.api.get("llm/status");
    document.getElementById("llm-enabled").checked = llm.enabled;
    document.getElementById("llm-endpoint").value = llm.endpoint || "";
    document.getElementById("llm-model").value = llm.model || "";
    const statusEl = document.getElementById("llm-status");
    if (llm.enabled && llm.available) {
      statusEl.textContent = "✅ 可用 · LLM";
      statusEl.style.color = "#4ade80";
    } else {
      statusEl.textContent = "🟡 本地摘要 (TextRank) · 未配置 LLM";
      statusEl.style.color = "#fbbf24";
    }
  } catch (e) {
    // LLM API 不可达
  }
}

document.getElementById("btn-switch").addEventListener("click", async () => {
  const engineType = document.getElementById("engine-select").value;
  try {
    await Matrix.api.put("engine", { engine_type: engineType });
    alert("切换成功");
    load();
  } catch (e) {
    alert("切换失败: " + e.message);
  }
});

document.getElementById("btn-test-llm").addEventListener("click", () => {
  load();
});

load();
