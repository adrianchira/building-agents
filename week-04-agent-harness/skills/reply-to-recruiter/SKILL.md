---
name: reply-to-recruiter
description: Answer a recruiter or hiring team about a call or an interview time.
---
# Replying to a recruiter or hiring team

Alex is changing careers into AI engineering. Every reply is a first impression.

1. Read Alex's preferences note (`read_note preferences.txt`) and check the calendar for the days offered.
   Rules that decide the time:
   - Work is 9:00-17:30. Don't put calls in work hours.
   - No calls 17:30-20:00 on weeknights (dinner, homework, bedtime).
   - Never overlap the AI course's live sessions.
2. Pick ONE time that fits both the rules and the times the sender offered. Use `free_slots` for each offered
   day, with day_start and day_end set to the sender's window. If no offered time fits the rules, say so politely
   and propose the closest time that does.
3. Put the call in the calendar (category `job_search`). If an existing event is being moved, use `move_event`
   on it; don't create a duplicate.
4. Save the reply with `draft_email`, never `send_email`: Alex sends his own job-search emails.
   - Under 90 words. Warm, direct, no exclamation marks in a row.
   - Say the day with its date and the time with the time zone (Eastern).
   - Sign it "Best, Alex".
5. In your final answer, say what you booked and that the draft is waiting for Alex.
