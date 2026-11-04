import { z } from 'zod';

export const voiceCapabilitiesSchema = z.object({
  enabled: z.boolean(),
  speech_enabled: z.boolean(),
  transcription_model: z.string().min(1),
  max_audio_bytes: z.number().int().positive(),
  requests_per_minute: z.number().int().positive(),
  supported_containers: z.array(z.string().min(1)),
  max_speech_characters: z.number().int().positive(),
  requires_confirmation: z.literal(true),
});

export const voiceTranscriptionSchema = z.object({
  text: z.string().trim().min(1),
  model: z.string().min(1),
  requires_confirmation: z.literal(true),
});

export type VoiceCapabilities = z.infer<typeof voiceCapabilitiesSchema>;
export type VoiceTranscription = z.infer<typeof voiceTranscriptionSchema>;
