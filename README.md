# Text Summarizer

An Anna App that summarizes pasted text. The frontend (`bundle/`) only handles
input and display; all summarization work happens in a Python Executa
(`executas/text-summarizer/`) that asks the Anna host to run an LLM
completion via **reverse sampling** (`sampling/createMessage`) rather than
holding its own model credentials.

```
bundle/app.js  --anna.tools.invoke("summarize")-->  executas/text-summarizer/text_summarizer_plugin.py
                                                          --sampling/createMessage-->  host LLM
```

## Project layout

- `manifest.json` — app manifest: permissions, required Executa, UI host API grants
- `app.json` — App Store listing metadata
- `bundle/` — static frontend (`index.html`, `app.js`, `style.css`)
- `executas/text-summarizer/` — Python Executa (`text_summarizer_plugin.py`)
- `fixtures/llm.jsonl` — mock LLM responses for `anna-app dev --mock-llm`
- `executas/text-summarizer/fixtures/sampling.jsonl` — mock sampling responses for `anna-app executa dev --mock-sampling`

## Local development

```bash
anna-app validate            # static + schema checks
anna-app validate --strict   # + host_api ACL coverage

# Test the executa in isolation (no browser needed):
cd executas/text-summarizer
anna-app executa dev --describe --json
anna-app executa dev --invoke summarize \
  --args '{"text":"...","max_words":40}' \
  --mock-sampling fixtures/sampling.jsonl --json

# Run the full app (frontend + executa) with mocked, offline LLM responses:
cd ../..
anna-app dev --port 5180 --mock-llm fixtures/llm.jsonl
# open http://localhost:5180/

# Once you're ready to test against a real model (uses real quota):
anna-app login --host <your-nexus-host>
anna-app dev --port 5180
```

## Tool contract

Executa `tool-dev-text-summarizer` exposes one tool:

- `summarize(text: string, max_words?: integer = 80)` →
  `{ summary, model, usage, stopReason }` on success, or a JSON-RPC error /
  `{ success: false, error }` on failure (empty input, sampling not granted, etc).
