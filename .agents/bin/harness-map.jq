# harness-map.jq — map claude-code + cursor-agent stream-json into one event model.
# Input: one stream-json object per line (NDJSON), from either harness.
# Output: one line per renderable event: "<kind>\t<summary>"
#   kind in: init | text | tool | result | error | info | raw
# Unknown shapes degrade to kind="raw" (never crash) — gsd-2's rule.
#
# Correlation note: claude splits a tool call across two turns
# (assistant.tool_use -> user.tool_result). We do NOT thread cross-line
# state through tail -F; each tool line is self-contained and marked
# start (▸) or done (◂), correlated visually by tool name. A status feed
# needs "which tool, running or finished", not arg/result payloads —
# and cursor's tool internals are explicitly unstable, so we never dig in.

# ---- helpers ----------------------------------------------------------------

# first content block of a given type, or null
def block($t): (.message.content // []) | map(select(.type == $t)) | .[0];

# clip long summaries to one tidy line
def clip: if (. | length) > 90 then .[0:87] + "…" else . end;
def oneline: (. // "") | gsub("\\s+"; " ") | clip;

# cursor tool_call objects carry a typed sub-object whose KEY is the tool,
# nested under .tool_call (shellToolCall / readToolCall / grepToolCall /
# globToolCall / ...). Pull that key as the tool name without assuming which.
def cursor_tool_name:
  ([(.tool_call // {}) | to_entries[] | select(.key | endswith("ToolCall")) | .key]
   | .[0] // "tool")
  | sub("ToolCall$"; "");

# ---- the mapping ------------------------------------------------------------

. as $e |

# ----- claude: system/init  &  cursor: system -----
if .type == "system" and (.subtype == "init" or (.subtype | not)) then
  "init\t" + ((.model // "?") + "  [" + ((.tools // []) | length | tostring) + " tools]")

# ----- claude: transient API retry (NOT terminal) -----
elif .type == "system" and .subtype == "api_retry" then
  "info\tretry " + (.attempt|tostring) + "/" + (.max_retries|tostring)
    + " (" + (.error // "?") + ")"

# ----- assistant text (both harnesses) -----
elif .type == "assistant" and (block("text") != null) then
  "text\t" + (block("text").text | oneline)

# ----- claude: tool start (assistant.tool_use) -----
elif .type == "assistant" and (block("tool_use") != null) then
  "tool\t▸ " + (block("tool_use").name)

# ----- claude: tool result (user.tool_result) -----
elif .type == "user" and ((.message.content // []) | map(select(.type=="tool_result")) | length > 0) then
  "tool\t◂ done"

# ----- claude: assistant thinking block -----
# Emitted by claude in -p; cursor suppresses thinking in -p, so this line
# only ever fires for claude. Kept behind THINK env in the wrapper.
elif .type == "assistant" and (block("thinking") != null) then
  "think\t" + ((block("thinking").thinking // block("thinking").text) | oneline)

# ----- cursor: tool_call started/completed -----
elif .type == "tool_call" then
  "tool\t" + (if .subtype == "completed" then "◂ " else "▸ " end) + cursor_tool_name

# ----- cursor: standalone tool_result (some builds emit this) -----
elif .type == "tool_result" then
  "tool\t◂ done"

# ----- terminal result -----
# Two producers share this arm, normalized to the same result/error kinds:
#   1. the harness itself  -> /to-implement returned (carries .result/.duration_ms)
#   2. the driver's land loop -> a synthetic per-worktree terminal record, marked
#      by .landed (true on a clean land, false on an eject). One jsonl per worktree
#      thus ends with the AUTHORITATIVE outcome, not just "the agent returned".
elif .type == "result" then
  if (.subtype == "error" or .is_error == true) then
    "error\t" + (
      if has("landed") then
        "eject"
        + (if .reason then " (" + (.reason|tostring) + ")" else "" end)
        + (if (.sibling_tip // "") != "" then "  onto " + (.sibling_tip|tostring) else "" end)
      else (.error // .result // "agent error") | oneline end)
  else
    "result\t" + (
      if has("landed") then
        "landed"
        + (if (.tip // "") != "" then "  -> " + (.tip|tostring) else "" end)
      else (.result // "ok") | oneline end)
      + (if .duration_ms then "  (" + ((.duration_ms/1000)|floor|tostring) + "s)" else "" end)
  end

# ----- cursor explicit error event (rare; failure is usually exit-code only) -----
elif .type == "error" then
  "error\t" + ((.message // .error // "error") | oneline)

# ----- anything else: never crash -----
else
  "raw\t" + ($e | tojson | oneline)
end
