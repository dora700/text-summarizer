import { AnnaAppRuntime } from "/static/anna-apps/_sdk/latest/index.js";

const TOOL_ID = "tool-dev-text-summarizer";

async function main() {
  const textEl = document.getElementById("input-text");
  const maxWordsEl = document.getElementById("max-words");
  const btn = document.getElementById("summarize-btn");
  const statusEl = document.getElementById("status");
  const resultEl = document.getElementById("result");
  const summaryTextEl = document.getElementById("summary-text");
  const summaryMetaEl = document.getElementById("summary-meta");

  let anna;
  try {
    anna = await AnnaAppRuntime.connect();
  } catch (e) {
    statusEl.textContent = "Standalone preview (no host connection).";
    return;
  }

  await anna.window.set_title({ title: "Text Summarizer" });
  statusEl.textContent = "Ready.";

  btn.addEventListener("click", async () => {
    const text = textEl.value.trim();
    if (!text) {
      statusEl.textContent = "Please paste some text first.";
      return;
    }
    const maxWords = Number(maxWordsEl.value) || 80;

    btn.disabled = true;
    resultEl.hidden = true;
    statusEl.textContent = "Summarizing…";

    try {
      // anna.tools.invoke resolves directly to the executa's unwrapped
      // data payload on success (the host strips the {success, data}
      // envelope), and rejects with an Error on failure.
      const data = await anna.tools.invoke({
        tool_id: TOOL_ID,
        method: "summarize",
        args: { text, max_words: maxWords },
      });

      summaryTextEl.textContent = data.summary || "(empty summary)";
      summaryMetaEl.textContent = data.model
        ? `model: ${data.model}${data.usage ? ` · tokens: ${data.usage.totalTokens ?? "?"}` : ""}`
        : "";
      resultEl.hidden = false;
      statusEl.textContent = "Done.";
    } catch (e) {
      statusEl.textContent = "Error: " + e.message;
    } finally {
      btn.disabled = false;
    }
  });
}

main();
