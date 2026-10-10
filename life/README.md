# Alex's week: the template

The simulated life used by every week of the course. **Edit the data here**, never in a week's `data/` folder
(that one is generated and overwritten).

| File | What it is |
|---|---|
| `calendar.csv`, `tasks.csv` | Written for the week of Monday 2026-10-12. Dates are shifted by whole weeks to the current week. |
| `notes/*.txt` | Dates are placeholders: `{{+4}}` → "Friday, October 16", `{{+1:short}}` → "Tue Oct 13" (days from Monday). |
| `simweek.py` | `build_week(out_dir)` writes the dated copy. Each week folder (and solution) has a copy of this file. |

The simulated "today" is the Monday of the current week (on Saturday and Sunday: the coming Monday).
Set `LIFE_TODAY=YYYY-MM-DD` in `.env` to pin it. Because only whole weeks are added, every weekday and every
answer in the exercises stays the same.

After changing `simweek.py` here, copy it to the other places:

```bash
for d in week-01-agentic-loop week-02-tools-and-permissions week-0*/solution/agent; do cp life/simweek.py $d/; done
```
