/**
 * Registers a publisher for workflow state on the LiveKit data channel so the
 * voice worker stays aligned when the user approves prerequisite steps via the
 * text UI (Proceed / Cancel) while a voice session is active.
 */

import { useRoomContext } from "@livekit/components-react";
import { useEffect } from "react";

export const WORKFLOW_STATE_TOPIC = "taskorbit.workflow_state";

export type WorkflowVoiceState = {
  selected_agent?: string | null;
  completed_workflow_steps?: string[];
  clear_pending_confirmation?: boolean;
};

export type WorkflowVoiceSyncFn = (state: WorkflowVoiceState) => Promise<void>;

type Props = {
  onRegister: (sync: WorkflowVoiceSyncFn | null) => void;
};

export function WorkflowVoiceSyncBridge({ onRegister }: Props): null {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) {
      onRegister(null);
      return;
    }

    const sync: WorkflowVoiceSyncFn = async (state) => {
      const payload = new TextEncoder().encode(
        JSON.stringify({
          type: "workflow_state",
          selected_agent: state.selected_agent ?? null,
          completed_workflow_steps: state.completed_workflow_steps ?? [],
          clear_pending_confirmation: state.clear_pending_confirmation ?? true,
        }),
      );
      await room.localParticipant.publishData(payload, {
        reliable: true,
        topic: WORKFLOW_STATE_TOPIC,
      });
    };

    onRegister(sync);
    return () => {
      onRegister(null);
    };
  }, [room, onRegister]);

  return null;
}
