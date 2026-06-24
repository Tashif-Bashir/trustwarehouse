# "Who's Free" Availability View — Use-Case Report

**Status:** scoping (pre-build) · companion to `availability_diagnosis.md`
**Purpose of this doc:** define what the view shows, who uses it and how, and the decisions that shape the build — before any code.

---

## 1. Who it's for

- **Primary: telesales agents** (Lily, Sue, Alicja, Alisha) — the people booking appointments while a customer is on the line.
- **Secondary: sales managers** (Fiona, Scott) — week-at-a-glance oversight: who's overloaded, who's idle, where the thin spots are.

## 2. The job to be done (the booking moment)

> *"A customer is on the phone. I need to book a home visit with the right rep, at a time the customer can do, in a slot the rep is genuinely free — in seconds, without scrolling a wall of everyone's events or accidentally booking someone who's on holiday."*

Everything the view does serves that 20-second moment.

## 3. What the view shows

**Must-have (v1):**

1. **Per-rep availability grid.** Next ~10 working days across the top, the working day (e.g. 09:00–17:00) down the side, one lane per rep. Each cell is **Free / Booked / Time-off**. At a glance: *"Thursday 2pm — who's open? → Niall, Kelly, Paul."*
2. **Free-slot finder ("find me a slot").** The inverse: agent enters constraints — *any rep or a specific rep*, a date range, and a time-of-day preference (AM/PM) — and gets a ranked list of open slots. For when the customer says *"I can only do Tuesday afternoon."*
3. **Rep filter & status.** Filter to one rep (repeat customer who wants the same advisor) or a team; each rep shows a clear **available / off-today / fully-booked** status.
4. **Time-off shown correctly.** Holidays/OOO render as **unavailable** — derived from the events directly, so it's right even though they're (wrongly) marked "Free" in Outlook today.
5. **Today / this-afternoon view.** Same-day and urgent: *"who can take a 4pm today?"*

**High-value (v1 or fast-follow):**

6. **Capacity / load signal per rep.** *"Niall: 4 booked today · Sammy: 0."* Surfaces the uneven distribution the diagnosis found (plenty of capacity, just hard to see) so work can be spread fairly.
7. **Double-book guard.** If a chosen slot overlaps an existing appointment or time-off for that rep, flag it before it's booked.

**Phase 2 (the big leverage):**

8. **One-click booking from the view.** Create the appointment directly — with the rep correctly invited, the event blocking the rep's own calendar, and a standard subject/category. This makes the tool the **booking front-end**, which *enforces* the calendar hygiene going forward (every appointment booked through it is clean), instead of just reporting on the mess.

## 4. How it's used — concrete scenarios

- **Inbound call:** customer wants a visit → agent filters to the dates the customer can do → grid shows which reps are free → agent picks one and books. No scrolling, no guessing.
- **"Tuesday afternoon only":** agent uses the slot-finder for *Tue PM, any rep* → gets the open slots → offers two times to the customer.
- **Repeat customer / specific rep:** filter to that rep → see their next open slot.
- **Same-day urgency:** today view → *"who's free at 4pm?"*
- **Fair distribution / manager:** week view shows Sammy at 0 and Niall at 6 → steer the next bookings to the quieter rep.
- **Avoiding the holiday trap:** a rep on annual leave shows **Off**, not Free — so they can't be mis-booked (today's #1 risk).

## 5. What "available" means (the rules the view encodes)

- **Free** = inside working hours, AND not in an appointment, AND not in time-off, AND not inside a blocked window (e.g. "bank holiday – NO APPTS").
- **Appointments** are taken from the **shared calendar** (the reliable record), attributed to the right rep via the email+category resolver (99% accurate) — *not* from each rep's own free/busy, because 3 of 14 reps' calendars under-block (Sam Chapman, Chris Mannix, Paul).
- **Time-off** is detected from OOO/holiday/"day off"/all-day blocks **regardless of the Outlook "Free" flag**.
- **Working hours / slots** — a working-day model (Mon–Fri core, Sat limited, Sun none) divided into bookable slots. *Slot length/typical visit duration to be calibrated from the data.*

## 6. Where it lives & how it refreshes

- A new **"Availability" page on the existing dashboard** (same Flask/Vercel stack as the telesales/sales pages), so telesales use one tool.
- Reads live from the Microsoft Graph calendar on load, **cached ~2–5 min** — near-real-time without hammering the API. Not streaming; a manual "refresh" is enough.

## 7. What it fixes (tied to the diagnosis)

| Diagnosis finding | How the view addresses it |
|---|---|
| No reliable per-rep field | Resolves the rep automatically (email+category, 99%) so the grid is clean |
| Time-off marked "Free" | Derives time-off from the events → shows **Off**, removing the mis-book risk |
| Reps' own calendars under-block | Availability is computed from the **shared appointment record**, not their patchy free/busy |
| Wasted scanning time / visual chaos | Replaces the wall-of-events scan with a per-rep grid + slot finder |
| Uneven load (capacity exists, unseen) | Load indicator helps distribute bookings |

## 8. Decisions to confirm before building

1. **Geography / territory** *(biggest one)* — these are in-home field visits, so the *right* rep usually depends on the customer's location. Should the view be **region/postcode-aware** (show "reps who cover this area + their free slots"), or just show all reps' availability and let the agent apply geography manually? Region-aware is far more powerful but needs a **rep → area coverage** mapping we don't have yet.
2. **Slot model** — fixed-length slots (e.g. 60/90 min) or named AM/PM windows? Driven by typical visit duration + travel time. Calibrate from the calendar data.
3. **v1 scope** — read-only "who's free" view first (lower risk, immediate value), with one-click booking as Phase 2; or go straight to booking write-back (more value, but it writes to the live calendar and must be got right).
4. **Working-hours definition** — confirm core hours, Saturday policy, and how "NO APPTS" admin blocks should be treated.

## 9. Suggested MVP (v1)

A read-only **Availability page**: per-rep grid for the next ~10 working days + a slot-finder, time-off shown correctly, load indicator, refreshed from Graph. No write-back yet. This delivers the core "who's free in seconds" value, proves the availability logic against real bookings, and de-risks the Phase-2 booking front-end.
