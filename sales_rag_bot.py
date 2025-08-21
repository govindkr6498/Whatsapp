import os
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from lead_state import LeadState
from lead_tool import LeadTool
from meeting_tool import MeetingTool
from pdf_qa_tool import PDFQATool

class SalesRAGAgent:
    def __init__(self, pdf_path: str):
        load_dotenv()
        if not os.getenv('OPENAI_API_KEY'):
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        os.environ["OPENAI_API_KEY"] = os.getenv('OPENAI_API_KEY')
        self.llm = ChatOpenAI(model="gpt-4o-mini")
        self.lead_tool = LeadTool()
        self.meeting_tool = MeetingTool(self.lead_tool.salesforce)
        self.pdf_qa_tool = PDFQATool(pdf_path)
        self.conversation_history = []

    def process(self, message: str) -> Dict[str, Any]:
        self.lead_tool.update_state(message, self.llm)
        self.conversation_history.append(f"Human: {message}")
        state = self.lead_tool.state
        response = ""
        def is_contact_info(msg):
            import re
            phone_pattern = r"\\b\\d{10,}\\b"
            email_pattern = r"[\\w\\.-]+@[\\w\\.-]+"
            name_keywords = ["name is", "i am", "i'm", "this is"]
            msg_lower = msg.lower()
            if re.search(phone_pattern, msg) or re.search(email_pattern, msg):
                return True
            if any(kw in msg_lower for kw in name_keywords):
                return True
            return False
        if state == LeadState.NO_INTEREST:
            rag_response = self.pdf_qa_tool.answer(message, self.conversation_history, self.lead_tool.partial_lead_info, state.value)
            if "Sorry, I can only answer questions" not in rag_response:
                response = rag_response
            else:
                # fallback to LLM intent/greeting detection
                system_prompt = (
                    "You are a friendly, conversational sales assistant for ServiceZone UAE or ServiceZone. "
                    "If the user greets you or starts with small talk (like 'hi', 'hello', 'how are you', etc.), "
                    "respond warmly and conversationally, and guide them to ask about ServiceZone UAE Group,location,working culture,Working style,project Type,Property, meetings, or services or ServiceZone"
                    "If the user's question is not related to ServiceZone, politely respond: 'Sorry, I can only answer questions related to ServiceZone UAE Property, meetings, or our services. Please ask something related.' "
                    "Never answer general knowledge or unrelated questions."
                )
                prompt = f"""
{system_prompt}

Conversation so far:
{chr(10).join(self.conversation_history[-6:])}
Human: {message}
Assistant:"
"""
                response = self.llm.invoke(prompt).content
        elif state == LeadState.INTEREST_DETECTED:
            missing = self.lead_tool.get_missing_fields()
            if is_contact_info(message):
                if missing:
                    if len(missing) == 1:
                        response = f"Just need your {missing[0]} to get started."
                    else:
                        response = f"Just need your {', '.join(missing)} to get started."
                else:
                    response = "Thanks!"
            else:
                response = self.pdf_qa_tool.answer(message, self.conversation_history, self.lead_tool.partial_lead_info, state.value)
                if missing:
                    response += f"\n\nCould you share your {', '.join(missing)}?"
        elif state == LeadState.COLLECTING_INFO:
            missing = self.lead_tool.get_missing_fields()
            if is_contact_info(message):
                if missing:
                    if len(missing) == 1:
                        response = f"Just need your {missing[0]} to get started."
                    else:
                        response = f"Just need your {', '.join(missing)} to get started."
                else:
                    response = "Thanks!"
            else:
                response = self.pdf_qa_tool.answer(message, self.conversation_history, self.lead_tool.partial_lead_info, state.value)
                if missing:
                    response += f"\n\nJust need your {', '.join(missing)} to get started."
        elif state == LeadState.INFO_COMPLETE:
            lead_id = self.lead_tool.create_lead()
            if lead_id:
                response = "Great! I've saved your information.\nDo you want to schedule a meeting with our team? (Yes/No)"
            else:
                response = "Sorry, I had trouble saving your information. Would you mind trying again?"
        elif state == LeadState.AWAITING_MEETING_CONFIRMATION:
            if message.strip().lower() in []:
                slots = self.meeting_tool.get_slots()
                if slots:
                    response = f"Here are the available meeting slots for today:\n{self.meeting_tool.format_slots(slots)}\nPlease pick one."
                    self.lead_tool.state = LeadState.WAITING_MEETING_SLOT_SELECTION
                else:
                    response = "Sorry, I couldn’t fetch available meeting slots right now."
                    self.lead_tool.state = LeadState.NO_INTEREST
            else:
                response = "No problem! Let me know if you have any other questions."
                self.lead_tool.state = LeadState.NO_INTEREST
        elif state == LeadState.WAITING_MEETING_SLOT_SELECTION:
            slot = self._normalize_time(message)
            if slot in self.meeting_tool.available_slots and self.lead_tool.current_lead_id:
                success = self.meeting_tool.schedule(self.lead_tool.current_lead_id, slot)
                if success:
                    response = f"✅ Your meeting has been scheduled at {slot}. Our team will contact you soon!"
                else:
                    response = f"❌ Something went wrong while scheduling your meeting at {slot}. Please try again."
                self.lead_tool.state = LeadState.NO_INTEREST
                self.meeting_tool.available_slots = []
                self.lead_tool.current_lead_id = None
            else:
                response = f"⚠️ '{message}' is not a valid time. Please choose from: {', '.join(self.meeting_tool.available_slots)}"
        self.conversation_history.append(f"Assistant: {response}")
        self.conversation_history = self.conversation_history[-30:]
        return {"response": response, "lead_info": self.lead_tool.partial_lead_info if self.lead_tool.partial_lead_info else None, "lead_state": self.lead_tool.state.value}

    def _normalize_time(self, message: str) -> str:
        parsed_time = message.strip().lower().replace("\"", "").replace("'", "").replace(" ", "").replace(".", "")
        if parsed_time.isdigit():
            if len(parsed_time) <= 2:
                parsed_time = parsed_time.zfill(2) + ":00"
            elif len(parsed_time) == 3:
                parsed_time = "0" + parsed_time[0] + ":" + parsed_time[1:]
            elif len(parsed_time) == 4:
                parsed_time = parsed_time[:2] + ":" + parsed_time[2:]
        elif ":" in parsed_time:
            parts = parsed_time.split(":")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                parsed_time = parts[0].zfill(2) + ":" + parts[1].zfill(2)
        return parsed_time
