"""M3: the LLM recap pass and what is built on it.

One call per session, at session end, over the compacted event log — never a
frame. It yields the session summary, the gap-scaled recaps, the rolling
playthrough state and speaker-attributed conversations; ``verify`` drops
whatever cannot cite an event. ``gap`` picks the recap tier offline at
launch; ``index`` searches items, places, bosses and NPCs locally.
"""
