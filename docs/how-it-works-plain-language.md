# How skill-concierge Works — In Plain Language

*For anyone who understands Claude and AI assistants at a basic level, but doesn't
want the technical details. A two-minute read.*

## The one-sentence version

skill-concierge is a quiet helper that makes sure Claude reaches for the **right
specialized skill at the right moment** — like a hotel concierge who knows every
service in the building and gently points you to the one you actually need.

## The problem it solves

Claude can be given dozens of **skills** — small expert playbooks for specific jobs
(writing a clean commit, designing a database, reviewing code, and so on). But left
alone, two things go wrong:

1. **Claude usually doesn't know a skill exists.** It is only shown a handful at a
   time, out of hundreds. The rest are invisible to it.
2. **Even when a skill fits, Claude tends to just wing it** out of habit — like
   someone with a full toolbox who keeps reaching for their bare hands.

The result: excellent skills sit unused, and you get a more generic answer than you
could have had.

## The idea, in one picture

Picture a hotel:

- **You** (the guest) make a request.
- There is a back room full of **specialists** — a tailor, a translator, a travel agent.
- Most guests never learn those specialists exist.
- **The concierge** is the person who hears your request, knows the whole roster, and
  says: *"For that, you'll want our travel agent — shall I send you over?"*

skill-concierge is that concierge, sitting quietly between you and Claude's specialists.

## What happens every time you send a message

Before Claude answers, in the background, skill-concierge:

1. **Reads your request** and asks: *"Is there a skill that fits this — by meaning,
   not just by matching words?"*
2. If there is a good match, it **whispers a reminder to Claude**: *"There's a skill
   for this — consider using it."* Claude still decides; it is a nudge, not an order.
3. If there is no good match, or the request is just small talk, or anything is
   unclear — **it says nothing** and lets Claude work normally.

You never see this. It happens in the half-second before Claude starts replying.

## The four quiet jobs it does

| In plain terms | What it is for |
|---|---|
| **The librarian** | Finds *which* skill fits your request, by meaning. |
| **The concierge's nudge** | Reminds Claude to actually *use* the right skill, in the moment. |
| **The logbook** | Quietly records what was offered and what got used, so the system can be improved with evidence. |
| **The caretaker** | Keeps the whole thing installed, healthy, and running. |

## Why it was designed this way

Every choice comes back to one belief: **a helper that sometimes gets in your way is
worse than no helper at all.** So:

- **It nudges; it never blocks.** It reminds Claude *during* its thinking — the only
  moment a reminder can still change the answer. It never stops Claude and never
  overrides you.
- **When in doubt, it stays out.** If the match is weak, the request is trivial, or
  anything breaks, it goes silent. It would rather miss a nudge than give a wrong or
  annoying one.
- **It saves its nudges for real tasks.** It can tell the difference between *"do this
  for me"* and *"just chatting,"* and only speaks up for the former.
- **It learns from evidence, not guesses.** The logbook lets the people maintaining it
  tune how eager or cautious it should be, based on what actually happened — not gut feel.
- **It is honest about whether it truly helped.** It carefully separates two very
  different things: *a reminder was shown* versus *the right skill was actually used to
  do the job.* Showing reminders is easy; what matters is the work coming out better —
  so it measures the second thing, not the flattering first one.

## What you would notice as a user

Almost nothing — and that is the point. You ask for things the way you always do. Now
and then, Claude reaches for a sharper, more specialized approach than it otherwise
would have. The help shows up in the **quality of the answer**, not in any extra step
for you.

## In one line

skill-concierge is the quiet concierge that helps Claude pick the right specialist at
the right moment — nudging, never blocking, and stepping aside the instant it isn't sure.
