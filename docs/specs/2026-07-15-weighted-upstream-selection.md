# Weighted / Priority Upstream Selection

**Status**: Proposed  
**Date**: 2026-07-15  
**Issue**: Currently upstreams are tried strictly in list order — the first healthy upstream always wins. This means the "pool" is really a fallback chain, not a load-balanced pool.

---

## 1. The Problem

Currently, given this config:

```yaml
virtual_models:
  coding:
    upstreams:
      - name: nvidia-glm
        provider: nvidia
        model: z-ai/glm-5.2
      - name: openrouter-glm
        provider: openrouter
        model: z-ai/glm-5.2
```

The router always tries `nvidia-glm` first, and only tries `openrouter-glm` if NVIDIA returns a retryable error. Even if both are healthy, NVIDIA gets 100% of traffic. This means:

- **Rate limits**: One provider gets hammered while another sits idle
- **Cost**: You can't split traffic 70/30 between cheap and expensive providers
- **Testing**: You can't canary a small percentage of traffic to a new provider
- **No true load balancing**: Adding more upstreams doesn't distribute load

## 2. Design

Add two optional fields to the upstream config:

- **`priority`** (int, default `1`) — Lower number = higher priority. Upstreams are tried by priority tier (all priority-1 upstreams before any priority-2 upstreams). Within a tier, traffic is distributed by weight.
- **`weight`** (int, default `100`) — Relative request distribution within a priority tier. A weight-60 upstream gets 60% of traffic, a weight-40 gets 40%.

### Config Shape

```yaml
virtual_models:
  coding:
    upstreams:
      # Priority 1 — load-balanced pool (70% NVIDIA, 30% OpenRouter)
      - name: nvidia-glm
        provider: nvidia
        model: z-ai/glm-5.2
        priority: 1
        weight: 70
      - name: openrouter-glm
        provider: openrouter
        model: z-ai/glm-5.2
        priority: 1
        weight: 30

      # Priority 2 — cheap backup, only tried if all priority-1 are down
      - name: fallback-glm
        provider: cheap-provider
        model: z-ai/glm-5.2
        priority: 2
        weight: 100
```

### Behavior Matrix

| Scenario | What happens |
|----------|-------------|
| All priority-1 upstreams healthy | Traffic distributed by weight (70/30) |
| One priority-1 upstream opens circuit | Removed from selection pool; remaining upstream(s) get 100% |
| All priority-1 upstreams unhealthy | Fall through to priority-2 tier |
| Weights sum to 100 (or any value) | Normalized: each weight / sum(weights) |
| Weight omitted (default 100) | Even distribution (100/100 = 50/50 split) |
| Only one upstream in tier | Gets 100% of traffic regardless of weight |
| Priority omitted (default 1) | All upstreams in same tier, distributed by weight |
| Circuit breaker opens during weighted selection | Upstream removed from the tier's rotation until circuit closes |

### Interaction with Existing Failover Logic

The weighted selection **replaces the strict list-order iteration** but lives **inside** the existing failover loop in `_failover_loop()`:

```
for each priority tier (sorted ascending):
    pick upstream by weight from the tier
        ↑ replaces: for upstream in virtual.upstreams:
    circuit breaker check → skip if open
    try_upstream(upstream, attempts)  ← existing callback
    
    if success: return immediately
    if retryable error: pick next upstream from the same tier by weight
    if all upstreams in tier exhausted: move to next priority tier
    if all tiers exhausted: return 503
```

This means the weighted selection **composes with** the circuit breaker, metrics, decision logging, streaming, and all existing error handling — those don't change.

## 3. Implementation Plan

### Phase 1: Config Layer (`config.py`)

**Changes needed:**

1. **Add `priority` and `weight` fields to `UpstreamConfigModel`** (the Pydantic validation model):
   ```python
   class UpstreamConfigModel(BaseModel):
       model_config = ConfigDict(extra="ignore")
       name: str | None = None
       provider: str | None = None
       base_url: str | None = None
       api_key_env: str | None = None
       model: str | None = None
       headers: dict[str, Any] = Field(default_factory=dict)
       timeout_seconds: float | None = None
       connect_timeout_seconds: float | None = None
       write_timeout_seconds: float | None = None
       pool_timeout_seconds: float | None = None
       priority: int = 1        # ← NEW
       weight: int = 100        # ← NEW
   ```

2. **Add `priority` and `weight` to the `Upstream` frozen dataclass:**
   ```python
   @dataclass(frozen=True)
   class Upstream:
       name: str
       base_url: str
       model: str
       api_key_env: str = ""
       timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
       headers: dict[str, str] = field(default_factory=dict)
       connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
       write_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
       pool_timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS
       priority: int = 1        # ← NEW
       weight: int = 100        # ← NEW
   ```

3. **Thread them through `_normalize_upstream()`:** The function already maps `UpstreamConfigModel` → `Upstream`. This is where `priority` and `weight` get copied over.

4. **Validation:** Add checks in `_validate_normalized_config()`:
   - `weight` must be >= 1 (default 100)
   - `priority` must be >= 1 (default 1)

**No changes needed to:** `VirtualModel`, `VirtualModelConfigModel`, `RouterConfig`, `ProviderConfigModel` — the priority/weight live on the upstream, not the model or provider.

### Phase 2: Selection Logic (`service.py`)

**Changes needed:**

1. **Add `_select_upstreams_by_tier()` helper** on `RichardRouter`:

