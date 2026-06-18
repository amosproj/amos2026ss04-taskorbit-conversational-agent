// Single source of truth for pipeline models and voices (ticket #87). Lists are curated, not exhaustive; withCurrent keeps legacy values selectable (AC5).

import type { LlmProvider, SttProvider, TtsProvider } from "@/types/agentConfig";

export const LLM_MODELS: Record<LlmProvider, string[]> = {
  openai: ["gpt-4o-mini", "gpt-4o"],
  gemini: ["gemini-2.5-flash", "gemini-2.5-pro"],
  openrouter: [
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-7b-instruct:free",
    "google/gemma-3-12b-it:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-7b-instruct:free",
  ],
};

// Index 0 of each provider's list is the default applied on provider switch — reordering changes this.
export const LLM_MODEL_DEFAULTS: Record<LlmProvider, string> = {
  openai: LLM_MODELS.openai[0],
  gemini: LLM_MODELS.gemini[0],
  openrouter: LLM_MODELS.openrouter[0],
};

export const STT_MODELS: Record<SttProvider, string[]> = {
  deepgram: ["nova-3", "nova-2"],
  elevenlabs: ["scribe_v2_realtime"],
};

export const TTS_MODELS: Record<TtsProvider, string[]> = {
  elevenlabs: ["eleven_multilingual_v2", "eleven_flash_v2_5"],
  deepgram: ["aura-2-andromeda-en", "aura-2-asteria-en", "aura-2-orion-en"],
};

// Voices are stored by id but shown by name; the dropdown renders the readable
// name while `value.tts.voice_id` keeps the raw id the voice worker expects.
export const TTS_VOICES: { name: string; id: string }[] = [
  { name: "Roger", id: "CwhRBWXzGAHq8TQ4Fs17" },
  { name: "Jessica", id: "cgSgspJ2msm6clMCkdW9" },
  { name: "Chris", id: "iP95p4xoKVk53GoZ742B" },
  { name: "Eric", id: "cjVigY5qzO86Huf0OWal" },
];

export const TTS_VOICE_DEFAULT: string = TTS_VOICES[0].id;

// options can be undefined when a saved config carries a provider string not present in the Record.
export function withCurrent(options: string[] | undefined, current: string): string[] {
  const base = options ?? [];
  if (current && !base.includes(current)) return [...base, current];
  return base;
}
