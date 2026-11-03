# Design and evidence

## Scope

Portable code snapshot only: no live activation, private medical timeline, account
IDs or deployment receipts. Use explicit consent/configuration for any future
installation. Canonical sensitive state is external, in a dedicated0700 directory
with0600 files. Tests use labelled synthetic fixtures and fake delivery responses.
Do not perform a live group test. See references/live-runner.md for reconstruction.

## Temporary bootstrap policy

An optional explicitly chosen fixed 28-day assumption may be used with a +/-1 day reminder window while collecting actual dates. The explicit state policy overrides the older seed-range/median forecast without changing recorded facts. A confirmed new start reanchors the calculation; silence and negative answers do not slide it. This is not evidence that the person's cycles are 28 days, nor a calibrated confidence interval. Preserve the original historical summary. Do not infer ovulation notifications from the imposed narrow range, and do not silently switch policy on reaching an arbitrary sample count.

## Forecast trade-offs

A min/max summary does not identify a mean, distribution or next date. Keep estimate=null until observed start-to-start intervals exist; the implementation waits for two intervals, which is a minimal computation threshold, not evidence of statistical accuracy. Once available, use the last twelve observed intervals' median and observed min/max; all are descriptive, not probabilistic bounds. Do not silently trim a long interval because it looks abnormal. Reassess an ovulation-oriented design with the person if cycle variability remains high or hormonal circumstances change.

NHS says ovulation is difficult to pinpoint and for most women happens about 10–16 days before the next period. This supports explaining uncertainty, not certifying this individual's ovulation. The code propagates the next-period interval backwards by this range. The narrow-interval and two-observation notification gate is an engineering choice to avoid confidently timed alerts, not a clinically validated method. It does not calculate validated fertile days. No reminder should imply safe days outside an interval.

## Public references actually retrieved

- https://www.nhs.uk/conditions/periods/fertility-in-the-menstrual-cycle/ — first bleeding day is cycle day one; variation; uncertain timing of ovulation, around 10–16 days before the next period.
- https://www.nhs.uk/contraception/methods-of-contraception/natural-family-planning/ — proper fertility-awareness methods involve observations and training; app-only predictions are not interchangeable with them.
- https://support.helloclue.com/hc/en-us/articles/14561714219677-What-reminders-are-available-in-the-Clue-app — configurable pre-period/due/late and tracking reminders.
- https://help.flo.health/hc/en-us/articles/4406826523284-Checking-your-cycle-predictions — history improves predictions, suggests at least three cycles; distinguishes predictions from logs.

The links above are public background references preserved from the reviewed
source, not newly fetched during offline packaging. Do not attach a private
person's medical timeline to public research/issues. Live activation is not part
of this snapshot and synthetic tests are not delivery or clinical validation.
