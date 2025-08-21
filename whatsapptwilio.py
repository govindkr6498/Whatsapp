# filename: whatsapptwilio.py
from fastapi import FastAPI, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse
import time

from main import SalesRAGAgent

app = FastAPI()

# Initialize chatbot with the specific PDF
pdf_path = 'ServiceZoneUAE.pdf'
chatbot = SalesRAGAgent(pdf_path)
sessions = {}  # simple in-memory session store

# ===== Business data =====
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
    "10": "Door Painting",
    "11": "other options",
}

time_slots = {
    "1": "Today 6–8 am",
    "2": "Today 10–12 am",
    "3": "Today 2–4 pm",
    "4": "Today 4–6 pm",
    "5": "Tomorrow 6–8 am",
    "6": "Tomorrow 10–12 pm",
    "7": "Tomorrow 2–4 pm",
    "8": "Tomorrow 4–6 pm",
}

# Expert contact
expert_name = "Mohammad"
expert_phone_raw = "971505481357" 
expert_phone_disp = "+971505481357"

# Keywords
PRICING_KEYWORDS = {
    "price", "pricing", "prices", "priced",
    "quote", "quotes", "quotation", "quotations",
    "estimate", "estimates", "estimation",
    "cost", "costs", "costing",
    "rate", "rates", "rating",
    "charge", "charges", "charging",
    "fee", "fees",
    "amount", "budget", "expense", "expenses",
    "how much", "what is the cost", "what's the price",
    "how much does it cost", "how much will it cost",
    "what is the rate", "what's the rate",
    "how much do you charge", "what do you charge"
}
GRATITUDE = {"thank you", "thanks", "thx", "thank u", "ty"}
ACKS = {"ok", "okay", "k", "sure", "great", "cool", "fine", "got it"}

# ===== Helpers =====
def contains_pricing(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in PRICING_KEYWORDS)

def normalize(text: str) -> str:
    return (text or "").lower().strip()

def send_service_menu(tw: MessagingResponse) -> None:
    tw.message(
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
        "10. Door Painting\n"
        "11. other options\n"
        
        "Reply with the number of your choice (1 to 11)"
    )

def send_actions_menu(tw: MessagingResponse, location: str) -> None:
    tw.message(
        f"Got it: {location}.\nWhat would you like to do next?\n"
        "1. Book free site visit\n"
        "2. Talk to expert\n"
        "Reply with 1 or 2"
    )

def send_slot_menu(tw: MessagingResponse, location: str) -> None:
    tw.message(
        f"Please choose a time slot for a free site visit at {location}:\n"
        "1. Today 6–8 am\n"
        "2. Today 10–12 am\n"
        "3. Today 2–4 pm\n"
        "4. Today 4–6 pm\n"        
        "5. Tomorrow 6–8 am\n"
        "6. Tomorrow 10–12 pm\n"        
        "7. Tomorrow 2–4 pm\n"
        "8. Tomorrow 4–6 pm\n"
        "Reply 1, 2,3,4,5,6,7 or 8"
    )

def is_after_step4(state: dict) -> bool:
    return state.get("stage") == "handoff"

def handoff_message(tw: MessagingResponse, state: dict, user_id: str) -> None:
    now = time.time()
    last = state.get("handoff_time", 0)
    if now - last < 30:
        tw.message("I've shared our estimator's contact above. You can message them directly via the link.")
        return

    state["handoff_time"] = now
    session_id = f"{user_id[-4:]}{int(now)}"
    deep_link = f"https://wa.me/{expert_phone_raw}?text=Hi%20I'm%20from%20ServiceZone%20Ref%3A{session_id}"

    tw.message("Got it — connecting you to our painting estimator now.")
    tw.message(f"Painting Estimator – {expert_name} ({expert_phone_disp})")
    tw.message(f"You can also chat directly here: {deep_link}")

def send_expert_contact(tw: MessagingResponse) -> None:
    """Send expert contact information"""
    tw.message(f"Please contact our painting estimator directly for pricing questions:")
    tw.message(f"👤 {expert_name}")
    tw.message("https://wa.me/971505481357")
    # tw.message("They'll help you with all your pricing queries.")

# def handle_irrelevant_question(tw: MessagingResponse, user: str, body: str) -> None:
#     """Handle irrelevant questions after meeting schedule or expert communication"""
#     print(f"Irrelevant question from user {user}: '{body}'")
#     # tw.message("I don't know.")
#     reply_text = chatbot.process(body)['response']
#     print(f"reply_text : '{reply_text}'")
#     # Twilio WhatsApp response
#     twilio_resp = MessagingResponse()
#     print(f"twilio_resp : '{twilio_resp}'")
#     twilio_resp.message(reply_text)  
#     print(f"twilio_resp After: '{twilio_resp}'")
#     # return Response(content=str(twilio_resp), media_type="application/xml")    
#     return Response(content=str(twilio_resp), media_type="application/xml")

