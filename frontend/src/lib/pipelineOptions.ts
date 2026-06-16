/**
 * Single source of truth for the selectable pipeline models and voices that
 * the agent-config form offers (ticket #87).
 *
 * To add or remove a model or voice, edit this file and redeploy. No other
 * file needs changing.
 *
 * The lists are deliberately curated, not exhaustive: they cover the standard
 * models for the providers TaskOrbit currently ships. A config may still carry
 * a value that isn't listed here (a legacy preset, or an env-default the form
 * never wrote) — `withCurrent` keeps such values selectable so the dropdown
 * never silently drops them (AC5).
 */

import type { LlmProvider, SttProvider, TtsProvider } from "@/types/agentConfig";

export const LLM_MODELS: Record<LlmProvider, string[]> = {
  openai: ["gpt-4o-mini", "gpt-4o"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro"],
};

// First model of each provider's list is the default applied on provider switch.
export const LLM_MODEL_DEFAULTS: Record<LlmProvider, string> = {
  openai: LLM_MODELS.openai[0],
  gemini: LLM_MODELS.gemini[0],
};

export const STT_MODELS: Record<SttProvider, string[]> = {
  deepgram: ["nova-3", "nova-2"],
  elevenlabs: ["scribe_v2_realtime"],
};

export const STT_MODEL_DEFAULT: string = STT_MODELS.deepgram[0];

export const TTS_MODELS: Record<TtsProvider, string[]> = {
  elevenlabs: ["eleven_multilingual_v2", "eleven_flash_v2_5"],
  deepgram: ["aura-2-andromeda-en", "aura-2-asteria-en", "aura-2-orion-en"],
};

export const TTS_MODEL_DEFAULT: string = TTS_MODELS.elevenlabs[0];

// Voices are stored by id but shown by name; the dropdown renders the readable
// name while `value.tts.voice_id` keeps the raw id the voice worker expects.
export const TTS_VOICES: { name: string; id: string }[] = [
  { name: "Roger", id: "CwhRBWXzGAHq8TQ4Fs17" },
  { name: "Jessica", id: "cgSgspJ2msm6clMCkdW9" },
  { name: "Chris", id: "iP95p4xoKVk53GoZ742B" },
  { name: "Eric", id: "cjVigY5qzO86Huf0OWal" },
];

export const TTS_VOICE_DEFAULT: string = TTS_VOICES[0].id;

/**
 * Returns `options` with `current` appended when it holds a value that isn't
 * already listed. Keeps legacy / env-default values selectable so loading an
 * older config never drops the user's stored choice from the dropdown (AC5).
 */
export function withCurrent(options: string[], current: string): string[] {
  if (current && !options.includes(current)) {
    return [...options, current];
  }
  return options;
}
