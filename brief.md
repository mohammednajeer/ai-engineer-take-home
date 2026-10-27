# mera.health AI Engineer Take-Home

**Make it better, and prove it**

## Context

A core part of mera.health is turning lab reports that Indian families upload into structured data. The reports come from hundreds of labs in wildly different formats: clean digital PDFs, scanned PDFs, phone photos of printouts, multi-page documents, handwritten annotations.

We are not asking you to build an extractor. We've built one for you, and it isn't very good. Your job is to find out how bad it is, work out why, and make it measurably better.

## What we're giving you

- `extract.py`: a working baseline. One command, one file in, JSON out.
- `reports/`: 12 sample reports covering the formats we see in production. The patients are fictional. The mess is realistic.
- `gold/`: labels for 8 of the 12 reports. They were made in a hurry. Treat them the way you'd treat any labels.
- `schema.json`: the output shape (test name, value, unit, reference range, per row).

## What you'll do

1. **Plan first.** Before you or your agent write any code, commit a `PLAN.md`: how you're breaking this down, what you'll look at first, what you expect to find. Half a page. It's fine if the plan turns out wrong. Don't go back and edit it.
2. **Build an eval.** Decide what "correct" means for an extracted row, score the baseline against the gold labels, and give us the number. Four reports have no labels. Tell us how you assessed those.
3. **Diagnose.** Find the three failure categories that matter most. For each one, point at a specific report and row, and tell us the root cause, not the symptom.
4. **Fix.** Change whatever you like: prompts, pipeline shape, model, validation, the lot. Show before and after on your eval, alongside cost per report and latency.
5. **Tell us one thing you tried that didn't help.** With the numbers.
6. **Three short answers**, one paragraph each, argued for this problem specifically and not in general:
   - Would retrieval (RAG) help here?
   - Would fine-tuning help here?
   - Would a multi-step agent help here, or is that complexity the pipeline hasn't earned?

Keep the entry point intact: `python extract.py <file>` must still print schema-valid JSON. We will run your version on 6 reports you haven't seen.

## How we expect you to work

We expect you to use a coding agent: Claude Code, Cursor, whatever you prefer. Writing the code is the cheap part now, so the code isn't what we're assessing. We're assessing how you approached the problem: how you broke it down, what you asked the agent to do, where you disagreed with it, and what you checked yourself.

So please:

- **Send your agent transcripts.** Export your sessions and include them unedited. This is strongly encouraged, not required. If we move to the next step, explaining your approach is part of the evaluation, and the transcript is the best record you'll have of what you did and why. It helps you as much as it helps us.
- **Keep your real git history.** Commit as you go. Don't squash.
- **Keep a short decision log** in the README: where you overruled the agent, and what you verified by hand.

A messy transcript where you changed your mind is better than a clean one. We are not grading your prompts for polish.

## Time

4 to 6 hours. We mean it. If you're spending more, you're solving the wrong problem. Send it back within 5 days of receiving it.

## Cost

Use any model or provider, including free credits or open models you can run locally. Paid API access is not required. Work with the resources you can access, explain your choice, and report cost and latency even when your actual API spend is zero. Never include API keys in your submission or transcripts.

## How we'll evaluate you

About half of this is your process and half is what came out of it.

**Process**
1. **Decomposition.** Did you break the problem into pieces before starting, or hand the agent the whole brief?
2. **Directing the agent.** When it guessed, did you notice? When it was wrong, did you find out why?
3. **Verification.** What did you check yourself, and what did you take on trust?

**Outcome**
4. **Eval design.** Does your eval measure what a doctor would care about? Would your number move if the pipeline got worse in a way that matters?
5. **Diagnosis and evidence.** Did the change make things better, or just different? Can you tell the two apart with 8 labelled reports?
6. **Cost and model choice.** What does one report cost before and after? Would this hold up at 10,000 reports a day?
7. **What you chose not to do.** This matters as much as what you built.

## What to submit

- The code, as a repo link or zip, with its git history.
- `PLAN.md`, as first committed.
- A README, two pages at most, covering tasks 2 to 6 and your decision log. Tables beat prose.
- Your eval, runnable with one command, and its output for baseline and final.
- Your actual prompts to the model, with a sentence on why each is shaped the way it is.
- Your agent transcripts, if you're sharing them.

## What we're not looking for

- A perfect score. The data is messy on purpose.
- Production-grade code. This is a prototype.
- A UI, a deployment, a database, a queue.
- A rewrite in your favourite framework.

## What will get you rejected

- Work you can't explain. "The agent wrote it that way" isn't an answer.
- A better number with no evidence behind it, or sample-specific fixes presented as general improvements. We'll examine the 6 unseen reports alongside your evidence; a score difference alone does not establish the cause.
- Changing the eval until the score goes up.
- Ignoring cost.
- Over-engineering. If the baseline was 150 lines and yours is 1,500, you've failed the judgment test.

## After you submit

If we move forward, a 45 minute call. You'll walk us through your approach, we'll ask about specific moments in it, and then we'll inspect an extraction error or a new ambiguous report and work through it together.
