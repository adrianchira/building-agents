---
name: reschedule
description: Move, add or cancel calendar events without breaking Alex's rules.
---
# Rescheduling

1. Find the event and its id with `list_events` for that day. Never guess an id.
2. Never move or cancel `work` events, and never move the AI course's live sessions.
3. Check the new time with `free_slots` before you move anything. Respect the preferences note:
   gym Monday and Thursday 6:30 stays; no calls 17:30-20:00 on weeknights; in bed by 23:00.
4. Prefer `move_event` over cancel + create: it keeps the event's id and history.
5. Cancelling is destructive: only do it when Alex asked for it explicitly.
6. Answer with a short before → after list.
