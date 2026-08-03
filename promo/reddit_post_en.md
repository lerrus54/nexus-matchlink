# Reddit / ENG post

Title (pick one):
- [OC] Made a free tool that accepts your Dota 2 match from your phone
- Never miss a queue pop again: accept Dota 2 / CS2 matches from your phone

Body:

I built a small free utility that watches your screen and the moment the Accept
button appears it pushes a notification to your Telegram. The notification has an
"ACCEPT MATCH" button — tap it on your phone and the app restores the game window
and clicks Accept for you. No more sitting in front of the monitor waiting for a game.

What it does:
- Dota 2 and CS2 (for CS2 you drop your own screenshot of the Accept button once)
- Telegram push + sound alert
- Works fully in the background — you can minimize the game
- Sends data nowhere except your own Telegram chat
- Open source on GitHub, ~30 MB single .exe, no Python required

Download: t.me/nexus_matchlink

Why this is NOT a cheat: it's plain UI automation — the program "sees" the button
on screen exactly like you do and clicks it. No memory reading, no game injection,
nothing.

Found a bug? Open an issue, I'll fix it. Code is public.

Notes:
- r/Dota2 and r/GlobalOffensive often restrict self-promo — check rules, or drop it
  into the weekly free-talk thread.
- Best traction: reply as a helpful comment under threads like "who else missed a
  match while afk" rather than a standalone ad.
- Post once per sub, then engage with comments. Spam = ban.
