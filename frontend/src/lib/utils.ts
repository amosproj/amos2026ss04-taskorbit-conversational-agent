import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Combine Tailwind classes safely.
 * Used by every shadcn/ui component 
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
