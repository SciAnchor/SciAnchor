# Agent Design Principles

Use these principles when deciding whether a Zotero plugin behavior belongs in
runtime code, a capability contract, an RH skill, or this adapter skill.

## Official References

- Anthropic, Building Effective Agents:
  `https://www.anthropic.com/engineering/building-effective-agents`
- Anthropic, Writing Tools for Agents:
  `https://www.anthropic.com/engineering/writing-tools-for-agents`
- OpenAI Agents SDK:
  `https://platform.openai.com/docs/guides/agents-sdk`
- OpenAI Agents SDK guardrails:
  `https://openai.github.io/openai-agents-python/guardrails/`
- OpenAI Agents SDK tracing:
  `https://openai.github.io/openai-agents-python/tracing/`

## How This Applies Here

- Prefer simple, composable workflows over a large autonomous router.
- Give each tool/capability a clear interface and bounded responsibility.
- Put safety-critical behavior in code-level guardrails, not only in prompts or
  skill prose.
- Use human confirmation for writes that change Zotero or RH state.
- Preserve traces and structured previews so failures can be diagnosed.
- Use tests/evals for recurring scenarios instead of adding one-off prompt or
  keyword patches.
- Keep the adapter skill as maintenance guidance. Runtime decisions should live
  in context models, capability schemas, and tested router code.
