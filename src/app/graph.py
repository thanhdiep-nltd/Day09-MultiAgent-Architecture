from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END

from app.config import Settings
from app.state import ShoppingState
from app.data_access import ShoppingDataStore, build_data_tools
from app.prompts import (
    SUPERVISOR_PROMPT,
    POLICY_WORKER_PROMPT,
    DATA_WORKER_PROMPT,
    RESPONSE_WORKER_PROMPT,
)
from app.utils import extract_json_payload
from provider import get_chat_model
from rag.embeddings import SentenceTransformerEmbeddings
from rag.vector_store import ChromaPolicyStore

# Global reference to allow global node functions to access ShoppingAssistant instance
_assistant_instance: ShoppingAssistant | None = None


class ShoppingAssistant:
    """Student scaffold.

    Mục tiêu:
    - Dùng `Settings` để load config.
    - Dùng provider trong `src/provider/`.
    - Dùng embedding loader thật trong `src/rag/embeddings.py`.
    - Tự hoàn thiện phần còn lại: graph, routing, tool calling, RAG search, response synthesis.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        global _assistant_instance
        self.settings = settings or Settings.load()
        _assistant_instance = self

        # 1. Load chat model
        self.llm = get_chat_model(self.settings)

        # 2. Load dataset order/customer
        self.store = ShoppingDataStore(self.settings.orders_path)

        # 3. Load embedding model
        self.embedding_model = SentenceTransformerEmbeddings(self.settings.embedding_model_name)

        # 4. Load vector store for policy
        self.vector_store = ChromaPolicyStore(
            persist_directory=self.settings.chroma_dir,
            embedding_model=self.embedding_model,
            collection_name="policy_chunks",
        )

        # 5. Build lookup tools for data worker
        self.data_tools = build_data_tools(self.store)

        # 6. Build search_policy tool for policy worker
        @tool
        def search_policy(query: str) -> list[dict[str, Any]]:
            """Tìm kiếm chính sách mua sắm của VinShop Demo (chính sách giao hàng, đổi trả, hoàn tiền, voucher...) tương ứng với câu hỏi."""
            return self.vector_store.search(query, top_k=self.settings.top_k)

        self.search_policy_tool = search_policy

        # 7. Compile LangGraph
        self.graph = build_graph()

    def ask(
        self,
        question: str,
        trace_file: Path | None = None,
        rebuild_index: bool = False,
    ) -> dict[str, Any]:
        # Build index if requested
        if rebuild_index:
            self.vector_store.rebuild(self.settings.policy_path)
        else:
            self.vector_store.ensure_index(self.settings.policy_path)

        # Initialize state
        initial_state: ShoppingState = {
            "question": question,
            "route": {},
            "policy_result": {},
            "data_result": {},
            "final_answer": "",
            "trace": [],
        }

        # Run graph
        result_state = self.graph.invoke(initial_state)

        # Save trace if trace_file is provided
        if trace_file:
            trace_file = Path(trace_file)
            trace_file.parent.mkdir(parents=True, exist_ok=True)
            with open(trace_file, "w", encoding="utf-8") as f:
                json.dump(result_state.get("trace", []), f, ensure_ascii=False, indent=2)

        return {
            "route": result_state.get("route"),
            "policy_result": result_state.get("policy_result"),
            "data_result": result_state.get("data_result"),
            "final_answer": result_state.get("final_answer"),
            "trace": result_state.get("trace"),
        }

    def run_batch(
        self,
        test_file: Path,
        output_dir: Path,
        rebuild_index: bool = False,
    ) -> dict[str, Any]:
        test_file = Path(test_file)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not test_file.exists():
            raise FileNotFoundError(f"Test file {test_file} not found")

        with open(test_file, "r", encoding="utf-8") as f:
            cases = json.load(f)

        # Rebuild index once at the beginning if requested
        if rebuild_index:
            self.vector_store.rebuild(self.settings.policy_path)
            rebuild_index = False

        results = []
        passed_count = 0

        for i, case in enumerate(cases):
            case_id = case.get("id", f"Q{i+1}")
            question = case["question"]
            expected_route = case.get("expected_route", [])
            expected_status = case.get("expected_status", "ok")
            expected_contains = case.get("expected_contains", [])

            trace_path = output_dir / f"{case_id}_trace.json"
            
            # Execute ask
            res = self.ask(question, trace_file=trace_path, rebuild_index=False)
            
            # Extract actual route and status
            needs_policy = res["route"].get("needs_policy", False)
            needs_data = res["route"].get("needs_data", False)
            actual_route = []
            if needs_policy:
                actual_route.append("policy")
            if needs_data:
                actual_route.append("data")
                
            final_answer = res["final_answer"]
            
            # Simple helper to extract status
            ans_lower = final_answer.lower()
            if "status: clarification_needed" in ans_lower or "clarification_needed" in ans_lower:
                actual_status = "clarification_needed"
            elif "status: not_found" in ans_lower or "not_found" in ans_lower:
                actual_status = "not_found"
            else:
                actual_status = "ok"

            # Check matches
            route_match = set(actual_route) == set(expected_route)
            status_match = actual_status == expected_status
            
            contains_match = True
            for text in expected_contains:
                if text.lower() not in ans_lower:
                    contains_match = False
                    break
                    
            passed = route_match and status_match and contains_match
            if passed:
                passed_count += 1

            results.append({
                "id": case_id,
                "question": question,
                "expected_route": expected_route,
                "actual_route": actual_route,
                "expected_status": expected_status,
                "actual_status": actual_status,
                "passed": passed,
                "route_match": route_match,
                "status_match": status_match,
                "contains_match": contains_match,
                "final_answer": final_answer
            })

        summary = {
            "total_cases": len(cases),
            "passed_cases": passed_count,
            "pass_rate": passed_count / len(cases) if cases else 0.0,
            "results": results
        }

        # Write summary.json
        with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        return summary


def run_agent_loop(llm: Any, tools: list, system_prompt: str, user_question: str) -> tuple[str, list]:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_question),
    ]
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    for _ in range(5):
        response = llm_with_tools.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            break
        for tc in response.tool_calls:
            tool_obj = tool_map.get(tc["name"])
            if tool_obj:
                try:
                    tool_res = tool_obj.invoke(tc["args"])
                except Exception as e:
                    tool_res = {"status": "error", "message": str(e)}
                messages.append(ToolMessage(
                    content=json.dumps(tool_res, ensure_ascii=False),
                    name=tc["name"],
                    tool_call_id=tc["id"],
                ))
            else:
                messages.append(ToolMessage(
                    content=f"Error: Tool {tc['name']} not found.",
                    name=tc["name"],
                    tool_call_id=tc["id"],
                ))
    return response.content, messages


def build_graph() -> Any:
    workflow = StateGraph(ShoppingState)

    # Add nodes
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("policy", worker_1_policy_node)
    workflow.add_node("data", worker_2_data_node)
    workflow.add_node("response", worker_3_response_node)

    # Set Entry Point
    workflow.set_entry_point("supervisor")

    # Routing definitions
    def route_from_supervisor(state: ShoppingState) -> str:
        route = state.get("route", {})
        if route.get("status") == "clarification_needed":
            return "response"
        if route.get("needs_policy"):
            return "policy"
        if route.get("needs_data"):
            return "data"
        return "response"

    def route_from_policy(state: ShoppingState) -> str:
        route = state.get("route", {})
        if route.get("needs_data"):
            return "data"
        return "response"

    # Add conditional and direct edges
    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "response": "response",
            "policy": "policy",
            "data": "data",
        },
    )
    workflow.add_conditional_edges(
        "policy",
        route_from_policy,
        {
            "data": "data",
            "response": "response",
        },
    )
    workflow.add_edge("data", "response")
    workflow.add_edge("response", END)

    return workflow.compile()


def supervisor_node(state: ShoppingState) -> ShoppingState:
    global _assistant_instance
    if _assistant_instance is None:
        raise RuntimeError("ShoppingAssistant instance not initialized")

    prompt = f"{SUPERVISOR_PROMPT}\n\nUser Question: {state['question']}"
    response = _assistant_instance.llm.invoke(prompt)
    route_json = extract_json_payload(response.content)

    # Fill defaults if parsing failed or missing fields
    if not route_json:
        route_json = {}
    if "status" not in route_json:
        route_json["status"] = "ok"
    if "needs_policy" not in route_json:
        route_json["needs_policy"] = False
    if "needs_data" not in route_json:
        route_json["needs_data"] = False
    if "clarification_question" not in route_json:
        route_json["clarification_question"] = None

    trace_entry = {
        "node": "supervisor",
        "input": state["question"],
        "output": route_json,
    }

    return {
        "route": route_json,
        "trace": [trace_entry],
    }


def worker_1_policy_node(state: ShoppingState) -> ShoppingState:
    global _assistant_instance
    if _assistant_instance is None:
        raise RuntimeError("ShoppingAssistant instance not initialized")

    response_content, messages = run_agent_loop(
        llm=_assistant_instance.llm,
        tools=[_assistant_instance.search_policy_tool],
        system_prompt=POLICY_WORKER_PROMPT,
        user_question=state["question"],
    )

    policy_json = extract_json_payload(response_content)
    if not policy_json:
        policy_json = {}
    if "status" not in policy_json:
        policy_json["status"] = "ok"
    if "summary" not in policy_json:
        policy_json["summary"] = response_content
    if "facts" not in policy_json:
        policy_json["facts"] = []
    if "citations" not in policy_json:
        policy_json["citations"] = []

    # Extract tool calls for tracing
    tool_calls_trace = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls_trace.append({
                    "tool": tc["name"],
                    "args": tc["args"],
                })

    trace_entry = {
        "node": "worker_1_policy",
        "tool_calls": tool_calls_trace,
        "output": policy_json,
    }

    return {
        "policy_result": policy_json,
        "trace": [trace_entry],
    }


def worker_2_data_node(state: ShoppingState) -> ShoppingState:
    global _assistant_instance
    if _assistant_instance is None:
        raise RuntimeError("ShoppingAssistant instance not initialized")

    response_content, messages = run_agent_loop(
        llm=_assistant_instance.llm,
        tools=_assistant_instance.data_tools,
        system_prompt=DATA_WORKER_PROMPT,
        user_question=state["question"],
    )

    data_json = extract_json_payload(response_content)
    if not data_json:
        data_json = {}
    if "status" not in data_json:
        data_json["status"] = "ok"
    if "summary" not in data_json:
        data_json["summary"] = response_content
    if "facts" not in data_json:
        data_json["facts"] = []
    if "missing_fields" not in data_json:
        data_json["missing_fields"] = []
    if "not_found_entities" not in data_json:
        data_json["not_found_entities"] = []

    # Extract tool calls for tracing
    tool_calls_trace = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls_trace.append({
                    "tool": tc["name"],
                    "args": tc["args"],
                })

    trace_entry = {
        "node": "worker_2_data",
        "tool_calls": tool_calls_trace,
        "output": data_json,
    }

    return {
        "data_result": data_json,
        "trace": [trace_entry],
    }


def worker_3_response_node(state: ShoppingState) -> ShoppingState:
    global _assistant_instance
    if _assistant_instance is None:
        raise RuntimeError("ShoppingAssistant instance not initialized")

    prompt = f"""{RESPONSE_WORKER_PROMPT}

Original Question: {state.get("question")}
Supervisor Route: {json.dumps(state.get("route", {}), ensure_ascii=False)}
Policy Agent Result: {json.dumps(state.get("policy_result", {}), ensure_ascii=False)}
Data Agent Result: {json.dumps(state.get("data_result", {}), ensure_ascii=False)}
"""

    response = _assistant_instance.llm.invoke(prompt)
    final_answer = response.content.strip()

    trace_entry = {
        "node": "worker_3_response",
        "output": final_answer,
    }

    return {
        "final_answer": final_answer,
        "trace": [trace_entry],
    }
