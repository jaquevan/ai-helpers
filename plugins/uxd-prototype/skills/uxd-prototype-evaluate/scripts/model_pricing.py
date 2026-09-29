"""Pinned standard API price card (USD per million tokens).

Short-context rates are used through 272,000 input tokens per response. For
GPT-5.6 and GPT-6 models, responses above that threshold use the configured
long-context rates for the full response. Source:
https://developers.openai.com/api/docs/pricing (verified 2026-09-28).
These are estimates from provider-reported token usage, not an invoice.
"""

PRICING = {
    "gpt-6-luna": (0.10, 0.01, 0.125, 0.50),
    "gpt-6-sol": (2.00, 0.20, 2.50, 10.00),
    "gpt-5.6-luna": (0.20, 0.02, 0.25, 1.20),
    "gpt-5.6-terra": (2.00, 0.20, 2.50, 12.00),
    "gpt-5.6-sol": (4.00, 0.40, 5.00, 20.00),
}

LONG_CONTEXT_INPUT_THRESHOLD = 272_000
LONG_CONTEXT_PRICING = {
    "gpt-6-sol": (4.00, 0.40, 5.00, 15.00),
    "gpt-6-luna": (0.20, 0.02, 0.25, 0.75),
    "gpt-5.6-luna": (0.40, 0.04, 0.50, 1.80),
    "gpt-5.6-terra": (4.00, 0.40, 5.00, 18.00),
    "gpt-5.6-sol": (8.00, 0.80, 10.00, 30.00),
}


def estimated_cost(model, input_tokens, output_tokens, cached_input_tokens=0, cache_write_tokens=0):
    try:
        rates = PRICING[model]
    except KeyError as error:
        raise ValueError(f"No pinned OpenAI pricing for {model}") from error
    values = (input_tokens, output_tokens, cached_input_tokens, cache_write_tokens)
    if any(not isinstance(value, int) or value < 0 for value in values):
        raise ValueError("Provider token usage must contain nonnegative integers")
    if cached_input_tokens + cache_write_tokens > input_tokens:
        raise ValueError("Cache reads and writes exceed provider-reported input tokens")
    if input_tokens > LONG_CONTEXT_INPUT_THRESHOLD:
        rates = LONG_CONTEXT_PRICING.get(model, rates)
    input_rate, cached_rate, write_rate, output_rate = rates
    uncached = input_tokens - cached_input_tokens - cache_write_tokens
    return round((uncached * input_rate + cached_input_tokens * cached_rate
                  + cache_write_tokens * write_rate + output_tokens * output_rate) / 1_000_000, 8)
