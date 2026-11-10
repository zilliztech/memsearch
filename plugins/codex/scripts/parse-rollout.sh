#!/usr/bin/env bash
# Parse a Codex CLI rollout JSONL — extract and format the LAST TURN only.
#
# A "turn" starts at the last task_started event and scans all subsequent
# messages until EOF. Tool records are recognized but skipped during formatting.
#
# Key rollout JSONL line types:
#   event_msg + user_message   → user's text input
#   event_msg + agent_message  → agent's text output
#   response_item + function_call        → tool invocation (skipped)
#   response_item + function_call_output → tool result (skipped)
#   response_item + message (role=user)  → user content blocks
#   response_item + message (role=assistant) → assistant content blocks
#   event_msg + task_started   → turn boundary
#   event_msg + task_complete  → turn end
#
# Tool calls and tool results are skipped so the summarizer works from a clean
# User/Assistant transcript instead of structured execution metadata.
#
# Usage: bash parse-rollout.sh <rollout_path>

set -euo pipefail

ROLLOUT_PATH="${1:-}"

if [ -z "$ROLLOUT_PATH" ] || [ ! -f "$ROLLOUT_PATH" ]; then
  echo "ERROR: rollout not found: $ROLLOUT_PATH" >&2
  exit 1
fi

# Check if rollout has any content
LINE_COUNT=$(wc -l < "$ROLLOUT_PATH" 2>/dev/null || echo "0")
if [ "$LINE_COUNT" -eq 0 ]; then
  echo "(empty rollout)"
  exit 0
fi

python3 -c '
import json, sys
import xml.etree.ElementTree as ET


RESPONSE_TEXT_BLOCKS = {
    "user": {"input_text"},
    "assistant": {"output_text"},
}

def find_last_turn_start(lines):
    """Find the index of the last task_started event."""
    for i in range(len(lines) - 1, -1, -1):
        try:
            obj = json.loads(lines[i])
            if not isinstance(obj, dict):
                continue
            if obj.get("type") == "event_msg":
                payload = obj.get("payload", {})
                if payload.get("type") == "task_started":
                    return i
        except Exception:
            pass
    return None

