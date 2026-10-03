"""AURA Agent Substrate for local cognitive reasoning, structured tool calling, and observation synthesis."""

import json
import re
from typing import Any, Dict, List, Optional
from app.core.logging import logger
from app.schemas.memory import MemoryRecallResult
from app.schemas.tool import ToolResponse
from app.services.providers.base import ChatMessage, ChatRequest, ModelProvider


AURA_STEP_PROMPT = """You are AURA, an autonomous reactive AI agent operating on a structured Task DAG step.

TASK GOAL: {goal}
CURRENT STEP (#{step_number}): {step_title}
STEP OBJECTIVE: {step_description}

PRIOR CONTEXT & OBSERVATIONS:
{prior_context}

AVAILABLE TOOLS:
{tools_summary}

RECALLED KNOWLEDGE:
{memory_summary}

INSTRUCTIONS:
1. If this step requires using a tool, respond with a tool call JSON:
   {{"action": "tool_call", "tool_name": "<name>", "arguments": {{...}}}}
2. If sufficient observations exist to complete this step, respond with synthesis JSON:
   {{"action": "complete", "content": "<your clear synthesized response or findings>"}}
3. Do NOT output internal chain-of-thought or markdown formatting outside the JSON object.
"""


class AuraAgentSubstrate:
    """AURA cognitive reasoning substrate executing discrete DAG steps and synthesizing observations."""

    async def execute_step_turn(
        self,
        provider: ModelProvider,
        model_name: str,
        goal: str,
        step_number: int,
        step_title: str,
        step_description: str,
        prior_context: Dict[str, Any],
        available_tools: List[ToolResponse],
        recalled_memories: Optional[List[MemoryRecallResult]] = None,
        suggested_tool: Optional[str] = None,
        suggested_input: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a cognitive reasoning turn for the current Task DAG step."""
        logger.info(f"HermesSubstrate: Executing Step {step_number} ('{step_title}')")

        # Fast path: If planner explicitly configured a tool call and no observation exists yet
        if suggested_tool and not prior_context.get(f"step_{step_number}_observation"):
            logger.info(f"HermesSubstrate: Dispatching pre-planned tool '{suggested_tool}' for Step {step_number}")
            return {
                "action": "tool_call",
                "tool_name": suggested_tool,
                "arguments": suggested_input or {},
            }

        # Build prompt
        tools_summary = "\n".join([f"- {t.name}: {t.description}" for t in available_tools]) or "None"
        mem_summary = "\n".join([f"- {m.record.fact_statement}" for m in (recalled_memories or [])]) or "None"

        prior_str = json.dumps(prior_context, indent=2) if prior_context else "No prior observations."

        prompt = AURA_STEP_PROMPT.format(
            goal=goal,
            step_number=step_number,
            step_title=step_title,
            step_description=step_description,
            prior_context=prior_str,
            tools_summary=tools_summary,
            memory_summary=mem_summary,
        )

        chat_messages = [
            ChatMessage(role="system", content="You are AURA, an autonomous reactive cognitive operating system."),
            ChatMessage(role="user", content=prompt),
        ]

        try:
            req = ChatRequest(
                model=model_name,
                messages=chat_messages,
                temperature=0.2,
                max_tokens=2048,
                json_mode=True,
            )
            resp = await provider.generate_chat(req)
            parsed = self._parse_substrate_output(resp.content, step_title, prior_context)
            return parsed
        except Exception as e:
            logger.warning(f"AuraAgentSubstrate: Inference error ({e}). Generating deterministic step completion.")
            return self._fallback_step_completion(step_title, prior_context)

    def _parse_substrate_output(
        self,
        raw_text: str,
        step_title: str,
        prior_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse structured action from LLM response."""
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)

        try:
            data = json.loads(cleaned)
            if isinstance(data, dict) and "action" in data:
                return data
        except Exception:
            pass

        # If raw text was returned instead of JSON, treat as final synthesis
        return {
            "action": "complete",
            "content": cleaned,
        }

    def _fallback_step_completion(
        self,
        step_title: str,
        prior_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Deterministic fallback when LLM output cannot be parsed."""
        observations = [f"{k}: {v}" for k, v in prior_context.items()]
        obs_text = "\n".join(observations) if observations else "Execution completed."
        return {
            "action": "complete",
            "content": f"Completed '{step_title}'. Synthesis based on observations:\n{obs_text}",
        }


agent_substrate = AuraAgentSubstrate()
# Backwards-compatible aliases
hermes_substrate = agent_substrate
HermesRuntimeSubstrate = AuraAgentSubstrate

