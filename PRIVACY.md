# RMT Privacy Policy

_Last updated: November 2, 2026_

RMT ("Risky Money Time") is a personal desktop app that runs entirely on your own computer. It has no servers, no accounts with us, and no analytics or tracking.

## What RMT does with your Google / YouTube data

When you choose **Sign in with Google** in RMT, you give RMT **read-only** access to your YouTube account (the `youtube.readonly` permission). RMT uses it only to:

- list the channels you are subscribed to, and
- show the newest videos from those channels, and from the finance channels built into RMT, inside the app.

RMT does **not** post, like, comment, subscribe, upload, or change anything on your YouTube account, and it does not read your email, contacts, or any other Google data.

## Where your data is kept

- The sign-in tokens Google gives RMT are saved in a file on **your computer** (`data/youtube_token.json` in the RMT folder).
- Video and subscription lists are kept in memory and in RMT's `data` folder on your computer, only to show them to you.
- RMT never sends your Google data to the RMT developers or to any third party. RMT talks only to Google's own servers to fetch it.

RMT's use of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Other services

If you add keys for other services (Alpaca, Finnhub, The Odds API, Anthropic), RMT sends requests to those services from your computer to show prices, odds, or AI answers. Those keys are stored only in the `.env` file on your computer.

## Removing access

- In RMT: **⚙ → YouTube → Sign out** deletes the saved sign-in from your computer.
- In your Google account: visit [myaccount.google.com/permissions](https://myaccount.google.com/permissions), choose the RMT app, and remove its access.
- Deleting the RMT folder removes everything RMT stored.

## Contact

Questions about this policy: open an issue at [github.com/jhauser2318-design/RMT/issues](https://github.com/jhauser2318-design/RMT/issues).
