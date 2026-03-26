# Sentry Alert Configuration for HydraFlow

## Recommended Alerts

### Error Alerts
| Alert | Query | Threshold | Action |
|-------|-------|-----------|--------|
| Pipeline error spike | `event.type:error` | >5 in 10 min | Slack #hydraflow-alerts |
| Credit exhaustion | `CreditExhaustedError` | Any occurrence | Immediate Slack + email |
| New error type | First seen | Any | Slack |

### Performance Alerts
| Alert | Metric | Threshold | Action |
|-------|--------|-----------|--------|
| Slow agent | `memory.first_pass_rate` | <0.2 for 1 hour | Slack |
| Score drift | `memory.avg_score` | Drops >15% in 24h | Slack |
| Learning stall | `memory.stale_items` | >20 for 48h | Slack |
| Adjustment storm | Auto-adjustment count | >5 in 24h | Slack + HITL |
| Factory divergence | Per-project first_pass_rate | Diverges >30% from avg | Investigate |

### Setup Instructions
1. Go to Sentry → Alerts → Create Alert
2. Select "Custom Metric" for performance alerts
3. Configure threshold and action channels
4. Set environment filter to match HYDRAFLOW_ENV
