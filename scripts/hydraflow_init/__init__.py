"""Emit a superpowers-chained remediation prompt from an audit report.

`make init` consumes `.hydraflow/audit-report.json` and templates a plan that
a human can paste into a Claude Code session. Greenfield mode (most checks
FAIL) opens with brainstorming; incremental adoption skips brainstorming and
dives into writing-plans. Either way the plan ends with a verification step
that re-runs `make audit`.
"""
