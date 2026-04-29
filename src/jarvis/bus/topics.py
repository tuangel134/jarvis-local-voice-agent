from __future__ import annotations

SYSTEM_STARTED = "system.started"
PERCEPTION_TEXT_TRANSCRIBED = "perception.text.transcribed"
INTENT_DETECTED = "intent.detected"
PLANNER_STEPS = "planner.steps"
ACTION_EXECUTED = "action.executed"
TTS_RESPONSE_GENERATED = "tts.response.generated"

ALL_TOPICS = [
    SYSTEM_STARTED,
    PERCEPTION_TEXT_TRANSCRIBED,
    INTENT_DETECTED,
    PLANNER_STEPS,
    ACTION_EXECUTED,
    TTS_RESPONSE_GENERATED,
]
