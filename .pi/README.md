# HydraFlow Pi Assets

These assets are installed into target repositories by `hf init` and `make setup`.

## Layout

- `skills/` - reusable task playbooks for `dev.pi`

## Usage

1. Run `make setup` from HydraFlow.
2. Verify target repo contains `.pi/skills/*`.
3. Set stage tools to `pi` in `.env` (for example `HYDRAFLOW_IMPLEMENT_TOOL=pi`).
