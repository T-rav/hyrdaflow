import React from "react";

export default function MockWorldBanner({ active }) {
  if (!active) return null;
  return (
    <div
      role="alert"
      data-testid="mockworld-banner"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        background: "#ff9800",
        color: "#000",
        padding: "8px 16px",
        textAlign: "center",
        fontWeight: 700,
        fontFamily: "monospace",
      }}
    >
      MOCKWORLD MODE — no real GitHub or LLM calls. Issues are simulated.
    </div>
  );
}
