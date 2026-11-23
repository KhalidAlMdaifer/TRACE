import "@fontsource/instrument-sans/400.css";
import "@fontsource/instrument-sans/500.css";
import "@fontsource/instrument-sans/600.css";
import "@fontsource/dm-mono/400.css";
import "@fontsource/dm-mono/500.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Component, StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 5_000 } } });

/** If anything throws while drawing, say so and offer a way back; never a blank page. */
class Boundary extends Component<{ children: ReactNode }, { broken: boolean }> {
  state = { broken: false };
  static getDerivedStateFromError() { return { broken: true }; }
  render() {
    if (!this.state.broken) return this.props.children;
    return (
      <main className="signin">
        <form onSubmit={(e) => { e.preventDefault(); window.location.reload(); }}>
          <h1 style={{ fontSize: 28 }}>Something went wrong</h1>
          <p className="muted" role="alert">The page hit an error it could not recover from. Your case is saved; reloading brings it back.</p>
          <button type="submit" className="pill primary">Reload</button>
        </form>
      </main>
    );
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <Boundary><App /></Boundary>
    </QueryClientProvider>
  </StrictMode>,
);
