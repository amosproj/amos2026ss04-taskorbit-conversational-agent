import { describe, expect, it } from "vitest";

import { restTtsOptions } from "@/components/ConversationalChat";
import type { AgentConfig } from "@/types/agentConfig";

describe("restTtsOptions", () => {
  it("returns voiceId and modelId for elevenlabs", () => {
    const tts: AgentConfig["tts"] = {
      provider: "elevenlabs",
      model: "eleven_multilingual_v2",
      voice_id: "CwhRBWXzGAHq8TQ4Fs17",
    };
    expect(restTtsOptions(tts)).toEqual({
      voiceId: "CwhRBWXzGAHq8TQ4Fs17",
      modelId: "eleven_multilingual_v2",
    });
  });

  it("returns an empty object for non-elevenlabs providers", () => {
    const tts: AgentConfig["tts"] = {
      provider: "deepgram",
      model: "aura-2-andromeda-en",
      voice_id: "",
    };
    expect(restTtsOptions(tts)).toEqual({});
  });
});
