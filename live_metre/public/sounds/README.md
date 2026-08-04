# Sale sound

Drop a file named **`sale.mp3`** in this folder and the sales & ops board will
play that exact recording when a sale lands, instead of the synthesised sound.

- Path the board looks for: `/sounds/sale.mp3` (set by `SALES_SOUND.file` in
  `lib/config.ts` — point it at `.wav`/`.ogg` there if you prefer that format).
- Keep it **short (≤ 2s)** and reasonably quiet; it fires several times a day.
  Playback volume is scaled by `SALES_SOUND.volume`.
- If the file is missing or won't decode, the board silently falls back to the
  synthesised sound — nothing breaks.
- Redeploy after adding it (`vercel deploy` from `live_metre/`), since it ships
  as a static asset.

**Licensing:** use something you're allowed to use commercially — Pixabay,
Mixkit and freesound.org (check each clip's licence) all have free
cash-register/coin effects. Don't rip audio from YouTube; those uploads are
usually someone else's copyright even when the video calls itself "free".
