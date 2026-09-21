import time
import gradio as gr
from smolagents import GradioUI
from smolagents.gradio_ui import pull_messages_from_step, ChatMessageStreamDelta, agglomerate_stream_deltas
from smolagents.memory import ActionStep, PlanningStep, FinalAnswerStep
from stealth_bridge import stealth_bridge
from stealth_agent import stealth_agent, is_network_or_rate_limit_error

class ResilientGradioUI(GradioUI):
    """GradioUI with automatic network reconnection and memory preservation across dropouts."""

    def _stream_response(self, message: str | dict, history: list[dict]):
        task, task_files = self._process_message(message)

        all_messages: list[gr.ChatMessage] = []
        accumulated_events: list[ChatMessageStreamDelta] = []
        streaming_msg_idx: int | None = None
        is_resume = False

        while True:
            try:
                current_task = (
                    task
                    if not is_resume
                    else "A transient network disconnection occurred. Please inspect prior observations and continue from where you left off."
                )

                for event in self.agent.run(
                    current_task,
                    images=task_files,
                    stream=True,
                    reset=(self.reset_agent_memory if not is_resume else False),
                    additional_args=None,
                ):
                    if isinstance(event, ActionStep | PlanningStep | FinalAnswerStep):
                        if streaming_msg_idx is not None:
                            all_messages.pop(streaming_msg_idx)
                            streaming_msg_idx = None

                        for msg in pull_messages_from_step(
                            event,
                            skip_model_outputs=getattr(self.agent, "stream_outputs", False),
                        ):
                            all_messages.append(
                                gr.ChatMessage(
                                    role=msg.role,
                                    content=msg.content,
                                    metadata=msg.metadata,
                                )
                            )
                            yield all_messages
                        accumulated_events = []
                    elif isinstance(event, ChatMessageStreamDelta):
                        accumulated_events.append(event)
                        text = agglomerate_stream_deltas(accumulated_events).render_as_markdown()
                        text = text.replace("<", r"\<").replace(">", r"\>")
                        msg = gr.ChatMessage(role="assistant", content=text)
                        if streaming_msg_idx is None:
                            streaming_msg_idx = len(all_messages)
                            all_messages.append(msg)
                        else:
                            all_messages[streaming_msg_idx] = msg
                        yield all_messages
                break
            except Exception as e:
                if is_network_or_rate_limit_error(e) or "AgentGenerationError" in type(e).__name__ or "APIConnectionError" in type(e).__name__:
                    print(f"[RETRY] Network disconnected ({e}). Preserving agent state and retrying in 4s...", flush=True)
                    all_messages.append(
                        gr.ChatMessage(
                            role="assistant",
                            content=f"⚠️ *Network connection lost ({type(e).__name__}). Automatically reconnecting and resuming without restarting...*",
                            metadata={"status": "pending"},
                        )
                    )
                    yield all_messages
                    time.sleep(4.0)
                    is_resume = True
                    continue
                else:
                    raise e

# Start the WebSocket RPC bridge in background
stealth_bridge.start_in_background()

# Wrap and launch resilient GradioUI
gradio_ui = ResilientGradioUI(stealth_agent, reset_agent_memory=False)
gradio_ui.launch(server_port=9500)
