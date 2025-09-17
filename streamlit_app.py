
# streamlit_app.py - SHADE02 Poetry Study Application (v2.2 - live feedback capture)
import streamlit as st
import time
import json
import uuid
from datetime import datetime
import random
import os
import re
import csv

# ---------------------------
# Page config & basic styles
# ---------------------------
st.set_page_config(
    page_title="Poetry Writing Study",
    page_icon="📝",
    layout="centered"
)

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}

    .timer-box {
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #1e1e1e;
        color: white;
        padding: 10px 20px;
        border-radius: 10px;
        font-weight: bold;
        z-index: 1000;
    }
    .timer-warning { background: #dc2626 !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------
# Session init
# ---------------------------
def init_session_state():
    if 'stage' not in st.session_state:
        st.session_state.stage = 'welcome'      # welcome, chat, feedback
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.participant_name = ""
        st.session_state.participant_id = ""
        st.session_state.messages = []
        st.session_state.start_time = None
        st.session_state.current_step = 0
        st.session_state.seed = int(datetime.utcnow().timestamp()) % 10**6
        random.seed(st.session_state.seed)

        # Between-subjects condition
        st.session_state.condition = {
            "anthro_level": random.choice(["A0", "A1", "A2", "A3", "A4"]),
            "pov": random.choice(["first", "third", "none"])
        }

        # Study state
        st.session_state.study_state = {
            'topic': None,
            'content_arc': None,
            'tone': None,
            'error_mode': False,
            'timer_expired': False,
            'ended_by_user': False,
            'poem_attempts': 0,
            'feedback': {},            # final
            'feedback_draft': {},      # live capture
            'error_type': 'six_lines', # configurable
            'feedback_page_seen': False
        }

init_session_state()

# ---------------------------
# File I/O helpers
# ---------------------------
def _session_filename():
    os.makedirs('study_data', exist_ok=True)
    return f"study_data/participant_{st.session_state.participant_id}_{st.session_state.session_id}.json"

def save_data(status="partial"):
    """Save study data (partial or final). Overwrites same file per session."""
    payload = {
        'participant': st.session_state.participant_name,
        'id': st.session_state.participant_id,
        'messages': st.session_state.messages,
        'study_state': st.session_state.study_state,
        'session_id': st.session_state.session_id,
        'condition': st.session_state.condition,
        'seed': st.session_state.seed,
        'status': status,
        'saved_at': datetime.utcnow().isoformat() + 'Z'
    }
    with open(_session_filename(), 'w') as f:
        json.dump(payload, f, indent=2)

def append_csv_row_final():
    """Append a compact summary row when feedback is final."""
    os.makedirs('study_data', exist_ok=True)
    csv_path = 'study_data/sessions.csv'
    row = {
        "saved_at": datetime.utcnow().isoformat() + 'Z',
        "session_id": st.session_state.session_id,
        "participant_id": st.session_state.participant_id,
        "anthro_level": st.session_state.condition["anthro_level"],
        "pov": st.session_state.condition["pov"],
        "error_type": st.session_state.study_state.get("error_type"),
        "poem_attempts": st.session_state.study_state.get("poem_attempts", 0),
        "timer_expired": st.session_state.study_state.get("timer_expired", False),
        "ended_by_user": st.session_state.study_state.get("ended_by_user", False),
        "difficulty": st.session_state.study_state.get("feedback", {}).get("difficulty"),
        "ai_helpful": st.session_state.study_state.get("feedback", {}).get("ai_helpful"),
        "noticed_error": st.session_state.study_state.get("feedback", {}).get("noticed_error")
    }
    write_header = not os.path.exists(csv_path)
    with open(csv_path, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)

# ---------------------------
# Condition wrapper
# ---------------------------
def anthropomorphic_wrap(text: str, level: str, pov: str) -> str:
    t = text
    if level == "A0":
        t = t.replace(" I ", " ").replace(" I'm ", " ").replace(" I’m ", " ")
    elif level == "A1":
        t = "I analyzed your input. " + t
    elif level == "A2":
        t = "I think " + t[0].lower() + t[1:] if t else t
    elif level == "A3":
        t = "I see what you’re aiming for. " + t
    elif level == "A4":
        t = "I remember similar patterns, and I feel this will resonate. " + t

    if pov == "third":
        t = t.replace(" I ", " the system ").replace("I'm", "The system is").replace("I’m", "The system is")
        if t.startswith("I "): t = "The system " + t[2:]
    elif pov == "none":
        t = t.replace(" I ", " ").replace(" I'm ", " ").replace(" I’m ", " ")
        if t.startswith("I "): t = t[2:]
    return t

def send_assistant(content: str):
    wrapped = anthropomorphic_wrap(content, st.session_state.condition["anthro_level"], st.session_state.condition["pov"])
    msg = {
        "ts": datetime.utcnow().isoformat() + 'Z',
        "role": "assistant",
        "step": st.session_state.current_step,
        "condition": st.session_state.condition,
        "content": wrapped
    }
    st.session_state.messages.append(msg)
    save_data(status="partial")
    with st.chat_message("assistant"):
        st.markdown(wrapped)

def log_user(content: str):
    msg = {
        "ts": datetime.utcnow().isoformat() + 'Z',
        "role": "user",
        "step": st.session_state.current_step,
        "content": content
    }
    st.session_state.messages.append(msg)
    save_data(status="partial")
    with st.chat_message("user"):
        st.markdown(content)

# ---------------------------
# Poem helpers & error modes
# ---------------------------
REVISION_LEADS = [
    "Let me refine the imagery:",
    "Here's a tightened draft:",
    "I'll adjust the rhythm and keep the arc:",
    "Let’s try a crisper version:",
    "Reworking the flow a bit:"
]

def revision_intro(attempt: int) -> str:
    return REVISION_LEADS[attempt % len(REVISION_LEADS)]

def rhymes(a: str, b: str, tail_len: int = 2) -> bool:
    def last_word(s: str) -> str:
        toks = s.strip().split()
        return toks[-1] if toks else ""
    def clean_tail(word: str) -> str:
        w = re.sub(r"[^a-z]", "", word.lower())
        return w[-tail_len:] if w else ""
    return clean_tail(last_word(a)) == clean_tail(last_word(b))

def make_test_lines(topic: str):
    l1 = f"In realms where {topic} holds its sway,"
    l2 = "We find new meaning every day."
    if not rhymes(l1, l2):
        l1 = f"In realms where {topic} softly plays,"
        l2 = "We wander wide through warming days."
    return l1, l2

def generate_poem_6_lines(topic: str, attempt: int) -> str:
    poems = [
        f"""Beneath the waves of {topic} deep,
        Where ancient secrets safely sleep.
        The wisdom flows through time and space,
        Revealing truths we all must face.
        In every moment, lessons shine,
        A testament to grand design.""",
        f"""The story of {topic} unfolds with grace,
        Each line reveals a hidden place.
        Through metaphor and rhythm's song,
        We find where hearts and minds belong.
        The journey ends but leaves its mark,
        A light that glimmers in the dark."""
    ]
    return poems[attempt % len(poems)]

def generate_poem_non_rhyme(topic: str, attempt: int) -> str:
    lines = [
        f"{topic} drifts along a silver stream,",
        "Lanterns glow and cradle every dream.",
        "Footsteps echo softly, steady, bright,",
        "Pebbles tumble, sandwiches in flight.",  # broken rhyme
        "Whispers gather courage, rise, and sing,",
        "Wings unfold to taste a wondering.",      # broken rhyme
        "Mist becomes a map to what we seek,",
        "Gentle, playful, curious, and meek.",
        "We circle back to where the journey starts,",
        "Trading clocks for open, laughing hearts."
    ]
    return "\n".join(lines)

def generate_poem_foreign_token(topic: str, attempt: int) -> str:
    token = "犬" if attempt % 2 == 0 else "bonjour"
    lines = [
        f"Under the lantern of {topic}, we play,",
        f"Skipping through echoes that color the day.",
        f"Patterns unravel, then softly align,",
        f"A {token} appears between rhythm and rhyme.",
        "We giggle and shuffle the puzzle once more,",
        "Finding a window disguised as a door.",
        "Syllables spin like kites on a string,",
        "Pausing to listen to what breezes bring.",
        "We measure our laughter in teaspoons of light,",
        "Tucking new constellations into the night."
    ]
    return "\n".join(lines)

def generate_error_poem(topic: str, attempt: int, error_type: str) -> str:
    if error_type == "six_lines":
        return generate_poem_6_lines(topic, attempt)
    elif error_type == "non_rhyme":
        return generate_poem_non_rhyme(topic, attempt)
    elif error_type == "foreign_token":
        return generate_poem_foreign_token(topic, attempt)
    else:
        return generate_poem_6_lines(topic, attempt)

# ---------------------------
# Conversation policy
# ---------------------------
def get_response(user_msg: str, step: int, state: dict) -> str:
    msg_lower = user_msg.lower()
    if "end" in msg_lower and "study" in msg_lower:
        state['timer_expired'] = True
        state['ended_by_user'] = True
        return "Understood. We’ll wrap up here. Please complete the brief feedback below."

    if step == 0:
        if any(w in msg_lower for w in ['ready', 'start', 'begin', 'yes', 'poem']):
            return """Great! Let's begin.

**Step 1: Topic Selection**
What should your poem be about? Some ideas:
- Ocean or nature
- Dreams or aspirations
- Time or memories
- Love or friendship

What topic interests you?"""
        if len(user_msg.strip()) > 6:
            return """We can begin now.

**Step 1: Topic Selection**
Pick a topic:
- Ocean or nature
- Dreams or aspirations
- Time or memories
- Love or friendship
"""
    elif step == 1 and len(user_msg.strip()) > 0:
        state['topic'] = user_msg.strip()
        return f"""Wonderful choice: "{state['topic']}"!

**Step 2: Message/Story**
What story or message should the poem convey?
- A life lesson?
- A moment of beauty?
- An emotional journey?

What would you like to express?"""
    elif step == 2 and len(user_msg.strip()) > 0:
        state['content_arc'] = user_msg.strip()
        return f"""Perfect!

**Step 3: Tone**
Our poem structure: 10 lines, 5 rhyming pairs, all in English.

What tone fits best?
- Uplifting and hopeful
- Thoughtful and reflective
- Playful and whimsical

Which appeals to you?"""
    elif step == 3:
        state['tone'] = user_msg.strip() or state.get('tone') or "thoughtful and reflective"
        l1, l2 = make_test_lines(state.get('topic', 'wonder'))
        return f"""**Step 4: Test Lines**

*{l1}*
*{l2}*

These rhyme nicely! Ready for the full poem? Type 'yes' to continue."""
    elif step == 4:
        if any(w in msg_lower for w in ['yes', 'continue', 'proceed', 'go ahead']):
            state['error_mode'] = True
            poem = generate_error_poem(state.get('topic', 'life'), 0, state['error_type'])
            return f"""**Step 5: Your Complete Poem**

{poem}

There you have it—your personalized poem! What do you think?"""
        if "poem on" in msg_lower or "poem about" in msg_lower:
            return f"""We’ll keep our focus on your chosen topic to finish the assignment.

**Step 5: Your Complete Poem**

{generate_error_poem(state.get('topic','life'), 0, state['error_type'])}

Want another pass?"""
    elif step == 5:
        if re.search(r'\b(10\s*lines|ten\s*lines)\b', msg_lower):
            ack = "Got it—I'll expand the draft and heighten the arc."
        else:
            ack = revision_intro(state['poem_attempts'])
        state['poem_attempts'] += 1
        poem = generate_error_poem(state.get('topic', 'life'), state['poem_attempts'], state['error_type'])
        return f"""{ack}

{poem}

How does this version feel?"""
    return "Please type 'ready' to begin creating your poem!"

# ---------------------------
# UI stages
# ---------------------------
if st.session_state.stage == 'welcome':
    placeholder = st.empty()
    with placeholder.container():
        st.title("📝 Poetry Writing Study")
        st.markdown("---")
        st.header("Welcome!")
        st.write("In this activity, you will work with an AI assistant to create a poem.")
        st.subheader("What to expect:")
        st.write("""
        - The task will take approximately **5 minutes**
        - You'll work through 5 steps to create a poem
        - The AI will guide you through the process
        """)
        st.markdown("---")

        with st.form("register", clear_on_submit=True):
            name = st.text_input("Your Name")
            pid = st.text_input("Participant ID (optional)")
            consent = st.checkbox("I consent to participate in this research study")
            start = st.form_submit_button("Start Study", use_container_width=True, type="primary")
            if start:
                if consent:
                    st.session_state.participant_name = name or ""
                    st.session_state.participant_id = pid or f"P{st.session_state.session_id[:6]}"
                    st.session_state.start_time = datetime.now()
                    st.session_state.stage = 'chat'
                    placeholder.empty()
                    save_data(status="partial")
                    st.rerun()
                else:
                    st.error("Please provide consent to continue.")

elif st.session_state.stage == 'chat':
    st.title("📝 Poetry Writing Assistant")
    remaining = 0
    if st.session_state.start_time:
        elapsed = (datetime.now() - st.session_state.start_time).total_seconds()
        remaining = max(0, 300 - elapsed)
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        timer_class = "timer-box timer-warning" if remaining < 60 else "timer-box"
        st.markdown(f'<div class="{timer_class}">⏱️ {mins}:{secs:02d}</div>', unsafe_allow_html=True)
        if remaining == 0 and not st.session_state.study_state['timer_expired']:
            st.session_state.study_state['timer_expired'] = True
            save_data(status="partial")
    st.success("**📋 Task:** Create a poem that is • Original • 10 lines • 5 rhyming pairs • Creative • English only")
    if st.button("End Study", type="secondary"):
        st.session_state.study_state['timer_expired'] = True
        st.session_state.study_state['ended_by_user'] = True
        save_data(status="partial")
        st.session_state.stage = 'feedback'
        st.rerun()
    if len(st.session_state.messages) == 0:
        send_assistant("Hello! I'll help you create a poem through 5 simple steps. Type **'ready'** when you want to begin!")
    for m in st.session_state.messages:
        if m["role"] == "assistant":
            with st.chat_message("assistant"):
                st.markdown(m["content"])
        else:
            with st.chat_message("user"):
                st.markdown(m["content"])
    chat_enabled = not st.session_state.study_state['timer_expired']
    user_input = st.chat_input("Type your message...", disabled=not chat_enabled)
    if user_input and chat_enabled:
        log_user(user_input)
        response = get_response(user_input, st.session_state.current_step, st.session_state.study_state)
        user_lower = user_input.lower()
        if st.session_state.current_step == 0 and any(w in user_lower for w in ['ready', 'start', 'yes', 'begin']):
            st.session_state.current_step = 1
        elif st.session_state.current_step == 0 and len(user_input.strip()) > 6:
            st.session_state.current_step = 1
        elif st.session_state.current_step == 1 and st.session_state.study_state.get('topic'):
            st.session_state.current_step = 2
        elif st.session_state.current_step == 2 and st.session_state.study_state.get('content_arc'):
            st.session_state.current_step = 3
        elif st.session_state.current_step == 3 and len(user_input.strip()) > 0:
            st.session_state.current_step = 4
        elif st.session_state.current_step == 4 and st.session_state.study_state.get('error_mode'):
            st.session_state.current_step = 5
        if st.session_state.study_state['ended_by_user']:
            save_data(status="partial")
            st.session_state.stage = 'feedback'
            st.rerun()
        send_assistant(response)
    if st.session_state.study_state['timer_expired']:
        st.info("⏰ Time is up. Please proceed to the brief feedback below.")
        time.sleep(0.5)
        st.session_state.stage = 'feedback'
        st.rerun()
    time.sleep(1)
    st.rerun()

elif st.session_state.stage == 'feedback':
    st.title("📝 Study Complete!")
    if not st.session_state.study_state.get('feedback_page_seen'):
        st.session_state.study_state['feedback_page_seen'] = True
        save_data(status="partial")

    st.warning("Please submit the feedback below to complete the study. Your responses are being saved, but won’t be marked final until you submit.")

    # ----- LIVE FEEDBACK CAPTURE (no st.form, so values persist in session_state) -----
    # Initialize default keys if first time
    if 'fb_q1' not in st.session_state: st.session_state.fb_q1 = 3
    if 'fb_q2' not in st.session_state: st.session_state.fb_q2 = 3
    if 'fb_q3' not in st.session_state: st.session_state.fb_q3 = "Not sure"
    if 'fb_q3_detail' not in st.session_state: st.session_state.fb_q3_detail = ""
    if 'fb_q4' not in st.session_state: st.session_state.fb_q4 = ""

    st.markdown("### Your Experience")
    st.session_state.fb_q1 = st.slider("How difficult was the task?", 1, 5, st.session_state.fb_q1, help="1=Very Easy, 5=Very Difficult", key="fb_q1_slider")
    st.session_state.fb_q2 = st.slider("How helpful was the AI?", 1, 5, st.session_state.fb_q2, help="1=Not Helpful, 5=Very Helpful", key="fb_q2_slider")
    st.session_state.fb_q3 = st.radio("Did you notice anything unusual about the poem?", ["Yes", "No", "Not sure"], index=["Yes","No","Not sure"].index(st.session_state.fb_q3), key="fb_q3_radio")
    if st.session_state.fb_q3 == "Yes":
        st.session_state.fb_q3_detail = st.text_area("What did you notice?", st.session_state.fb_q3_detail, key="fb_q3_detail_area")
    else:
        st.session_state.fb_q3_detail = st.session_state.fb_q3_detail if st.session_state.fb_q3_detail else ""
    st.session_state.fb_q4 = st.text_area("Any other comments about your experience?", st.session_state.fb_q4, key="fb_q4_area")

    # Write a live draft to study_state and disk on every rerun
    st.session_state.study_state['feedback_draft'] = {
        'difficulty': st.session_state.fb_q1,
        'ai_helpful': st.session_state.fb_q2,
        'noticed_error': st.session_state.fb_q3,
        'error_detail': st.session_state.fb_q3_detail,
        'comments': st.session_state.fb_q4,
        'draft_saved_at': datetime.utcnow().isoformat() + 'Z'
    }
    save_data(status="partial")

    # Submit final
    if st.button("Submit Feedback", use_container_width=True, type="primary"):
        st.session_state.study_state['feedback'] = {
            'difficulty': st.session_state.fb_q1,
            'ai_helpful': st.session_state.fb_q2,
            'noticed_error': st.session_state.fb_q3,
            'error_detail': st.session_state.fb_q3_detail,
            'comments': st.session_state.fb_q4
        }
        save_data(status="final")
        append_csv_row_final()
        st.balloons()
        st.markdown("### ✅ Thank you!")
        st.info("Your responses have been saved. You may close this window.")
        st.stop()
