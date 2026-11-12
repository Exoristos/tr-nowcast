// site/vitest.config.ts — testler workerd (Cloudflare vitest entegrasyonu) içinde koşar;
// worker handler'ı doğrudan çağrılıp mock binding ile test edilir (gerçek LLM yok).
// Not: @cloudflare/vitest-pool-workers deprecated; resmi halefi @cloudflare/vitest-plugin.
import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      miniflare: {
        compatibilityDate: "2026-10-01",
      },
    }),
  ],
});
