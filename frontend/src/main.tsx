import "@mantine/core/styles.css";
import "./styles.css";

import { createTheme, MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";

const theme = createTheme({
  primaryColor: "violet",
  primaryShade: 6,
  fontFamily: 'Inter, "Segoe UI", Arial, sans-serif',
  headings: { fontFamily: 'Inter, "Segoe UI", Arial, sans-serif' },
  defaultRadius: "md",
  colors: {
    violet: [
      "#f2efff",
      "#e2dcff",
      "#c5b9ff",
      "#a895fb",
      "#927cf7",
      "#836cf3",
      "#7d69ee",
      "#6956d8",
      "#5e4bc1",
      "#4f3fa9",
    ],
  },
});

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="light">
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </MantineProvider>
  </React.StrictMode>,
);