```python
@staticmethod
def _select_upstreams_by_tier(upstreams: tuple[Upstream, ...]) -> List[Tuple[int, List[Upstream]]]:
    """Group upstreams by priority tier, sorted ascending.
    
    Returns [(1, [upstream_a, upstream_b]), (2, [upstream_c]), ...]
    """
    tiers: dict[int, list[Upstream]] = {}
    for upstream in upstreams:
        tiers.setdefault(upstream.priority, []).append(upstream)
    return sorted(tiers.items())
```

2. **Add `_pick_weighted_upstream()` helper** for weighted random selection within a tier:

```python
@staticmethod
def _pick_weighted_upstream(tier: list[Upstream], seed: int | None = None) -> Upstream:
    """Pick an upstream from the tier using weighted random selection.
    
    An upstream with weight 70 gets selected 70% of the time vs
    an upstream with weight 30.
    """
    total = sum(u.weight for u in tier)
    rand = seed if seed is not None else random.random()
    target = rand * total
    cumulative = 0.0
    for upstream in tier:
        cumulative += upstream.weight
        if target <= cumulative:
            return upstream
    return tier[-1]  # fallback
```

3. **Modify `_failover_loop()`** to iterate by tier + weighted selection instead of simple list order:

```python
async def _failover_loop(self, virtual, try_upstream, *, stream):
    attempts: list[Attempt] = []
    tiers = self._select_upstreams_by_tier(virtual.upstreams)
    
    for _, tier in tiers:
        while True:
            # Build active pool: upstreams in this tier that aren't circuit-open
            active = [u for u in tier if self._circuit_open_attempt(u) is None]
            if not active:
                break  # all upstreams in this tier are open
            
            # Pick by weight
            upstream = self._pick_weighted_upstream(active)
            
            for _ in range(self.config.failover.max_attempts_per_upstream):
                # ... existing logic: circuit check, try_upstream, error handling ...
                # On retryable error: re-pick from remaining active upstreams
                # On circuit open: upstream removed from tier, re-pick
                # On success: return
            # All retries on this upstream exhausted, re-pick next one
        # Tier exhausted, fall through to next priority
    return self._all_failed(attempts, virtual.name, stream=stream)
```

**Key design decisions:**

- **Re-pick on each try**: After a retryable error, we re-pick from the active pool. This means if you have 3 upstreams at weights 50/30/20 and the first pick (50) returns 503, the next pick is still weighted (but from 2 upstreams). This gives better load distribution than fixed ordering.
- **Hot upstreams don't need to be removed from the tier**: The circuit breaker handles that. A circuit-open upstream simply isn't in `active`.
- **Streaming**: For streaming requests, failover can still happen before the upstream accepts the stream (same as today). Once a stream starts, we don't switch mid-stream.

### Phase 3: Metrics & Observability

The existing `/v1/pool` endpoint and `richard-router status` CLI already show per-upstream metrics. No changes needed — they'll naturally reflect the new distribution.

### Phase 4: Example & Docs

Update `config/router.example.yaml` with a comment showing the priority/weight fields.

## 4. Existing Tests — Zero Changes Needed

The feature is purely additive: missing `priority`/`weight` defaults to `1`/`100`, and a single-tier all-weight-100 selection behaves identically to the current list-order iteration (all upstreams in the same "pool", weight doesn't affect order). In fact, with all weights equal and all priorities equal, the only difference is that selection is random instead of ordered — but the existing tests mock the handler to return specific responses, so the exact order within a tier doesn't matter for behavior assertions.

**No existing test would break.**

## 5. New Tests

| Test | What it proves |
|------|---------------|
| `test_weighted_70_30_distribution` | With weights 70/30 and 100 calls, each upstream gets roughly its share (±15% tolerance) |
| `test_priority_tier_exhaustion` | All priority-1 upstreams fail → priority-2 upstream tried |
| `test_fallback_to_next_tier_on_circuit_open` | All priority-1 circuits open → skip to priority-2 |
| `test_default_weight_provides_even_distribution` | Omitting weight → even distribution between 2 upstreams |
| `test_single_upstream_gets_100_percent` | Only one upstream in tier → always selected |
| `test_weight_equal_with_different_weights` | Weights 50/50 → approximately even (random, within tol) |
| `test_priority_invalid_values_rejected` | Config validation rejects priority < 1 or weight < 1 |
| `test_weighted_back_compat_same_as_list_order` | A single-tier with all weight=100 behaves identically to the old list-order for deterministic tests |

## 6. Config Example (updated)

```yaml
virtual_models:
  coding:
    owned_by: richard-router
    context_length: 128000
    upstreams:
      - name: nvidia-glm
        provider: nvidia
        model: z-ai/glm-5.2
        priority: 1
        weight: 70
      
      - name: openrouter-glm
        provider: openrouter
        model: z-ai/glm-5.2
        priority: 1
        weight: 30

      # Priority uplift: if neither NVIDIA is available, use DeepSeek directly
      - name: deepseek-fallback
        base_url: https://api.deepseek.com/v1
        api_key_env: DEEPSEEK_API_KEY
        model: deepseek-chat
        priority: 2
        weight: 100
```

## 7. File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `config.py` | MODIFY | Add `priority`, `weight` to `UpstreamConfigModel` and `Upstream`. Thread through `_normalize_upstream()`. Add validation. |
| `service.py` | MODIFY | Add `_select_upstreams_by_tier()`, `_pick_weighted_upstream()`. Modify `_failover_loop()` to iterate by tier + weight. No changes to helpers or callback contract. |
| `config/router.example.yaml` | MODIFY | Add priority/weight doc example |
| `tests/test_upstream_selection.py` | NEW | 8+ tests for weighted selection |
| `docs/specs/...` | NEW | This spec |