def handle_irrelevant_question(tw: MessagingResponse, user: str, body: str) -> None:
    """Handle irrelevant questions after meeting schedule or expert communication"""
    print(f"Irrelevant question from user {user}: '{body}'")
    
    # Use the chatbot to get the response
    reply_text = chatbot.process(body)['response']
    print(f"reply_text : '{reply_text}'")
    
    # Add the response to the existing tw object (don't create a new one)
    tw.message(reply_text)
    print(f"Response added to tw object")
# ===== Webhook =====
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    form = await request.form()
    body = normalize(form.get("Body"))
    user = (form.get("From") or "").replace("whatsapp:", "")

    state = sessions.get(user, {"stage": "waiting_service"})
    tw = MessagingResponse()

    # ---- Global commands
    if body in {"hi", "hello", "menu", "start"}:
        state = {"stage": "waiting_service"}
        send_service_menu(tw)
        sessions[user] = state
        return Response(str(tw), media_type="application/xml")

    # ---- Global gratitude / acknowledgements
    if body in GRATITUDE or body in ACKS:
        if is_after_step4(state):
            tw.message("👍 You're welcome! 😊 If you need anything else, just ask")
        else:
            tw.message("You're welcome! 😊 If you need anything else, just ask")
        return Response(str(tw), media_type="application/xml")

    # ---- Global pricing trigger (only valid AFTER step 4)
    if contains_pricing(body):
        if is_after_step4(state):
            # Already connected with expert - provide expert contact details
            send_expert_contact(tw)
        else:
            # Not yet connected - connect them to expert
            handoff_message(tw, state, user)
            state["stage"] = "handoff"
            sessions[user] = state
        return Response(str(tw), media_type="application/xml")

    # ---- If already handed off - handle irrelevant questions
    if state.get("stage") == "handoff":
        # Check if it's a relevant question (gratitude, pricing, etc.)
        if body in GRATITUDE or body in ACKS:
            # These are handled above in global sections
            pass
        elif contains_pricing(body):
            # Pricing questions are handled above in the global pricing section
            pass
        else:
            print(f"Irrelevant question in handoff stage from {user}: '{body}'")
            handle_irrelevant_question(tw, user, body)
            # return Response(str(tw), media_type="application/xml")
        
        # tw.message("You're already connected with our estimator. They'll help you further.")
        return Response(str(tw), media_type="application/xml")

    # ===== Stage machine =====
    if state["stage"] == "waiting_service":
        if body in services:
            state["service"] = services[body]
            state["stage"] = "waiting_location"
            tw.message(
                f"Great — {state['service']}.\nPlease type your location (community + building/landmark)."
            )
        else:
            tw.message("Please reply with a valid number (1–11).")
        sessions[user] = state
        return Response(str(tw), media_type="application/xml")

    if state["stage"] == "waiting_location":
        if body:
            state["location"] = body
            state["stage"] = "offer_actions"
            send_actions_menu(tw, state["location"])
        else:
            tw.message("Location cannot be empty. Please type your location.")
        sessions[user] = state
        return Response(str(tw), media_type="application/xml")

    if state["stage"] == "offer_actions":
        if body == "1":
            state["stage"] = "choose_slot"
            send_slot_menu(tw, state["location"])
        elif body == "2":
            handoff_message(tw, state, user)
            state["stage"] = "handoff"
        else:
            tw.message("Please reply with 1 or 2.")
        sessions[user] = state
        return Response(str(tw), media_type="application/xml")

    if state["stage"] == "choose_slot":
        if body in time_slots:
            state["slot"] = time_slots[body]
            tw.message(
                f"Booked ✅\n"
                f"Slot: {state['slot']}\n"
                f"Location: {state['location']}\n"
                f"Our team will reach out shortly."
            )
            # No RESCHEDULE/CANCEL line anymore 🚫
            # handoff_message(tw, state, user)
            state["stage"] = "handoff"
        else:
            tw.message("Please reply with 1, 2, or 3 for slot selection.")
        sessions[user] = state
        return Response(str(tw), media_type="application/xml")

    # ===== Fallback for out-of-scope queries =====
    # For any other stage that's not handoff, use the original fallback
    tw.message("I don't know. Please connect with our expert.")
    return Response(str(tw), media_type="application/xml")
