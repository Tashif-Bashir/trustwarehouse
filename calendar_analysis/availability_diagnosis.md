# Shared Appointment Calendar — Diagnosis & Options

**Calendar:** `info@trustelectricheating.co.uk` (single shared Outlook calendar)
**Prepared:** 23 June 2026 · read-only analysis via the Microsoft Graph API
**Windows analysed:** a 90-day window (735 events) and a focused 6-week window (418 events / 331 timed appointments, ~55 appointments/week)

---

## Executive summary

The problem isn't that reps are overbooked — **it's that nobody can quickly see who is free.** Every rep's appointments, holidays and personal notes live in one shared calendar, with the rep identified three different (and inconsistent) ways, and with time-off logged in a way that doesn't actually block availability. So telesales scan a wall of overlapping events and guess at free slots.

The encouraging finding: **the data needed to fix this is all there and readable** — the Graph `getSchedule` free/busy API returns successfully for every rep, and appointments can be attributed to the right rep **99% of the time by a tool** (even though they can't be by eye). The fix is an availability layer that derives "who's free" from the calendar automatically, plus a few calendar-hygiene corrections.

---

## How it works today

1. A telesales agent opens the shared `info@` calendar.
2. They visually hunt for a gap for the right rep.
3. They create an event with the customer's details and invite the rep as an attendee, so it also appears in the rep's own Outlook.

There is **no structured "this rep, this slot, free/busy" view** — availability is inferred by eye from a single congested calendar.

---

## Findings (with evidence)

### 1. There is no reliable per-rep field
A rep is tagged in up to three places, none consistent on its own:
- **Categories** are free-text and messy — `Kourosh` (= Kris), `Chris M` vs `Chris Mannix`, `Sam` vs `Sam Chapman`, `Sammy`; **33 events had no category** at all (90-day window).
- **Attendees** carry the rep's email **~89%** of the time — but **~11% have no rep attendee** (e.g. "chris cash jersey", "ROB- OOO" only carried `info@`).
- Combining both signals, a tool resolves the rep on **99%** of appointments (4 unresolved of 331). **A human scanning the calendar cannot do this reliably or quickly** — which is the daily friction.

### 2. Time-off is logged as "Free", so it doesn't block anything
All-day holiday / out-of-office / "BUSY" / "DAY OFF" events are marked `showAs = free`:
- 90-day window: **55 of 56** all-day blocks were `free`.
- 6-week window: **33** time-off/admin blocks marked `free`.

Because they're "free", **a rep on holiday still shows as available** — in the shared calendar *and* in Outlook's own scheduling assistant. This is the single biggest cause of mis-booking risk.

### 3. Reps' own calendars under-represent their real bookings
`getSchedule` works for every rep, but comparing each rep's shared-calendar appointments against their own free/busy (next 14 days) shows some calendars don't reflect their bookings:

| Rep | Shared appts (next 14d) | Own calendar busy hrs | |
|---|---|---|---|
| Sam Chapman | 8 | **0** | own calendar shows FREE despite 8 appts |
| Chris Mannix | 12 | 2 | badly under-blocked |
| Paul | 9 | 2 | under-blocked |
| Niall / Kelly / Kris / Scott / Samantha | 8–17 | 21–79 | OK |

So free/busy is trustworthy for *most* reps but **unreliable for ~3 of 14** — because appointments sit in the shared mailbox and the rep is only an attendee (acceptance/blocking varies per person). A free/busy-only solution would silently mis-state those reps.

### 4. Hard double-bookings are actually rare
Across the 6-week window there was **only 1** genuine same-rep time overlap (Scott — an all-day "DUAL CALLING" block over a real appointment). **The cost of today's setup is wasted telesales time, mis-booking *risk*, and visual congestion — not mass conflicts.**

### 5. Capacity is healthy — free slots exist, they're just hard to find
Per rep, per active working day: **~1–2 appointments on average**, busiest days 5–6 (Niall, Kelly). Reps are not slammed; there is plenty of open capacity. **The problem is locating the free slots, not a shortage of them.**

### 6. Congestion is visual and peaky
331 appointments for ~14 reps all render in one calendar. Demand concentrates at **10–11am and 3–4pm**, heaviest **Mon/Thu/Fri**; Saturday light, Sunday near-empty. One calendar showing everyone at once makes the busy windows look impenetrable.

---

## Root cause

A single shared calendar is being used as the **source of truth for availability**, but it has no availability layer: rep identity is unstructured, and time-off doesn't block. Availability is therefore a human guess, every time.

---

## Recommended solution

**A purpose-built "who's free" availability view, built on a few calendar-hygiene fixes.**

**B — Availability layer (the real win).** A tool/view that:
- reads the shared calendar (the reliable record of *appointments*) and attributes each to the right rep (email + category, the 99% resolver),
- overlays each rep's time-off,
- presents telesales a clean **per-rep day grid showing open slots**, and can suggest the best slot per rep.

This works even where reps' own free/busy is patchy (Finding 3), because it derives availability from the appointment record directly rather than trusting each rep's calendar.

**A — Calendar hygiene (quick wins, needed for accuracy either way):**
1. Log time-off as **Busy / Out-of-office**, never *Free* (fixes Finding 2 immediately).
2. Standardise the rep tag — ideally always invite the rep by their `@trustelectricheating.co.uk` address (drives the 99% → ~100%); categories become secondary.
3. Ensure rep appointments **block the rep's own calendar** (owner the event appropriately / auto-accept), fixing Sam Chapman / Chris Mannix / Paul.

> The Graph API supports this fully — `getSchedule` (free/busy), `findMeetingTimes` (slot suggestions), and per-calendar reads all returned successfully in testing.

---

## Appendix

**Rep mailboxes seen (attendee → rep):** scott@, kris@, niall@, kelly@, chrism@, samchapman@ (SamC), samantha@, paul@, **chrisk@ (ChrisK)**, rob@, samuel@ (Sammy), merv@, victoria@, gia@. (These line up with the sales-team `sales_rep_mapping`; `chrisk@` confirms the "ChrisK" name on the sales sheet.)

**Category variants observed (the inconsistency):** `Kourosh`=Kris, `Chris M`/`Chris Mannix`=ChrisM, `Sam`/`Sam Chapman`=SamC, `Sammy`, `Scott Conor`, `Niall Devenish`, `Kelly`, `Samantha Doyle`, `Paul Slade`, `Chris Cash`, `Rob`, `Chris Southworth`, `Sarah Jordan`, `Keith`, `Victoria`, `Josh`, `Merv`, plus 33 uncategorised.

**Method:** Microsoft Graph `calendarView` + `getSchedule`, read-only, client-credentials app with `Calendars.Read`. No data was modified.
