# Workshop Module 07: Compaction and Long Conversations

## Learning Objectives
- Understand why compaction is necessary for long advisory sessions
- Configure `TokenBudgetComposedStrategy`
- Observe compaction in action via App Insights
- Tune compaction parameters for your use case

## Why Compaction?

GPT-4o has a 128k token context window. A long financial advisory session — with
multiple back-and-forth questions, tool call outputs, and market data snippets —
can easily exceed this limit. Without compaction, old messages are simply dropped,
losing critical context (e.g., "as we discussed earlier, your tech weighting is...").

`CompactionProvider` with `TokenBudgetComposedStrategy` automatically summarises
older conversation turns when the token budget is approached, preserving semantic
content while reducing token usage.

## Configuration

```python
from agent_framework.compaction import CompactionProvider, TokenBudgetComposedStrategy

compaction = CompactionProvider(
    strategy=TokenBudgetComposedStrategy(
        token_budget=100_000,   # summarise when exceeding 100k tokens
    )
)

async with Agent(
    client=client,
    instructions="...",
    context_providers=[history_provider, search_provider, compaction],
) as agent:
    ...
```

## How TokenBudgetComposedStrategy Works

1. Before each agent call, the framework measures the total token count of the conversation history
2. If `token_budget` is exceeded, the strategy generates a summary of older turns
3. The summary replaces the raw old messages in the context window
4. Recent turns are preserved verbatim for immediate context
5. The summary is stored back to Cosmos DB for the session

## Exercise 1: Simulate a long conversation

Send 20+ messages to the same session to build up conversation history:

```bash
SESSION="long-conv-test"
for i in $(seq 1 25); do
  curl -s -X POST http://localhost:8000/api/chat/message \
    -H "Content-Type: application/json" \
    -d "{\"message\": \"Tell me about company number $i in my portfolio\", \"session_id\": \"$SESSION\"}" \
    | jq -r '.[-1].content // "..."' | head -c 100
  echo ""
done
```

## Exercise 2: Observe compaction in App Insights

1. Navigate to App Insights in the Azure portal
2. Go to Logs → run this KQL query:

```kusto
traces
| where message contains "compaction" or message contains "summariz"
| project timestamp, message, severityLevel
| order by timestamp desc
| take 20
```

You should see compaction events logged when the token budget is exceeded.

## Exercise 3: Tune the budget

In `backend/app/workflows/portfolio_workflow.py`, find `_get_compaction_provider()`.

Try different budgets:
- `token_budget=50_000` — aggressive compaction (more summarisation, lower cost)
- `token_budget=120_000` — conservative (preserve more raw context, higher cost)

Observe the trade-off between response coherence and token consumption.

## Key Code References
- [backend/app/workflows/portfolio_workflow.py](../../backend/app/workflows/portfolio_workflow.py) — `_get_compaction_provider()`

## Next: [Module 08 — Evaluation](./08-evaluation.md)
