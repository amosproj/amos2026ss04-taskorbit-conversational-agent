/**
 * Maps the LiveKit room connection state to a small enum the UI can
 * react to. The livekit-client itself handles auto-reconnect on
 * transient drops; we just surface "we are currently retrying" so the
 * call surface can render a banner instead of going stale.
 *
 * Must be used inside a `<LiveKitRoom>`.
 */

import { useConnectionState } from "@livekit/components-react";
import { ConnectionState } from "livekit-client";

export type CallConnectionStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

export function useConnectionStatus(): CallConnectionStatus {
  const state = useConnectionState();
  switch (state) {
    case ConnectionState.Connecting:
      return "connecting";
    case ConnectionState.Connected:
      return "connected";
    case ConnectionState.Reconnecting:
    case ConnectionState.SignalReconnecting:
      return "reconnecting";
    case ConnectionState.Disconnected:
    default:
      return "disconnected";
  }
}
