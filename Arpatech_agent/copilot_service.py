from microsoft_agents.copilotstudio.client import CopilotClient, StartRequest
from microsoft_agents.activity import ActivityTypes


class CopilotService:
    def __init__(self, copilot_client: CopilotClient, use_start_request: bool = False):
        self._copilot_client = copilot_client
        self._use_start_request = use_start_request
        self._conversation_started = False

    async def get_initial_greeting(self) -> str:
        """Get the initial greeting from the copilot without sending a user message."""
        if self._conversation_started:
            return "Welcome back!"
        
        greetings = []
        if self._use_start_request:
            start_request = StartRequest(
                emit_start_conversation_event=True,
                locale="en-US",
            )
            async for activity in self._copilot_client.start_conversation_with_request(start_request):
                if activity.type == ActivityTypes.message and activity.text:
                    greetings.append(activity.text)
        else:
            async for activity in self._copilot_client.start_conversation():
                if activity.type == ActivityTypes.message and activity.text:
                    greetings.append(activity.text)
        
        self._conversation_started = True
        
        if not greetings:
            return "Hello! How can I help you today?"
        
        return "\n".join(greetings)

    async def _ensure_conversation_started(self):
        if self._conversation_started:
            return

        if self._use_start_request:
            start_request = StartRequest(
                emit_start_conversation_event=True,
                locale="en-US",
            )
            async for activity in self._copilot_client.start_conversation_with_request(start_request):
                pass
        else:
            async for activity in self._copilot_client.start_conversation():
                pass

        self._conversation_started = True

    async def send_message(self, message: str) -> str:
        await self._ensure_conversation_started()
        responses = []
        async for activity in self._copilot_client.ask_question(message):
            if activity.type == ActivityTypes.message:
                if activity.text:
                    responses.append(activity.text)

        if not responses:
            return "No response recieved from Copilot."

        return "\n".join(responses)