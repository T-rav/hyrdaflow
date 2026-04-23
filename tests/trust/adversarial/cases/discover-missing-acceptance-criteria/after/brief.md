## Intent

Give end users a way to switch the application into dark mode so the UI
is easier on the eyes in low-light environments and matches their OS
preference where possible. This has been a long-standing request in the
community forum and is table stakes for our enterprise customers who
run the app on kiosks at night.

## Affected area

- `src/ui/settings/` — settings page where the toggle will live
- `src/ui/theme.ts` — theme token definitions and CSS variable bindings
- The shared component library's `<ThemeProvider>` wrapper

## Open questions

- Should the preference persist per-device (localStorage) or per-account
  (server-side profile)? Per-account roams across devices but requires
  a schema migration.

## Known unknowns

- Accessibility in dark mode: do any of our current colour tokens fail
  WCAG AA contrast when inverted? We have not audited this yet.