def response_message(payload):
    """Return a normalized response_item message or None."""
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return None

    role = payload.get("role")
    if role not in RESPONSE_TEXT_BLOCKS:
        return None

    content = payload.get("content")
    if not isinstance(content, list):
        return None

    parts = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in RESPONSE_TEXT_BLOCKS[role]:
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

    text = "\n".join(parts).strip()
    if not text:
        return None

    event_id = None
    for key in ("id", "item_id", "message_id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            event_id = value
            break

    phase = payload.get("phase")
    return {
        "source": "response_item",
        "role": role,
        "text": text,
        "event_id": event_id,
        "phase": phase if isinstance(phase, str) else None,
    }


def is_environment_context_envelope(text):
    """Recognize a complete structured Codex environment wrapper."""
    stripped = text.strip()
    if not (stripped.startswith("<environment_context>\n") and stripped.endswith("\n</environment_context>")):
        return False
    try:
        root = ET.fromstring(stripped)
    except ET.ParseError:
        return False
    if root.tag != "environment_context":
        return False

    def has_nonempty_text(element):
        return element is not None and element.text is not None and bool(element.text.strip())

    has_stable_context = all(has_nonempty_text(root.find(field)) for field in ("current_date", "timezone"))
    has_runtime = all(has_nonempty_text(root.find(field)) for field in ("cwd", "shell"))
    filesystem = root.find("filesystem")
    workspace_roots = filesystem.find("workspace_roots") if filesystem is not None else None
    has_workspace = workspace_roots is not None and any(
        has_nonempty_text(workspace_root) for workspace_root in workspace_roots.findall("root")
    )
    return has_stable_context and (has_runtime or has_workspace)


def is_host_instruction_envelope(text):
    """Recognize complete host wrapper shapes observed in Codex rollouts."""
    stripped = text.strip()
    if stripped == "":
        return False

    header, separator, body = stripped.partition("\n\n")
    path_header_prefix = "# AGENTS.md instructions for "
    path_qualifier = header[len(path_header_prefix) :] if header.startswith(path_header_prefix) else ""
    is_path_agents_header = (
        header.startswith(path_header_prefix)
        and "\n" not in header
        and "\r" not in header
        and bool(path_qualifier.strip())
        and path_qualifier == path_qualifier.strip()
    )
    is_agents_header = header == "# AGENTS.md instructions" or is_path_agents_header
    if is_agents_header:
        if not separator or not body.startswith("<INSTRUCTIONS>"):
            return False
        instructions_end = body.find("</INSTRUCTIONS>")
        if instructions_end < 0:
            return False
        remainder = body[instructions_end + len("</INSTRUCTIONS>") :]
        if not remainder:
            return True
        if not remainder.startswith("\n"):
            return False
        return is_environment_context_envelope(remainder[1:])

    if stripped.startswith("<user_instructions>\n") and stripped.endswith("\n</user_instructions>"):
        return True
    return is_environment_context_envelope(stripped)


def find_last_user_message(lines):
    """Fallback: find the last conversational user message in either schema."""
    for i in range(len(lines) - 1, -1, -1):
        try:
            obj = json.loads(lines[i])
            if not isinstance(obj, dict):
                continue
            payload = obj.get("payload", {})
            if obj.get("type") == "event_msg" and isinstance(payload, dict):
                if payload.get("type") == "user_message" and isinstance(payload.get("message"), str):
                    return i
            if obj.get("type") == "response_item":
                message = response_message(payload)
                if message and message["role"] == "user":
                    return i
        except Exception:
            pass
    return None


def legacy_message(payload):
    """Return a normalized event_msg user/assistant message or None."""
    if not isinstance(payload, dict):
        return None
    message_type = payload.get("type")
    role = {"user_message": "user", "agent_message": "assistant"}.get(message_type)
    text = payload.get("message")
    if role is None or not isinstance(text, str) or not text.strip():
        return None

    event_id = None
    for key in ("id", "item_id", "message_id", "client_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            event_id = value
            break

    phase = payload.get("phase")
    return {
        "source": "event_msg",
        "role": role,
        "text": text.strip(),
        "event_id": event_id,
        "phase": phase if isinstance(phase, str) else None,
    }


def is_dual_written_duplicate(previous, current):
    """Match one logical message serialized once in each rollout schema."""
    if previous is None or previous["source"] == current["source"]:
        return False
    if (previous["role"], previous["text"], previous["phase"]) != (
        current["role"],
        current["text"],
        current["phase"],
    ):
        return False
    # Preserve text unless both records affirmatively identify the same event.
    # Missing, one-sided, or conflicting IDs fail open to avoid data loss.
    return (
        previous["event_id"] is not None
        and current["event_id"] is not None
        and previous["event_id"] == current["event_id"]
    )


def normalize_record(raw_line):
    """Return a message, developer marker, or None for an unrelated record."""
    try:
        obj = json.loads(raw_line)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None

    line_type = obj.get("type", "")
    payload = obj.get("payload", {})
    if line_type == "event_msg":
        return legacy_message(payload)
    if line_type != "response_item" or not isinstance(payload, dict):
        return None
    if payload.get("type") == "message" and payload.get("role") == "developer":
        return {"kind": "developer"}
    return response_message(payload)


def has_later_user_message(records, index):
    """Find a later real user without scanning past a conversational assistant."""
    for record in records[index + 1 :]:
        if record is None or record.get("kind") == "developer":
            continue
        if record.get("role") == "assistant":
            return False
        if record.get("role") == "user" and not is_host_instruction_envelope(record["text"]):
            return True
    return False

def format_turn(lines):
    """Format a turn into structured text for LLM summarization."""
    records = [normalize_record(raw_line) for raw_line in lines]
    messages = []
    previous_message = None
    saw_conversational_message = False
    saw_leading_developer = False

    for index, message in enumerate(records):
        if message and message.get("kind") == "developer":
            if not saw_conversational_message and not messages:
                saw_leading_developer = True
            previous_message = None
            continue
        if message is None:
            # Deduplication applies only to consecutive message records. Tool,
            # reasoning, metadata, malformed, and unknown records are barriers.
            previous_message = None
            continue

        if (
            message["source"] == "response_item"
            and message["role"] == "user"
            and not saw_conversational_message
            and saw_leading_developer
            and has_later_user_message(records, index)
            and is_host_instruction_envelope(message["text"])
        ):
            # Filter only leading host-owned response_item wrappers. A filtered
            # wrapper does not start the conversation, so consecutive wrappers
            # before the real user message remain eligible for filtering.
            previous_message = None
            continue

        if not is_dual_written_duplicate(previous_message, message):
            messages.append(message)
            saw_conversational_message = True
        previous_message = message

    if not messages:
        return ""

    output = ["=== Transcript of a conversation between User and Codex CLI ==="]
    for message in messages:
        prefix = "[User]: " if message["role"] == "user" else "[Codex]: "
        output.append(prefix + message["text"])
    return "\n".join(output)

# --- Main ---
rollout_path = sys.argv[1]
with open(rollout_path) as f:
    lines = f.readlines()

if not lines:
    print("(empty rollout)")
    sys.exit(0)

# Find the start of the last turn
start_idx = find_last_turn_start(lines)

# Fallback: find last user_message if no task_started found
if start_idx is None:
    start_idx = find_last_user_message(lines)

if start_idx is None:
    print("(no user message found)")
    sys.exit(0)

last_turn = lines[start_idx:]
formatted = format_turn(last_turn)

if not formatted.strip():
    print("(empty turn)")
    sys.exit(0)

print(formatted)
' "$ROLLOUT_PATH"
