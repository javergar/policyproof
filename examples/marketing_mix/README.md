# A media plan for a budget

An optimizer picks the most profitable way to split a media budget across SKUs and channels, and `policyproof` proves
that the plan follows the marketing guidelines. No model, no account: Z3 does both.

```bash
uv run python examples/marketing_mix/plan.py
```

| File | What it is |
|---|---|
| `guidelines.md` | The guidelines, as the marketing and finance teams would write them (G1 to G7). |
| `policy.yaml` | The same guidelines as a policy: the plan's spend per SKU and channel goes in, `go` or `revise` comes out. |
| `planning_data.json` | Made-up numbers standing in for the planning tools: SKU margin, stock and launches, each channel's funnel stage, and funnel performance per SKU and channel. |
| `plan.py` | Optimises, proves and reports. |

## How it works

1. **The tools supply the facts.** The budget, each SKU's weeks of stock and whether it launches this quarter enter
   the policy as system facts, like any other case.
2. **Performance becomes a response curve.** For every SKU and channel, revenue per dollar starts at the fitted value
   and falls block by block as the channel saturates. With the SKU's margin, that gives the margin each block of spend
   earns after its cost.
3. **The optimizer maximises margin under the policy's own rules.** `optimise` hands Z3 the compiled policy, the facts,
   the curves and one demand, `approved`, so the guidelines exist once and no translation can drift from them. It
   doesn't spend money that would lose margin, so the best plan can come in under budget.
4. **`decide` proves the plan.** The finished plan is checked as an ordinary case: approved with the guidelines that
   prove it, the one question still open, or refused. `broken` lists every guideline a plan breaks, and `clash` names
   the guidelines that together leave no plan approvable.

## What it shows

1. **The best plan without legal sign-off** uses no TV (G4), puts AeroLite's launch support into social (G6), gives
   Classic Canvas nothing for search or retail media because it has 1.5 weeks of stock (G7), and is approved.
2. **With legal sign-off** TV opens up and the predicted margin rises by $155k. Until legal answers, that plan can't
   be approved: the policy asks "Has legal signed off the TV creative?" and says what each answer leads to. The
   approval worth chasing comes out of the numbers.
3. **Last quarter's plan** is refused because it breaks G2 (search was 42% of the budget) and G7 (it bought search
   for the low-stock SKU).
4. **Finance's proposed G8** ("at least 80% to the lower funnel") is refused before any plan is made: with G1 and G5
   no plan could ever be approved, and the report names those two.

## Making it real

- Replace `planning_data.json` with calls to your tools, and the curves with ones from your marketing mix model.
- Grow the policy with your guidelines. Write them in `guidelines.md` first, and use `policyproof studio` to turn
  them into rules and fix contradictions in plain English.
- For a large catalogue, search with a linear-programming solver (HiGHS, OR-Tools) and keep `decide` as the final
  proof that the plan follows the guidelines.
- Put an agent on top for what-if questions and explanations, and check its claims about the plan with
  `guard_reply` before anyone reads them.
