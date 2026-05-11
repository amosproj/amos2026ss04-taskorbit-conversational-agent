/**
 * Stop / Send pair shown only while the user is actively recording.
 *
 * - Stop  → mute the mic but stay in the call so the user can compose
 *           themselves and tap the mic again to resume.
 * - Send  → commit the current utterance to the agent for processing.
 *           In the streaming architecture this just disables the mic
 *           and the agent's VAD finalises the turn — keeping a
 *           dedicated button preserves the ChatGPT-style mental model.
 */

import { Pause, Send } from "lucide-react";

import { Button } from "@/components/ui/button";

type Props = {
  onStop: () => void;
  onSend: () => void;
  disabled?: boolean;
};

export function RecordingControls({ onStop, onSend, disabled }: Props) {
  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label="Recording controls"
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onStop}
        disabled={disabled}
      >
        <Pause data-icon="inline-start" className="size-3.5" />
        Pause
      </Button>
      <Button
        type="button"
        size="sm"
        onClick={onSend}
        disabled={disabled}
        className="bg-primary text-primary-foreground"
      >
        <Send data-icon="inline-start" className="size-3.5" />
        Send
      </Button>
    </div>
  );
}
