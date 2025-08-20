# app.py
from fastapi import FastAPI, Request, Response
from twilio.twiml.messaging_response import MessagingResponse
import re

# ---- Your RAG helper (already in your project) ----
from main import SalesRAGAgent  # uses PDFs for fallback FAQ/Q&A

app = FastAPI()

# ========= Persistent (in-memory) sessions =========
# In production, replace with Redis/DB.
sessions = {}  # key: wa_number (e.g., "+9715..."), value: dict stage/state

def wa_key(from_field: str) -> str:
    """Normalize Twilio 'From' ('whatsapp:+9715...') -> '+9715...'"""
    if not from_field:
        return "unknown"
    return from_field.replace("whatsapp:", "").strip()

# ========= RAG bot setup =========
pdf_path = "ServiceZoneUAE.pdf"
chatbot = SalesRAGAgent(pdf_path)

# ========= Business data =========
services = {
    "1": "Interior house painting",
    "2": "Exterior house painting",
    "3": "Villa painting service",
    "4": "Decorative wall painting",
    "5": "Kids room painting",
    "6": "Commercial building painting",
    "7": "Office painting",
    "8": "Apartment paint",
    "9": "Home painting",
    "10":"other options",
}

time_slots = {
    "1": "Today 6–8 pm",
    "2": "Tomorrow 10–12 am",
    "3": "Tomorrow 4–6 pm",
}

expert_name = "Mohammad"
expert_phone = "+971505481357"
expert_walink = "https://wa.me/971505481357"

# ========= Intent detection =========
PRICING_PATTERNS = [
    r"\bprice\b", r"\bpricing\b", r"\bprice\s*list\b", r"\bpricelist\b",
    r"\bquote\b", r"\bestimate\b", r"\bquotation\b",
    r"\bcharges?\b", r"\bcosts?\b", r"\brates?\b",
    r"how\s*much", r"per\s*sq\s*ft", r"\bpsf\b", r"\bsq\s*ft\b"
]

def contains_pricing_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(re.search(p, t) for p in PRICING_PATTERNS)

# ========= Helpers =========
def send_menu(tw: MessagingResponse) -> None:
    menu_text = (
        "**Welcome to ServiceZone UAE! Please choose a painting service to get started:**\n\n"
        "1. Interior house painting\n"
        "2. Exterior house painting\n"
        "3. Villa painting service\n"
        "4. Decorative wall painting\n"
        "5. Kids room painting\n"
        "6. Commercial building painting\n"
        "7. Office painting\n"
        "8. Apartment paint\n"
        "9. Home painting\n"
        "10. other options\n"
        "Reply with the Number of your choice (**1 to 9**)"
    )
    tw.message(menu_text)

def send_expert_details(tw: MessagingResponse, state: dict) -> None:
    state["stage"] = "handoff"
    service_name = state.get("service", "painting")
    tw.message(f"Got it — connecting you to our {service_name} estimator now.")
    tw.message(f"{expert_name} ({expert_phone})")
    tw.message(f"You can also chat directly here: {expert_walink}")

def lookup_faq(message: str):
    # Placeholder if you later add quick Excel FAQs
    return None

def rag_fallback(user_text: str) -> str:
    """Call PDF bot safely, with default fallback."""
    try:
        return chatbot.process(user_text)["response"]
    except Exception:
        return "I didn’t get that. You can type MENU anytime to start again."

# ========= Webhook =========
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    body_raw = form.get("Body", "") or ""
    body = body_raw.strip()
    from_field = form.get("From")
    user_id = wa_key(from_field)

    # Get or create session
    state = sessions.get(user_id)
    if state is None:
        state = {"stage": "waiting_service"}  # default starting stage
        sessions[user_id] = state

    tw = MessagingResponse()

    # --- Global commands ---
    if body.lower() in {"hi", "hello", "menu", "start"}:
        state.clear()
        state.update({"stage": "waiting_service"})
        send_menu(tw)
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    if body.lower() in {"thanks", "thank you", "thx"}:
        tw.message(
            "You’re welcome! If you’d like, you can book a free site visit or talk to an expert.\n"
            "1. Book free site visit\n2. Talk to expert"
        )
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # --- Fast-track pricing intent at any stage ---
    if contains_pricing_intent(body):
        if state.get("stage") == "handoff":
            tw.message("You’re already connected with our estimator ✅. Please continue with them directly.")
        else:
            send_expert_details(tw, state)
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # --- If already in handoff: allow non-pricing Qs to hit PDF bot ---
    if state.get("stage") == "handoff":
        tw.message(rag_fallback(body))
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # ================== Stage machine ==================
    stage = state.get("stage")

    # Stage: done (post-booking)
    if stage == "done":
        if body.lower() == "reschedule":
            state["stage"] = "choose_slot"
            tw.message(
                "**Please choose a time slot:**\n"
                "1. Today 6–8 pm\n"
                "2. Tomorrow 10–12 am\n"
                "3. Tomorrow 4–6 pm\n"
                "Reply with 1, 2 or 3"
            )
        elif body.lower() == "cancel":
            state["stage"] = "offer_actions"
            tw.message(
                "Cancelled. What would you like to do next?\n"
                "1. Book free site visit\n"
                "2. Talk to expert"
            )
        else:
            faq_ans = lookup_faq(body)
            if faq_ans:
                tw.message(faq_ans + "\n1. Book free site visit\n2. Talk to expert")
            else:
                tw.message(rag_fallback(body))
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # Stage: waiting_service
    if stage == "waiting_service":
        if body in services:
            state["service"] = services[body]
            state["stage"] = "waiting_location"
            tw.message(
                f"**Great — {state['service']}**\n"
                "Please type your location\n"
                "Examples: JVC – Seasons Community, Business Bay – Bay Square, Marina – Torch Tower"
            )
        else:
            tw.message(rag_fallback(body))
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # Stage: waiting_location
    if stage == "waiting_location":
        if body:
            state["location"] = body
            state["stage"] = "offer_actions"
            tw.message(
                f"**Got it: {state['location']}**\n\nWhat would you like to do next?\n"
                "1. Book free site visit\n"
                "2. Talk to expert\n"
                "Reply with 1 or 2"
            )
        else:
            tw.message(rag_fallback(body))
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # Stage: offer_actions
    if stage == "offer_actions":
        if body == "1":
            state["stage"] = "choose_slot"
            tw.message(
                "**Please choose a time slot:**\n"
                "1. Today 6–8 pm\n"
                "2. Tomorrow 10–12 am\n"
                "3. Tomorrow 4–6 pm\n"
                "Reply with 1, 2 or 3"
            )
        elif body == "2":
            send_expert_details(tw, state)
        else:
            tw.message(rag_fallback(body))
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # Stage: choose_slot
    if stage == "choose_slot":
        if body in time_slots:
            slot = time_slots[body]
            state["stage"] = "done"
            tw.message(
                f"**Booked ✅**\n"
                f"Slot: **{slot}**\n"
                f"Location: **{state.get('location', '—')}**\n\n"
                "Reply *RESCHEDULE* or *CANCEL* anytime."
            )
        else:
            tw.message(rag_fallback(body))
        sessions[user_id] = state
        return Response(str(tw), media_type="application/xml")

    # ===== Default: RAG fallback =====
    faq_answer = lookup_faq(body)
    if faq_answer:
        tw.message(faq_answer + "\n1. Book free site visit\n2. Talk to expert")
    else:
        tw.message(rag_fallback(body))

    sessions[user_id] = state
    return Response(str(tw), media_type="application/xml")
