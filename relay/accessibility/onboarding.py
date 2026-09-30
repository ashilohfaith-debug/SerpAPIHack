"""Spoken, voice-only onboarding.

A blind user must be able to start RELAY and understand it with no visual step. On
first run RELAY introduces itself, states how to talk to it and stop it, and (if a
screen reader is present) explains how it coexists. The "first run" flag is a small
file in the per-user data dir, so onboarding runs once but can be replayed on
request ("help" / "how do I use you").
"""

from __future__ import annotations

from relay.accessibility.coexist import coexistence_advice, screen_reader_running
from relay.config import user_data_dir


def _flag_path():
    return user_data_dir() / ".onboarded"


def is_first_run() -> bool:
    return not _flag_path().exists()

def mark_onboarded() -> None:
    try:
        _flag_path().write_text("1", encoding="utf-8")
    except OSError:
        pass

def run_onboarding(session) -> None:
    """The conversational onboarding loop."""
    wake = session.store.get_pref("wake_word", default="relay")
    from relay.audio.hotkeys import spoken_combo
    talk = spoken_combo(session.talk_key)
    running, name = screen_reader_running()
    
    if not is_first_run():
        lines = [f"Relay is ready. Press {talk}, or say {wake}, to talk to me."]
        if running:
            lines.append(f"{name} is running too; I'll stay out of its way.")
        for line in lines:
            session.say(line, 2)  # _REQ
        session._rearm_voice()
        return

    # First run conversational loop
    def step_2():
        session.say("How fast should I speak? Say a number between 0.6 and 2.2, or say default.")
        def handle_speed(ans: str):
            ans_low = ans.lower()
            try:
                import re
                nums = re.findall(r"\d+\.\d+|\d+", ans_low)
                if nums:
                    speed = float(nums[0])
                    session.set_speech_rate(speed)
                    session.say(f"Okay, speed set to {speed}.")
                else:
                    session.say("I'll keep the default speed.")
            except Exception:
                session.say("I'll keep the default speed.")
            step_3()
        session.capture_next(handle_speed)

    def step_3():
        session.say("For screen reading, do you prefer quick summaries or detailed descriptions? Say quick or detailed.")
        def handle_detail(ans: str):
            if "detail" in ans.lower():
                session.store.set_pref("narration_mode", "detailed")
                session.narration_mode = "detailed"
                session.runner.mode = "detailed"
                session.say("I'll be detailed.")
            else:
                session.store.set_pref("narration_mode", "quick")
                session.say("I'll be quick.")
            step_4()
        session.capture_next(handle_detail)

    def step_4():
        session.say("Should I always ask for confirmation before clicking or typing? Say yes or no.")
        def handle_conf():
            session.store.set_pref("confirmation", "always")
            session.say("I will always ask before taking action.")
            step_5()
        def handle_no_conf():
            session.store.set_pref("confirmation", "adaptive")
            session.say("I'll only ask for important actions.")
            step_5()
        session.offer(handle_conf)
        # We need a way to capture 'no' for the offer... wait, session.offer drops it on 'no'. 
        # But we need to move to step_5! 
        # Actually, capture_next is better for this.
        session._offer = None # clear offer
        def handle_conf_capture(ans: str):
            import re
            if re.search(r"\b(?:yes|yeah|always)\b", ans, re.I):
                session.store.set_pref("confirmation", "always")
                session.say("I will always ask before taking action.")
            else:
                session.store.set_pref("confirmation", "adaptive")
                session.say("I'll only ask for important actions.")
            step_5()
        session.capture_next(handle_conf_capture)

    def step_5():
        session.say("Do you consent to me sending snippets of your screen to cloud AI models for processing? Say yes to allow, or no to stay strictly offline.")
        def handle_cloud(ans: str):
            import re
            if re.search(r"\b(?:yes|yeah|allow|sure|ok)\b", ans, re.I):
                session.store.set_pref("cloud_consent", "1")
                session.say("Cloud processing allowed. If you have a Free LLM API key copied to your clipboard, say 'read key' to save it now, or say 'later' to skip.")
                def handle_key(ans2: str):
                    if re.search(r"\b(?:read|key|yes|yeah|sure|ok)\b", ans2, re.I):
                        import pyperclip
                        key = pyperclip.paste().strip()
                        if len(key) > 10:
                            from relay.memory.secrets import save_secret
                            save_secret("RELAY_LLM_KEY", key)
                            session.say("Key saved securely.")
                        else:
                            session.say("I didn't find a valid key on the clipboard.")
                    else:
                        session.say("We can set it up later.")
                    step_done()
                session.capture_next(handle_key)
            else:
                session.store.set_pref("cloud_consent", "0")
                session.say("I will stay offline. No screen data will leave this computer.")
                step_done()
        session.capture_next(handle_cloud)

    def step_done():
        mark_onboarded()
        session.say("Setup complete. Say help at any time to hear more. What would you like to do?")
        session._rearm_voice()

    # step_1
    lines = [
        "Hello, I'm Relay. I help you use this computer by voice.",
        f"To talk to me, press {talk} from anywhere — you'll hear a short chirp — "
        f"then speak. Or just say {wake}, then your request.",
        "Say stop to interrupt me, cancel to stop a task, or emergency stop to halt everything at once.",
    ]
    if running:
        lines.append(coexistence_advice(name))
    lines.append("I need to ask you a few setup questions. Should we do that now? Say yes or no.")
    for line in lines:
        session.say(line, 2)
        
    def handle_yes_setup(ans: str):
        import re
        if re.search(r"\b(?:yes|yeah|sure|ok)\b", ans, re.I):
            step_2()
        else:
            step_done()
    session.capture_next(handle_yes_setup)
