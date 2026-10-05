# Ticket Price Tracker

Daily price-tracking and email reports for **Miami Dolphins at Buffalo Bills**,
November 22, 2026, Highmark Stadium (Orchard Park, NY).

**Architecture:** GitHub Actions (daily cron) + Python + Gmail SMTP — same pattern as
[`job-alert-system`](https://github.com/nickgardone/job-alert-system).

Each run:
1. Queries the SeatGeek Platform API for the lowest/average/highest resale price.
2. Queries the Ticketmaster Discovery API for the official primary-market price range.
3. Rates today's price (Low/Medium/High) against the price history this tracker has
   collected so far, and calls out the day-over-day / week-over-week trend.
4. Emails the report to `ngardone@gmail.com`.
5. Appends today's snapshot to `price_history.json` and commits it, so the rating gets
   more accurate the longer the tracker runs.

## Why only SeatGeek + Ticketmaster are "live" data, and StubHub / Vivid Seats are links only

StubHub and Vivid Seats don't publish a public pricing API, and both run bot-detection
(Akamai/PerimeterX-style) that routinely blocks automated requests from shared infra like
GitHub Actions. Rather than ship a scraper that silently breaks, the report includes a
direct link to each site's exact event page so you can glance at the live price yourself
in one click. SeatGeek and Ticketmaster both have official, stable public APIs, so those
two carry the actual data-driven rating and trend.

## Important limitation: "life of ticket sales" history

There's no public API that returns a ticket's full historical price curve since tickets
first went on sale. This tracker builds its own baseline starting from the day it's first
run — the High/Medium/Low rating is a rough heuristic for roughly the first 1-2 weeks,
then becomes a real comparison against this event's actual tracked price range.

## One-time setup

1. **Gmail app password** — this repo reuses the same Gmail account as `job-alert-system`.
   Copy the existing secret over (run this yourself so the password never passes through
   chat):
   ```bash
   gh secret set GMAIL_APP_PASSWORD -R nickgardone/ticket-price-tracker --body "<your existing Gmail app password>"
   gh secret set NOTIFY_EMAIL -R nickgardone/ticket-price-tracker --body "ngardone@gmail.com"
   ```

2. **SeatGeek client_id** — free at <https://seatgeek.com/account/develop>.
3. **Ticketmaster consumer key** — free at <https://developer.ticketmaster.com/>.

   Once you have both, either paste them in chat for Claude to set, or run:
   ```bash
   gh secret set SEATGEEK_CLIENT_ID -R nickgardone/ticket-price-tracker --body "<client_id>"
   gh secret set TICKETMASTER_API_KEY -R nickgardone/ticket-price-tracker --body "<consumer_key>"
   ```

4. Trigger a test run any time from the **Actions** tab, or:
   ```bash
   gh workflow run track_prices.yml -R nickgardone/ticket-price-tracker
   ```

## Schedule

Runs daily at 13:30 UTC (~8:30am America/Chicago; shifts an hour across the DST change
in early November) until the game date. GitHub Actions cron has no natural end date —
delete or disable the workflow after November 22, 2026.
