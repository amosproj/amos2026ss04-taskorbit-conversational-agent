import { RouterProvider } from "react-router-dom";

import { router } from "@/router";

/**
 * App entry — delegates to the data router which wires Layout + the three
 * routes for the conversational agent (chat / config / history) per #5.
 */
export function App() {
  return <RouterProvider router={router} />;
}
