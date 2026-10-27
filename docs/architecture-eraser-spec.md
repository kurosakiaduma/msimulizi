# Msimulizi — Architecture Diagram (Eraser.io Spec)

Paste the block below into [eraser.io](https://app.eraser.io) → New Diagram → Cloud Architecture.
Recommended theme: **Dark**. Export as PNG at 2× for the pitch deck and README.

---

## Eraser.io diagram-as-code

```
// Msimulizi — AI Match Intelligence
// Theme: dark  |  Layout: left-to-right

// ── Colour tokens ──────────────────────────────────────────────
// violet  = #7c3aed   (pipeline / AI services)
// cyan    = #06b6d4   (exposure / API)
// emerald = #10b981   (frontend / UI)
// slate   = #334155   (infrastructure)
// amber   = #f59e0b   (storage)

// ── Event Source ───────────────────────────────────────────────
group EventSource [Event Source] {
  color: slate
  Generator [icon: cpu, label: "Synthetic\nGenerator", color: slate]
  EventHubs [icon: azure-event-hubs, label: "Azure\nEvent Hubs", color: violet]
  FileReplay [icon: file, label: "File\nReplay", color: slate]
}

// ── Intelligence Pipeline ──────────────────────────────────────
group Pipeline [Intelligence Pipeline] {
  color: violet
  Interpreter [icon: activity, label: "Interpreter\nAgent", color: violet]
  MomentAgent [icon: zap, label: "Moment\nAgent", color: violet]
  Personaliser [icon: user, label: "Personaliser\nAgent", color: violet]
  Explainer [icon: book-open, label: "Explainer\nAgent", color: violet]
  Narrator [icon: message-square, label: "Narrator\nAgent\n(gpt-5.4)", color: violet]
  Verifier [icon: check-circle, label: "Verifier\nAgent\n(gpt-5.4-mini)", color: violet]
}

// ── Azure AI Services ──────────────────────────────────────────
group AIServices [Azure AI Services] {
  color: violet
  Foundry [icon: azure-openai, label: "Azure AI\nFoundry\n(gpt-5.4 / 5.4-mini)", color: violet]
  Speech [icon: azure-cognitive-services, label: "Azure AI\nSpeech\n(sw-KE · sw-TZ)", color: violet]
  ContentSafety [icon: shield, label: "Azure AI\nContent Safety", color: violet]
}

// ── Rendering ──────────────────────────────────────────────────
group Rendering [Rendering] {
  color: amber
  Renderer [icon: layers, label: "Overlay\nRenderer", color: amber]
  BlobStorage [icon: azure-blob-storage, label: "Azure Blob\nStorage\n(audio CDN)", color: amber]
}

// ── Data & Observability ───────────────────────────────────────
group DataLayer [Data & Observability] {
  color: slate
  CosmosDB [icon: azure-cosmos-db, label: "Azure\nCosmos DB\n(6 containers)", color: slate]
  AppInsights [icon: azure-monitor, label: "Application\nInsights\n(OTEL metrics)", color: slate]
  KeyVault [icon: azure-key-vault, label: "Azure\nKey Vault", color: slate]
}

// ── API & Gateway ──────────────────────────────────────────────
group Gateway [API & Gateway] {
  color: cyan
  RestAPI [icon: server, label: "FastAPI\nREST", color: cyan]
  WebSocket [icon: radio, label: "WebSocket\nGateway", color: cyan]
  MCPServer [icon: terminal, label: "MCP\nServer", color: cyan]
}

// ── Hosting ────────────────────────────────────────────────────
group Hosting [Azure Container Apps] {
  color: slate
  BackendCA [icon: azure-container-apps, label: "Backend\nContainer App", color: slate]
  FrontendCA [icon: azure-container-apps, label: "Frontend\nContainer App", color: slate]
}

// ── Viewer UI ──────────────────────────────────────────────────
group UI [Viewer UI — Next.js] {
  color: emerald
  CardFeed [icon: layout, label: "Card Feed\n+ Scheduler", color: emerald]
  MatchClock [icon: clock, label: "Match Clock\n+ Score Bar", color: emerald]
  PersonPanel [icon: sliders, label: "Personalisation\nPanel", color: emerald]
  ReviewDash [icon: bar-chart-2, label: "/review\nDashboard", color: emerald]
}

// ── Connections ────────────────────────────────────────────────
Generator --> Interpreter
EventHubs --> Interpreter
FileReplay --> Interpreter

Interpreter --> MomentAgent
MomentAgent --> Personaliser
Personaliser --> Explainer
Explainer --> Narrator
Narrator --> Verifier

Narrator --> Foundry
Verifier --> Foundry
Explainer --> Foundry

Verifier --> Renderer
Renderer --> Speech
Speech --> BlobStorage
Renderer --> CosmosDB

Renderer --> WebSocket
CosmosDB --> RestAPI
CosmosDB --> MCPServer
AppInsights --> ReviewDash
KeyVault --> BackendCA

RestAPI --> CardFeed
WebSocket --> CardFeed
WebSocket --> MatchClock
RestAPI --> PersonPanel
WebSocket --> ReviewDash

ContentSafety --> Verifier
ContentSafety --> Renderer
```

The spoken-script adapter is not a seventh agent. It reuses the mini
deployment after the caption is rendered, and it is deliberately outside the
verified card path: the caption stays authoritative, and audio falls back to
the caption if the rewrite is rejected.

---

## Colour and style notes for Eraser

- Set the diagram background to `#0a0a0f` (matches the UI dark base).
- Group borders: use `#7c3aed` for the Pipeline and AI Services groups, `#06b6d4` for Gateway, `#10b981` for UI.
- Arrow style: **curved**, weight **1.5px**, colour `#52525b`.
- Export at **2× PNG**, 1920 px wide minimum, for use in the pitch deck.
- For the README, export at **1× PNG** or use the embedded Mermaid diagram instead (GitHub renders Mermaid natively).

---

## Which to use where

| Context | Format |
|---|---|
| GitHub README | Mermaid (renders inline, no image needed) |
| Pitch deck slide | Eraser.io PNG export (2× dark) |
| `/about` page in the UI | Either — link to the README or embed the Eraser PNG |
| Innovation Studio submission | Eraser.io PNG attached to the project description |
