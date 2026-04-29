import { createBrowserRouter } from "react-router-dom";

import { ConversationalChat } from "@/components/ConversationalChat";
import { Layout } from "@/components/Layout";
import { AgentConfigPage } from "@/pages/AgentConfigPage";
import { HistoryPage } from "@/pages/HistoryPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <ConversationalChat /> },
      { path: "config", element: <AgentConfigPage /> },
      { path: "history", element: <HistoryPage /> },
    ],
  },
]);
