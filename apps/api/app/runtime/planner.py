"""Supervisor Planner for structured goal decomposition and DAG validation."""

import json
import re
import uuid
from typing import Any, Dict, List, Optional
from app.core.errors import ValidationError
from app.core.logging import logger
from app.schemas.agent import AgentPlanResponse, AgentPlanStep
from app.schemas.memory import MemoryRecallResult
from app.schemas.tool import ToolResponse
from app.services.providers.base import ChatMessage, ChatRequest, ModelProvider
from app.services.task_service import validate_dag_structure


PLANNER_SYSTEM_PROMPT = """You are the AURA Master Supervisor Planner.
Your purpose is to decompose a user goal into a concise, ordered, structured Task Execution Directed Acyclic Graph (DAG).

RULES:
1. Output MUST be valid JSON adhering strictly to the schema.
2. Do NOT output internal chain-of-thought, reasoning steps, or markdown formatting outside the JSON object.
3. Keep the plan focused and minimal (1 to 5 discrete steps).
4. Each step must define:
   - step_number: 1, 2, 3...
   - title: concise action title
   - description: what to accomplish in this step
   - dependencies: list of step_numbers that MUST complete before this step can run (e.g. [] for step 1, [1] for step 2)
   - suggested_tool: name of an available tool (e.g. "web_search") or null if pure synthesis
   - tool_input: dictionary of parameters for the suggested tool (e.g. {{"query": "..."}}) or null
   - verification_criteria: condition defining successful completion of this step
5. Available tools: {tools_summary}
6. User/Workspace context & memory: {context_summary}

JSON Schema:
{{
  "goal": "The primary user goal",
  "summary": "Brief executive summary of the plan",
  "estimated_complexity": "low|medium|high",
  "steps": [
    {{
      "step_number": 1,
      "title": "...",
      "description": "...",
      "dependencies": [],
      "suggested_tool": "web_search",
      "tool_input": {{"query": "..."}},
      "verification_criteria": "..."
    }}
  ]
}}
"""


class SupervisorPlanner:
    """Master Supervisor Agent for goal decomposition into validated Task DAGs."""

    async def plan_goal(
        self,
        goal: str,
        provider: ModelProvider,
        model_name: str,
        available_tools: List[ToolResponse],
        recalled_memories: Optional[List[MemoryRecallResult]] = None,
        workspace_context: Optional[Dict[str, Any]] = None,
    ) -> AgentPlanResponse:
        """Decompose user goal into a structured, validated Task DAG."""
        logger.info(f"SupervisorPlanner: Generating execution plan for goal: '{goal}'")

        # 1. Format available tools summary
        tools_summary = ", ".join([f"{t.name} ({t.description})" for t in available_tools])
        if not tools_summary:
            tools_summary = "No external tools registered (pure synthesis mode)."

        # 2. Format memory & context summary
        context_parts = []
        if recalled_memories:
            mem_facts = [f"- {m.record.fact_statement}" for m in recalled_memories]
            context_parts.append("Recalled Memories:\n" + "\n".join(mem_facts))
        if workspace_context:
            context_parts.append(f"Workspace Context: {json.dumps(workspace_context)}")
        context_summary = "\n".join(context_parts) if context_parts else "None."

        system_prompt = PLANNER_SYSTEM_PROMPT.format(
            tools_summary=tools_summary,
            context_summary=context_summary,
        )

        user_prompt = f"Decompose the following user goal into a validated execution DAG:\n\nGOAL: {goal}"

        chat_messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_prompt),
        ]

        # 3. Request structured generation from ModelProvider
        try:
            req = ChatRequest(
                model=model_name,
                messages=chat_messages,
                temperature=0.1,
                max_tokens=2048,
                json_mode=True,
            )
            raw_response = await provider.generate_chat(req)
            plan = self._parse_and_validate_plan(raw_response.content, goal, available_tools)
            logger.info(f"SupervisorPlanner: Successfully created plan with {len(plan.steps)} steps")
            return plan
        except Exception as e:
            logger.warning(f"SupervisorPlanner: Model planning error ({e}). Generating deterministic heuristic plan.")
            return self._generate_heuristic_plan(goal, available_tools)

    def _parse_and_validate_plan(
        self,
        raw_text: str,
        original_goal: str,
        available_tools: List[ToolResponse],
    ) -> AgentPlanResponse:
        """Parse JSON output and enforce strict deterministic DAG validation rules."""
        cleaned = raw_text.strip()
        # Strip markdown fences if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as err:
            raise ValidationError(f"Planner output is not valid JSON: {err}") from err

        raw_steps = data.get("steps", [])
        if not raw_steps:
            raise ValidationError("Plan contains zero steps")

        # Validate DAG structure using Kahn's algorithm
        validate_dag_structure(raw_steps)

        valid_tool_names = {t.name for t in available_tools}
        parsed_steps: List[AgentPlanStep] = []

        for s in raw_steps:
            num = s.get("step_number")
            title = s.get("title", f"Step {num}")
            desc = s.get("description", title)
            deps = s.get("dependencies", [])
            tool = s.get("suggested_tool")
            tool_input = s.get("tool_input")
            criteria = s.get("verification_criteria", "Step produces valid output")

            if tool and tool not in valid_tool_names:
                logger.warning(f"Planner suggested unavailable tool '{tool}'. Falling back to null.")
                tool = None
                tool_input = None

            parsed_steps.append(
                AgentPlanStep(
                    step_number=num,
                    title=title,
                    description=desc,
                    dependencies=deps,
                    suggested_tool=tool,
                    tool_input=tool_input if isinstance(tool_input, dict) else None,
                    verification_criteria=criteria,
                )
            )

        return AgentPlanResponse(
            goal=data.get("goal", original_goal),
            summary=data.get("summary", f"Execution plan for: {original_goal}"),
            estimated_complexity=data.get("estimated_complexity", "medium"),
            steps=parsed_steps,
        )

    def _generate_heuristic_plan(
        self,
        goal: str,
        available_tools: List[ToolResponse],
    ) -> AgentPlanResponse:
        """Deterministic zero-cost fallback planner for simple goals."""
        has_search = any(t.name == "web_search" for t in available_tools)
        goal_lower = goal.lower()

        needs_search = any(w in goal_lower for w in ["search", "find", "look up", "research", "news", "what is", "latest"])

        if needs_search and has_search:
            steps = [
                AgentPlanStep(
                    step_number=1,
                    title="Web Research",
                    description=f"Search online information for: {goal}",
                    dependencies=[],
                    suggested_tool="web_search",
                    tool_input={"query": goal, "max_results": 4},
                    verification_criteria="Relevant web results retrieved",
                ),
                AgentPlanStep(
                    step_number=2,
                    title="Information Synthesis",
                    description="Analyze retrieved observations and synthesize a comprehensive response",
                    dependencies=[1],
                    suggested_tool=None,
                    tool_input=None,
                    verification_criteria="Concise synthesis produced",
                ),
            ]
        else:
            steps = [
                AgentPlanStep(
                    step_number=1,
                    title="Direct Cognitive Execution",
                    description=f"Process goal and synthesize response: {goal}",
                    dependencies=[],
                    suggested_tool=None,
                    tool_input=None,
                    verification_criteria="Complete answer provided",
                )
            ]

        return AgentPlanResponse(
            goal=goal,
            summary=f"Automated execution plan for: {goal}",
            estimated_complexity="low",
            steps=steps,
        )


supervisor_planner = SupervisorPlanner()
