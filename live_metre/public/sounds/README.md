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

## Making the wall screen play it without anyone clicking

Browsers refuse to start audio until a page has had a real user gesture, so a
board left running on a wall would stay silent. Two ways round it:

**Preferred — launch the kiosk with autoplay allowed.** The board calls
`tryAutoUnlock()` on load; with this flag it succeeds, the "enable sound" badge
never appears, and a screen nobody touches still rings:

```
chrome.exe --kiosk --autoplay-policy=no-user-gesture-required ^
  https://trust-live-metre.vercel.app/sales-ops
```

Put that in the shortcut in `shell:startup` on the wall PC so it survives a
reboot.

**Fallback — one click.** Without the flag the board shows a
"🔔 Tap once to enable the sale sound" badge. One click arms it for the life of
that page, and it has to be done again after every reload.

Test on demand any time by adding `?sound=1` to the URL.
