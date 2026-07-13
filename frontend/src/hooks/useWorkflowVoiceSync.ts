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
          clear_pending_confirmation: state.clear_pending_confirmation ?? false,
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

// ---------------------------------------------------------------------------
// Manual transfer bridge (#212)
// ---------------------------------------------------------------------------

export const MANUAL_TRANSFER_TOPIC = "taskorbit.manual_transfer";

/** Payload for a UI-picked agent transfer during a voice call; null clears. */
export type ManualTransferVoiceMsg = {
  target_agent_id: string;
  target_agent_name: string;
} | null;

export type ManualTransferVoiceSyncFn = (msg: ManualTransferVoiceMsg) => Promise<void>;

/**
 * Publishes @route menu picks to the voice worker over the data channel.
 * During a voice call there is no typed message to carry manual_transfer,
 * so the worker stores the pick and applies it as a hard transfer on the
 * next voice turn (#212). Mirrors WorkflowVoiceSyncBridge.
 */
export function ManualTransferVoiceBridge({
  onRegister,
}: {
  onRegister: (sync: ManualTransferVoiceSyncFn | null) => void;
}): null {
  const room = useRoomContext();

  useEffect(() => {
    if (!room) {
      onRegister(null);
      return;
    }

    const sync: ManualTransferVoiceSyncFn = async (msg) => {
      const payload = new TextEncoder().encode(
        JSON.stringify(
          msg === null
            ? { type: "manual_transfer", clear: true }
            : {
                type: "manual_transfer",
                target_agent_id: msg.target_agent_id,
                target_agent_name: msg.target_agent_name,
              },
        ),
      );
      await room.localParticipant.publishData(payload, {
        reliable: true,
        topic: MANUAL_TRANSFER_TOPIC,
      });
    };

    onRegister(sync);
    return () => {
      onRegister(null);
    };
  }, [room, onRegister]);

  return null;
}
