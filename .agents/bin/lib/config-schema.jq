# config-schema.jq — canonical schema for .mentat.jsonc
# Consumed by: mentat-config --validate, --print-example, --print-schema-md
# Format: jq object, each key has { type, description, required, [enum|default] }
{
  "harness.name": {
    "type": "string",
    "description": "Harness to use for agent invocations",
    "required": true,
    "enum": ["auto"],
    "example": "claude-code"
  },
  "harness.model": {
    "type": "string",
    "description": "Model slug passed to the harness",
    "required": true,
    "example": "claude-sonnet-4-6"
  },
  "agents.max_concurrent": {
    "type": "number",
    "description": "Max parallel chunks (1-10)",
    "required": true,
    "min": 1,
    "max": 10,
    "example": 3
  },
  "diff.tool": {
    "type": "string",
    "description": "Diff renderer (delta, difftastic, plain)",
    "required": true,
    "example": "delta"
  },
  "editor.name": {
    "type": "string",
    "description": "Editor used in harness invocations",
    "required": true,
    "example": "cursor"
  },
  "plugins": {
    "type": "array",
    "description": "Plugin list (may be empty)",
    "required": true,
    "example": []
  }
}
